"""The resolution pipeline shared by night, dusk and instant actions.

Rule of simultaneity: everything that resolves at the same moment reads the
state as it was at the start of that moment. Roles never mutate state while
being evaluated - they emit intents (`inform`, `kill`, `commit`) that are
applied together in the commit pass. Only the explicitly modelled
interactions (curses, locks, stalks, protections, visits) influence other
actions within the same resolution.

Order of a resolution:
  1. prepare hooks        (e.g. the wolf pack turns its ballot into an attack)
  2. interaction pass     interact_<ability> for priority < LOCK (curses)
  3. movement             visits are built from house-leaving actions
  4. interaction pass     interact_<ability> for LOCK <= priority < INFO
                          (locks, stalks, protections - may block visits)
  5. on_visited hooks
  6. evaluation pass      resolve_<ability> for every action that wasn't blocked
  7. commit pass          early commits -> kills + death cascade -> late commits
                          -> after_resolution hooks -> messages
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterable, Sequence

from Core.abilities import Priority
from Core.effects import PrivateMessage
from Core.state import (
    ActionStatus,
    DeathRecord,
    GameState,
    LifeState,
    Player,
    SubmittedAction,
)

if TYPE_CHECKING:
    from Core.actor import Actor


@dataclass
class Visit:
    visitor: int
    target: int | None           # house visited; None = left the house without visiting anyone
    action_id: int | None
    source: str                  # role/modifier name (or "werewolves" for the pack)
    ability: str
    pack: bool = False
    blocked: bool = False        # tried to leave/visit but was stopped
    reason: str = ""


@dataclass
class Kill:
    target: int
    cause: str
    killers: list[int] = field(default_factory=list)
    killer_role: str | None = None
    attacker_faction: str | None = None
    enters_house: bool = True
    unstoppable: bool = False    # heartbreak, GM kills: ignores protections
    public: bool = False         # lynch: public immediately
    action_id: int | None = None
    prevented_by: str | None = None
    processed: bool = False


@dataclass
class Protection:
    label: str
    applies: Callable[[Kill], bool]


SECTIONS = (
    "Actions", "Movement", "Blocked", "Protections", "Info", "Conversions",
    "Kills", "Deaths", "Newspaper", "Win check", "Notes",
)


class Report:
    def __init__(self, title: str):
        self.title = title
        self.sections: dict[str, list[str]] = {s: [] for s in SECTIONS}

    def add(self, section: str, line: str) -> None:
        self.sections.setdefault(section, []).append(line)

    def render(self) -> str:
        parts = [f"# {self.title}"]
        for section, lines in self.sections.items():
            if lines:
                parts.append(f"\n## {section}")
                parts.extend(f"- {line}" for line in lines)
        if len(parts) == 1:
            parts.append("\nNothing happened.")
        return "\n".join(parts)


@dataclass
class Outcome:
    report: str
    deaths: list[tuple[int, str]]
    messages: dict[int, list[str]]


# hooks run at the start of every resolution, e.g. the wolf pack's attack.
# Signature: hook(ctx) -> None
PREPARE_HOOKS: list[Callable[["Resolution"], None]] = []
# hooks run after the death cascade, e.g. win checks. Signature: hook(ctx) -> None
FINAL_HOOKS: list[Callable[["Resolution"], None]] = []


def register_prepare_hook(fn: Callable[["Resolution"], None]) -> Callable[["Resolution"], None]:
    if fn not in PREPARE_HOOKS:
        PREPARE_HOOKS.append(fn)
    return fn


def register_final_hook(fn: Callable[["Resolution"], None]) -> Callable[["Resolution"], None]:
    if fn not in FINAL_HOOKS:
        FINAL_HOOKS.append(fn)
    return fn


# kind -> fn(ctx, target, by) applying a conversion in the commit pass ("werewolf", "vampire"...)
CONVERSIONS: dict[str, Callable[["Resolution", int, int], None]] = {}


def register_conversion(kind: str, fn: Callable[["Resolution", int, int], None]) -> None:
    CONVERSIONS[kind] = fn


class Resolution:
    EARLY = 20
    NORMAL = 50
    LATE = 80        # after deaths (e.g. revives "after the lynch")

    def __init__(self, state: GameState, *, kind: str, slot: str, seed: int, title: str,
                 actions: Sequence[SubmittedAction] | None = None):
        self.state = state
        self.kind = kind                 # "night" | "dusk" | "instant"
        self.slot = slot
        self.rng = random.Random(seed)
        self.report = Report(title)
        if actions is None:
            actions = [a for a in state.actions if a.slot == slot and a.status is ActionStatus.PENDING]
        self.actions: list[SubmittedAction] = sorted(actions, key=self._sort_key)
        self.blocked: dict[int, str] = {}
        self.visits: list[Visit] = []
        self.kills: list[Kill] = []
        self.protections: dict[int, list[Protection]] = {}
        self.messages: dict[int, list[str]] = {}
        self.flags: dict[str, object] = {}
        self.deaths: list[tuple[Player, DeathRecord]] = []
        self.redirects: dict[int, int] = {}                 # action id -> new target
        self.claims: dict[tuple[str, int], list[int]] = {}  # (kind, target) -> claimants
        self._claim_winners: dict[tuple[str, int], int] = {}
        self._commits: list[tuple[int, int, Callable[[], None]]] = []
        self._keep_use: set[int] = set()
        self._resolved: set[int] = set()

    # --- ordering ----------------------------------------------------------
    def _sort_key(self, action: SubmittedAction) -> tuple:
        ability = self.ability_of(action)
        priority = ability.priority if ability is not None else Priority.POST
        return (priority, action.submitted_at, action.id)

    def ability_of(self, action: SubmittedAction):
        actor = self.actor_for(action)
        return actor.ability(action.ability) if actor is not None else None

    def actor_for(self, action: SubmittedAction) -> Actor | None:
        player = self.state.find_player(action.actor)
        if player is None:
            return None
        return next((a for a in player.actors() if a.name == action.source), None)

    # --- intents -----------------------------------------------------------
    def inform(self, player_id: int, text: str) -> None:
        """Private message delivered when this resolution is applied."""
        self.messages.setdefault(player_id, []).append(text)
        self.report.add("Info", f"{self.state.name(player_id)} learns: {text}")

    def kill(self, target: int, cause: str, *, killers: Iterable[int] = (), killer_role: str | None = None,
             attacker_faction: str | None = None, enters_house: bool = True, unstoppable: bool = False,
             public: bool = False, action: SubmittedAction | None = None) -> Kill:
        kill = Kill(
            target=target, cause=cause, killers=list(killers), killer_role=killer_role,
            attacker_faction=attacker_faction, enters_house=enters_house, unstoppable=unstoppable,
            public=public, action_id=action.id if action else None,
        )
        self.kills.append(kill)
        return kill

    def commit(self, fn: Callable[[], None], *, order: int = NORMAL) -> None:
        """Run `fn` in the commit pass. All state changes go through here."""
        self._commits.append((order, len(self._commits), fn))

    def protect(self, target: int, label: str, applies: Callable[[Kill], bool] | None = None, *,
                first: bool = False) -> None:
        """Register a protection for this resolution. `first` puts it before
        protections registered earlier (the Old Hunter's wolfsbane must trigger)."""
        protections = self.protections.setdefault(target, [])
        protection = Protection(label, applies or (lambda kill: True))
        if first:
            protections.insert(0, protection)
        else:
            protections.append(protection)
        self.report.add("Protections", f"{self.state.name(target)}: {label}")

    def block(self, action: SubmittedAction, reason: str) -> None:
        if action.id in self.blocked:
            return
        self.blocked[action.id] = reason
        for visit in self.visits:
            if visit.action_id == action.id:
                visit.blocked = True
                visit.reason = reason
        self.report.add("Blocked", f"{self.state.name(action.actor)}'s {action.source}.{action.ability}: {reason}")

    def is_blocked(self, action: SubmittedAction) -> bool:
        return action.id in self.blocked

    def redirect(self, action: SubmittedAction, target: int, *, reason: str = "") -> None:
        """Change who an action targets (the Puppet curse, the Ancient wolf...)."""
        self.redirects[action.id] = target
        for visit in self.visits:
            if visit.action_id == action.id and visit.target is not None:
                visit.target = target
        self.report.add("Movement", f"{self.state.name(action.actor)}'s {action.source}.{action.ability} is redirected "
                                    f"to {self.state.name(target)}" + (f" ({reason})" if reason else ""))

    def target_of(self, action: SubmittedAction, param: str | None = "target") -> int | None:
        """The action's (possibly redirected) target. Always use this in resolvers."""
        if action.id in self.redirects:
            return self.redirects[action.id]
        if param is None:
            return None
        value = action.params.get(param)
        return value if isinstance(value, int) else None

    def claim(self, kind: str, target: int, claimant: int) -> None:
        """Register a competing claim, e.g. two roles trying to turn the same
        player. Resolve with claim_winner() in the commit pass."""
        self.claims.setdefault((kind, target), []).append(claimant)

    def claim_winner(self, kind: str, target: int) -> int | None:
        key = (kind, target)
        if key not in self._claim_winners:
            claimants = self.claims.get(key, [])
            if not claimants:
                return None
            winner = self.choice(claimants) if len(claimants) > 1 else claimants[0]
            self._claim_winners[key] = winner
            if len(claimants) > 1:
                self.report.add("Conversions", f"Competing {kind} of {self.state.name(target)} by "
                                f"{', '.join(self.state.name(c) for c in claimants)} - {self.state.name(winner)} wins")
        return self._claim_winners[key]

    def turn_prevented(self, target: int, *, attacker_faction: str, killers: Iterable[int] = (),
                       enters_house: bool = True) -> str | None:
        """Turning goes through the same protections as killing, with cause
        "turn" - protections decide whether they also stop turning."""
        probe = Kill(target=target, cause="turn", killers=list(killers), attacker_faction=attacker_faction,
                     enters_house=enters_house)
        reason = self.kill_prevented(probe)
        if reason:
            probe.prevented_by = reason
            player = self.state.find_player(target)
            for actor in (player.actors() if player else []):
                actor.on_kill_prevented(self, probe)
        return reason

    def convert(self, kind: str, target: int, *, by: int) -> None:
        """Apply a registered conversion now (commit pass) and tell every actor,
        so e.g. a visiting Village Slut can be turned along."""
        CONVERSIONS[kind](self, target, by)
        player = self.state.player(target)
        for other, actor in list(self.state.iter_actors()):
            if other is not player:
                actor.on_other_converted(self, player, kind, by)

    def action_by_id(self, action_id: int | None) -> SubmittedAction | None:
        return next((a for a in self.actions if a.id == action_id), None) if action_id is not None else None

    def keep_use(self, action: SubmittedAction) -> None:
        """Don't consume a limited use for this action (e.g. a failed turn)."""
        self._keep_use.add(action.id)

    def note(self, section: str, text: str) -> None:
        self.report.add(section, text)

    def newspaper(self, text: str) -> None:
        self.report.add("Newspaper", text)

    # --- queries -----------------------------------------------------------
    def actions_by(self, player_id: int) -> list[SubmittedAction]:
        return [a for a in self.actions if a.actor == player_id]

    def action_of(self, source: str, ability: str | None = None) -> list[SubmittedAction]:
        return [a for a in self.actions if a.source == source and (ability is None or a.ability == ability)]

    def visits_by(self, player_id: int, *, include_blocked: bool = True) -> list[Visit]:
        return [v for v in self.visits if v.visitor == player_id and (include_blocked or not v.blocked)]

    def visitors_of(self, player_id: int) -> list[Visit]:
        """Visits that actually reached this player's house."""
        return [v for v in self.visits if v.target == player_id and not v.blocked]

    def left_house(self, player_id: int) -> bool:
        return any(v.visitor == player_id for v in self.visits)

    def apparent_faction(self, target: int, observer: str) -> str | None:
        player = self.state.player(target)
        for actor in [*reversed(player.modifiers), *([player.role] if player.role else [])]:
            seen = actor.apparent_faction(self.state, observer)
            if seen is not None:
                return seen
        return player.true_faction()

    def apparent_role(self, target: int, observer: str) -> str | None:
        player = self.state.player(target)
        for actor in [*reversed(player.modifiers), *([player.role] if player.role else [])]:
            seen = actor.apparent_role(self.state, observer)
            if seen is not None:
                return seen
        return player.role_name

    def choice(self, options: Sequence[int]):
        """Deterministic random pick (seeded) from player ids."""
        return self.rng.choice(sorted(options)) if options else None

    def pending_kills_on(self, target: int) -> list[Kill]:
        return [k for k in self.kills if k.target == target and k.prevented_by is None]

    # --- pipeline ----------------------------------------------------------
    def run(self) -> Outcome:
        self._fail_unusable()
        if self.kind == "night":
            for override in self.state.night_overrides:
                if override.kind == "kill":
                    self.kill(override.player, override.cause, killer_role="gm", unstoppable=True,
                              enters_house=False)
                    self.report.add("Notes", f"GM override: kill {self.state.name(override.player)} ({override.cause})")
                elif override.kind == "spare":
                    self.report.add("Notes", f"GM override: spare {self.state.name(override.player)}")
        for hook in PREPARE_HOOKS:
            hook(self)
        self._report_actions()

        self._interaction_pass(lambda p: p < Priority.LOCK)
        self._build_visits()
        self._interaction_pass(lambda p: Priority.LOCK <= p < Priority.INFO)
        self._report_movement()
        for visit in list(self.visits):
            if visit.blocked or visit.target is None:
                continue
            target = self.state.find_player(visit.target)
            if target is not None:
                for actor in target.actors():
                    actor.on_visited(self, visit)

        self._evaluation_pass()
        self._commit_pass()
        return Outcome(
            report=self.report.render(),
            deaths=[(p.user_id, r.cause) for p, r in self.deaths],
            messages=self.messages,
        )

    def _fail_unusable(self) -> None:
        usable: list[SubmittedAction] = []
        for action in self.actions:
            actor = self.actor_for(action)
            player = self.state.find_player(action.actor)
            ability = actor.ability(action.ability) if actor else None
            reason = None
            if player is None or actor is None or ability is None:
                reason = "ability no longer available"
            elif not player.alive and not ability.usable_while_dead:
                reason = "actor is dead"
            if reason:
                self._finish(action, ActionStatus.FAILED, reason)
                self.report.add("Notes", f"{self.state.name(action.actor)}'s {action.source}.{action.ability} failed: {reason}")
            else:
                usable.append(action)
        self.actions = usable

    def _report_actions(self) -> None:
        for action in self.actions:
            details = describe_action(self.state, action)
            self.report.add("Actions", f"{self.state.name(action.actor)}: {details}")

    def _interaction_pass(self, select: Callable[[int], bool]) -> None:
        for action in self.actions:
            ability = self.ability_of(action)
            if ability is None or not select(ability.priority) or self.is_blocked(action):
                continue
            actor = self.actor_for(action)
            if actor is not None:
                actor.interact(self, action)

    def _build_visits(self) -> None:
        for action in self.actions:
            ability = self.ability_of(action)
            if ability is None or not ability.leaves_house or self.is_blocked(action):
                continue
            target = self.target_of(action, ability.visits)
            self.visits.append(Visit(
                visitor=action.actor, target=target, action_id=action.id,
                source=action.source, ability=action.ability,
            ))

    def _report_movement(self) -> None:
        for visit in self.visits:
            where = f"visits {self.state.name(visit.target)}" if visit.target is not None else "leaves the house"
            suffix = f" (stopped: {visit.reason})" if visit.blocked else ""
            label = "werewolf pack" if visit.pack else f"{visit.source}.{visit.ability}"
            self.report.add("Movement", f"{self.state.name(visit.visitor)} {where} [{label}]{suffix}")

    def _evaluation_pass(self) -> None:
        for action in self.actions:
            if self.is_blocked(action):
                continue
            actor = self.actor_for(action)
            if actor is None:
                continue
            if hasattr(actor, f"resolve_{action.ability}"):
                actor.resolve(self, action)
            self._resolved.add(action.id)

    def _commit_pass(self) -> None:
        # status + use bookkeeping happens first so commits can inspect it
        for action in self.actions:
            actor = self.actor_for(action)
            ability = actor.ability(action.ability) if actor else None
            if self.is_blocked(action):
                if ability and ability.consume_on_block and action.id not in self._keep_use:
                    actor.consume(self.state, action.ability)
                self._finish(action, ActionStatus.BLOCKED, self.blocked[action.id])
                if self.state.settings.notify_blocked_actions and self.kind in ("night", "dusk"):
                    # the reason stays in the GM report; players only learn that it didn't work
                    self.inform(action.actor, f"Your {action.ability.replace('_', ' ')} didn't work out "
                                              "- something stopped you.")
            else:
                if actor and action.id not in self._keep_use:
                    actor.consume(self.state, action.ability)
                self._finish(action, ActionStatus.RESOLVED, action.note)

        self._run_commits(lambda order: order < 60)
        self._process_kills()
        self._run_commits(lambda order: order >= 60)
        self._process_kills()

        for player, actor in list(self.state.iter_actors()):
            actor.after_resolution(self)
        self._process_kills()
        for hook in FINAL_HOOKS:
            hook(self)

        for player_id, texts in self.messages.items():
            title = {"night": "Last night", "dusk": "This evening"}.get(self.kind, "")
            self.state.emit(PrivateMessage(player=player_id, text="\n".join(texts), title=title))

    def _run_commits(self, select: Callable[[int], bool]) -> None:
        pending = sorted((c for c in self._commits if select(c[0])), key=lambda c: (c[0], c[1]))
        self._commits = [c for c in self._commits if not select(c[0])]
        for _, _, fn in pending:
            fn()

    def _finish(self, action: SubmittedAction, status: ActionStatus, note: str) -> None:
        action.status = status
        if note:
            action.note = note

    # --- kills & deaths ----------------------------------------------------
    def kill_prevented(self, kill: Kill) -> str | None:
        target = self.state.find_player(kill.target)
        if target is None:
            return "unknown player"
        if any(o.kind == "spare" and o.player == kill.target for o in self.state.night_overrides) and self.kind == "night":
            return "spared by a GM"
        if target.dead:
            return "already dead"
        if kill.unstoppable:
            return None
        for protection in self.protections.get(kill.target, []):
            if protection.applies(kill):
                return protection.label
        if self.kind == "night":
            for status in target.statuses:
                # night protections set during the day (Priest blessing, Enchantress charm): data = {"label", "turn"}
                if status.key == "protection" and (kill.cause != "turn" or status.data.get("turn", False)):
                    return status.data.get("label", "protected")
        for actor in target.actors():
            reason = actor.protects_against(self, kill)
            if reason:
                return reason
        return None

    def _process_kills(self) -> None:
        while True:
            pending = [k for k in self.kills if not k.processed]
            if not pending:
                return
            for kill in pending:
                kill.processed = True
                if kill.prevented_by is None:
                    kill.prevented_by = self.kill_prevented(kill)
                who = self.state.name(kill.target)
                by = f" by {kill.killer_role}" if kill.killer_role else ""
                if kill.prevented_by:
                    self.report.add("Kills", f"{who} attacked ({kill.cause}{by}) - survived: {kill.prevented_by}")
                    target = self.state.find_player(kill.target)
                    if target is not None and kill.prevented_by != "already dead":
                        for actor in target.actors():
                            actor.on_kill_prevented(self, kill)
                    continue
                self.report.add("Kills", f"{who} attacked ({kill.cause}{by}) - dies")
                for _, actor in list(self.state.iter_actors()):
                    actor.on_other_killed(self, kill)
                self.apply_death(kill)

    def apply_death(self, kill: Kill) -> None:
        player = self.state.player(kill.target)
        if player.dead:
            return
        player.life = LifeState.PERMA_DEAD if player.life is LifeState.SKELETON else LifeState.DEAD
        record = DeathRecord(
            day=self.state.day, phase=self.kind, cause=kill.cause,
            killer_ids=list(kill.killers), killer_role=kill.killer_role, public=kill.public,
        )
        player.deaths.append(record)
        if kill.public:
            from Core.access import due_public_status
            player.public_status = due_public_status(player)
        self.deaths.append((player, record))
        self.report.add("Deaths", f"{player.display_name} ({player.role_name}) - {kill.cause}")

        if self.state.mayor == player.user_id:
            self._succeed_mayor(player)

        for actor in player.actors():
            actor.on_death(self, record)
        for other, actor in list(self.state.iter_actors()):
            if other is not player:
                actor.on_other_death(self, player)

    def _succeed_mayor(self, old: Player) -> None:
        successor = self.state.find_player(self.state.mayor_successor)
        self.state.mayor_successor = None
        if successor is not None and successor.alive:
            self.state.mayor = successor.user_id
            self.newspaper(f"Mayor {old.display_name} died; {successor.display_name} is the new Mayor.")
            self.inform(successor.user_id, "The Mayor has died and you are their successor - you are now the Mayor! "
                                           "Pick your own successor with `/mayor successor`.")
        else:
            self.state.mayor = None
            self.newspaper(f"Mayor {old.display_name} died without a living successor - there is no Mayor.")

    def revive(self, player_id: int, *, reason: str) -> None:
        player = self.state.player(player_id)
        if player.life is not LifeState.DEAD:
            self.report.add("Notes", f"Revive of {player.display_name} failed: not revivable ({player.life.value})")
            return
        player.life = LifeState.ALIVE
        if player.deaths:
            player.deaths[-1].revived = True
        self.report.add("Deaths", f"{player.display_name} is revived ({reason})")
        # e.g. a wolf whose role was taken over by the Apprentice comes back without abilities
        for actor in list(player.actors()):
            actor.on_revived(self)
        replacement = player.status("becomes_on_revive")
        if replacement is not None:
            from Core.flow import set_role
            player.remove_status("becomes_on_revive")
            set_role(self.state, player, replacement.data["role"], keep_faction=True,
                     reason=replacement.data.get("reason", "revived"))


def describe_action(state: GameState, action: SubmittedAction) -> str:
    parts = []
    for key, value in action.params.items():
        if isinstance(value, int) and value in state.players:
            parts.append(f"{key}={state.name(value)}")
        else:
            parts.append(f"{key}={value}")
    gm = " (entered by GM)" if action.by_gm else ""
    return f"{action.source}.{action.ability}({', '.join(parts)}){gm}"


def run_resolution(state: GameState, *, kind: str, slot: str, seed: int, title: str,
                   actions: Sequence[SubmittedAction] | None = None) -> Outcome:
    return Resolution(state, kind=kind, slot=slot, seed=seed, title=title, actions=actions).run()

