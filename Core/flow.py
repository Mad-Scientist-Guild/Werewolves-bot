"""Game flow: setup, the daily transitions, decisions and GM operations.

Everything here is a pure function on GameState. The service layer wraps
each call in a locked, persisted mutation and delivers the resulting logs,
effects and reports.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from datetime import datetime

from Core import voting
from Core.access import publish_statuses
from Core.actor import Modifier, Role, modifier_class, role_class
from Core.clock import TransitionKind, next_transition
from Core.effects import Announcement, DecisionPrompt, NewspaperPost, RoleCard, VoteChannelPost
from Core.errors import GameError
from Core.factions import faction_display, winners
from Core.resolution import Outcome, Resolution, register_final_hook
from Core.state import (
    Decision,
    GameState,
    Group,
    GroupKind,
    LifeState,
    Membership,
    NightOverride,
    Phase,
    Player,
    Status,
)


@dataclass
class FlowResult:
    """Reports for the mod channel produced by a flow step."""
    reports: list[tuple[str, str]] = field(default_factory=list)
    preview: Outcome | None = None

    def add(self, title: str, text: str) -> None:
        self.reports.append((title, text))


# --- shared chats ---------------------------------------------------------------

# group key -> (kind, channel name). Roles declare membership with `groups = ("wolves",)`.
GROUP_DEFS: dict[str, tuple[GroupKind, str]] = {}


def register_group(key: str, kind: GroupKind, channel_name: str) -> None:
    GROUP_DEFS[key] = (kind, channel_name)


register_group("wolves", GroupKind.WOLVES, "werewolves")
register_group("undead", GroupKind.UNDEAD, "undead")


def join_group(state: GameState, player: Player, key: str) -> Group:
    kind, name = GROUP_DEFS.get(key, (GroupKind.CUSTOM, key))
    group = state.ensure_group(key, kind, name)
    if group.members.get(player.user_id) is not Membership.ACTIVE:
        group.add(player.user_id)
        state.log("GROUP", f"{player.display_name} joins {group.name}.", actor=player.user_id)
    return group


def join_actor_groups(state: GameState, player: Player) -> None:
    for actor in player.actors():
        for key in actor.groups:
            join_group(state, player, key)


# --- seeds ----------------------------------------------------------------------

def seed(state: GameState, key: str) -> int:
    """A persisted random seed, so previews and final resolutions match."""
    if key not in state.seeds:
        state.seeds[key] = random.SystemRandom().randrange(1, 2**31)
    return state.seeds[key]


# --- players, roles, modifiers --------------------------------------------------

def add_player(state: GameState, user_id: int, display_name: str) -> Player:
    if state.phase is not Phase.SETUP:
        raise GameError("The game has already started - new players can't join. Contact a GM.")
    if user_id in state.players:
        raise GameError(f"{display_name} has already joined.")
    player = Player(user_id=user_id, display_name=display_name)
    state.players[user_id] = player
    if user_id in state.backups:
        state.backups.remove(user_id)
    state.log("PLAYER", f"{display_name} joined the game.", actor=user_id)
    return player


def remove_player(state: GameState, user_id: int) -> None:
    if state.phase is not Phase.SETUP:
        raise GameError("Players can't be removed once the game has started - use the reaper instead.")
    player = state.player(user_id)
    del state.players[user_id]
    for group in state.groups.values():
        group.members.pop(user_id, None)
    state.log("PLAYER", f"{player.display_name} left the game.", actor=user_id)


def set_role(state: GameState, player: Player, role_name: str, *, keep_faction: bool = False,
             notify: bool = True, note: str = "", reason: str = "") -> Role:
    cls = role_class(role_name)
    old = player.role_name
    if state.phase is Phase.SETUP:
        private = state.groups.get(player.private_group) if player.private_group else None
        if private is not None and private.channel_id is not None:
            raise GameError(f"{player.display_name}'s private channel already exists and is named after their "
                            "role - change roles before creating channels, or use `/gm set_role` once the game runs.")
        for key in (player.role.groups if player.role else ()):
            if key in state.groups:
                state.groups[key].members.pop(player.user_id, None)
    player.role = cls(owner=player.user_id)
    if not keep_faction:
        player.faction = cls.faction
    if state.phase is Phase.SETUP:
        player.original_role = cls.name
    else:
        join_actor_groups(state, player)
        if notify:
            state.emit(RoleCard(player=player.user_id, role=cls.name, changed=old is not None, note=note))
    state.log("ROLE", f"{player.display_name}: {old or 'no role'} → {cls.name}"
              + (f" ({reason})" if reason else ""), actor=player.user_id)
    return player.role


def adopt_role(state: GameState, player: Player, role: Role, *, reason: str, note: str = "") -> Role:
    """Give a player a copy of an existing role instance - its state and used
    charges carry over (the Apprentice wolf taking over a fallen wolf)."""
    new = copy.deepcopy(role)
    new.owner = player.user_id
    old = player.role_name
    player.role = new
    join_actor_groups(state, player)
    state.emit(RoleCard(player=player.user_id, role=new.name, changed=True, note=note))
    state.log("ROLE", f"{player.display_name}: {old} → {new.name} ({reason}, charges carried over)", actor=player.user_id)
    return new


def add_modifier(state: GameState, player: Player, name: str, *, reason: str = "", **fields) -> Modifier:
    cls = modifier_class(name)
    existing = player.modifier(cls.name)
    if existing is not None:
        return existing
    modifier = cls(owner=player.user_id, **fields)
    player.modifiers.append(modifier)
    if state.phase is not Phase.SETUP:
        join_actor_groups(state, player)
    state.log("MODIFIER", f"{player.display_name} gains {cls.name}" + (f" ({reason})" if reason else ""),
              actor=player.user_id)
    return modifier


def remove_modifier(state: GameState, player: Player, name: str, *, reason: str = "") -> None:
    before = len(player.modifiers)
    player.modifiers = [m for m in player.modifiers if m.name != name]
    if len(player.modifiers) != before:
        state.log("MODIFIER", f"{player.display_name} loses {name}" + (f" ({reason})" if reason else ""),
                  actor=player.user_id)


# --- assignment & families ------------------------------------------------------

def plan_assignment(state: GameState, rng_seed: int | None = None) -> dict[int, str]:
    pool = [name for name, count in sorted(state.role_pool.items()) for _ in range(count)]
    players = sorted(state.players)
    if len(pool) != len(players):
        raise GameError(f"The role pool has {len(pool)} roles but there are {len(players)} players.")
    rng = random.Random(rng_seed)
    rng.shuffle(pool)
    return dict(zip(players, pool))


def apply_assignment(state: GameState, mapping: dict[int, str]) -> None:
    for user_id, role_name in mapping.items():
        set_role(state, state.player(user_id), role_name, reason="assignment")


def split_families(state: GameState, *, size: int, rng_seed: int | None = None) -> list[Group]:
    if state.phase is not Phase.SETUP:
        raise GameError("Families can only be formed before the game starts.")
    players = sorted(state.players)
    if not players:
        raise GameError("No players have joined yet.")
    rng = random.Random(rng_seed)
    rng.shuffle(players)
    count = max(1, round(len(players) / max(1, size)))
    for group in state.groups_of_kind(GroupKind.FAMILY):
        del state.groups[group.key]
    families = [
        state.ensure_group(f"family:{i + 1}", GroupKind.FAMILY, f"family-{i + 1}") for i in range(count)
    ]
    for index, user_id in enumerate(players):
        family = families[index % count]
        family.add(user_id)
        state.players[user_id].family = family.key
    state.log("SETUP", "Families formed: " + "; ".join(
        f"{f.name}: {', '.join(state.name(u) for u in f.active_members())}" for f in families))
    return families


def set_family(state: GameState, player: Player, family_key: str) -> None:
    family = state.group(family_key)
    if family.kind is not GroupKind.FAMILY:
        raise GameError("That isn't a family.")
    if player.family and player.family in state.groups:
        old = state.groups[player.family]
        if state.phase is Phase.SETUP:
            old.members.pop(player.user_id, None)
        else:
            old.leave(player.user_id)
    family.add(player.user_id)
    player.family = family.key
    state.log("FAMILY", f"{player.display_name} is now in {family.name}.", actor=player.user_id)


def family_members(state: GameState, family_key: str | None) -> list[Player]:
    if family_key is None or family_key not in state.groups:
        return []
    return [state.players[u] for u in state.groups[family_key].active_members() if u in state.players]


def ensure_base_groups(state: GameState) -> None:
    """Village, dead chat and one private group per player."""
    state.ensure_group("village", GroupKind.VILLAGE, "village-chat")
    state.ensure_group("dead", GroupKind.DEAD, "dead-chat")
    taken: dict[str, int] = {}
    for player in sorted(state.players.values(), key=lambda p: p.user_id):
        if player.private_group is not None:
            continue
        base = (player.role_name or "player").replace("_", "-")
        taken[base] = taken.get(base, 0) + 1
        name = base if taken[base] == 1 else f"{base}-{taken[base]}"
        group = state.ensure_group(f"private:{player.user_id}", GroupKind.PRIVATE, name,
                                   topic=f"Private channel of {player.display_name}")
        group.add(player.user_id)
        player.private_group = group.key
    for player in state.players.values():
        join_actor_groups(state, player)


# --- start / end ----------------------------------------------------------------

def start_game(state: GameState, now: datetime) -> FlowResult:
    if state.phase is not Phase.SETUP:
        raise GameError("The game has already started.")
    if not state.players:
        raise GameError("No players have joined yet.")
    missing = [p.display_name for p in state.players.values() if p.role is None]
    if missing:
        raise GameError(f"These players have no role yet: {', '.join(missing)}")

    ensure_base_groups(state)
    state.phase = Phase.DAY
    state.day = 1
    state.started_at = now.isoformat()
    for player in state.players.values():
        if player.original_role is None:
            player.original_role = player.role_name
        state.emit(RoleCard(player=player.user_id, role=player.role_name))
    for _, actor in list(state.iter_actors()):
        hook = getattr(actor, "on_game_start", None)
        if hook is not None:
            hook(state)

    voting.open_ballot(state, voting.MAYOR, allow_abstain=False)
    state.emit(Announcement(
        title="THE GAME HAS STARTED",
        text="Welcome to XP Werewolves! Today is the first day - get to know each other.\n"
             "Vote for a **Mayor** with `/mayor vote`. The first night begins at "
             f"{state.settings.schedule.dusk}.",
    ))
    state.next_transition = next_transition(state, now)
    state.log("GAME", f"Game started with {len(state.players)} players.", alert=True)
    return FlowResult()


def end_game(state: GameState, winner: str | None, now: datetime) -> None:
    if not state.active:
        raise GameError("The game isn't running.")
    state.phase = Phase.ENDED
    state.winner = winner
    state.ended_at = now.isoformat()
    state.next_transition = None
    text = f"The game is over! **{faction_display(winner)}** win." if winner else "The game is over!"
    state.emit(Announcement(title="GAME OVER", text=text, color="gold"))
    state.log("GAME", f"Game ended. Winner: {winner or 'none declared'}", alert=True)


# --- transitions ----------------------------------------------------------------

def run_transition(state: GameState, kind: TransitionKind, scheduled: datetime) -> FlowResult:
    result = FlowResult()
    handler = {
        TransitionKind.MORNING: _morning,
        TransitionKind.NEWSPAPER: _newspaper,
        TransitionKind.DUSK: _dusk,
        TransitionKind.SECOND_LYNCH_END: _second_lynch_end,
        TransitionKind.NIGHT_LOCK: _night_lock,
    }[kind]
    state.log("PHASE", f"Transition: {kind.value} (day {state.day})")
    handler(state, result)
    state.next_transition = next_transition(state, scheduled)
    return result


def _expire_statuses(state: GameState, slot: str) -> None:
    for player in state.players.values():
        expired = [s for s in player.statuses if s.expires == slot]
        if expired:
            player.statuses = [s for s in player.statuses if s.expires != slot]
            state.log("STATUS", f"{player.display_name}: expired {', '.join(s.key for s in expired)}",
                      actor=player.user_id)


def _morning(state: GameState, result: FlowResult) -> None:
    night = state.day
    outcome = resolve_night(state)
    result.add(f"Night {night} — final", outcome.report)
    voting.archive_ballot(state, voting.WOLVES)
    state.night_overrides.clear()

    state.day += 1
    state.phase = Phase.DAY
    _expire_statuses(state, f"morning:{state.day}")
    state.emit(Announcement(title=f"DAY {state.day}", text="The sun rises over XP. A new day begins."))


def _newspaper(state: GameState, result: FlowResult) -> None:
    changed = publish_statuses(state)
    if changed:
        state.log("PUBLIC", "Public statuses updated: " + ", ".join(
            f"{p.display_name} → {p.public_status.value}" for p in changed))
    url = state.settings.newspaper_url
    if url:
        state.emit(NewspaperPost(url=url))
        state.data.setdefault("newspapers", {})[str(state.day)] = url
        state.settings.newspaper_url = None
    else:
        state.log("NEWSPAPER", f"No newspaper image was set for day {state.day}.", alert=True)
    state.data["newspaper_day"] = state.day
    if state.day >= 2:
        voting.open_ballot(state, voting.LYNCH)
        state.emit(Announcement(title="VOTING IS OPEN",
                                text="You can now vote to lynch someone with `/lynch vote` "
                                     f"(until {state.settings.schedule.dusk})."))


def _dusk(state: GameState, result: FlowResult) -> None:
    day = state.day
    _expire_statuses(state, f"dusk:{day}")

    mayor_ballot = voting.close_ballot(state, voting.MAYOR)
    if mayor_ballot is not None:
        _finish_mayor_election(state, mayor_ballot)

    lynch_ballot = voting.close_ballot(state, voting.LYNCH)
    tally = voting.tally_lynch(state, lynch_ballot) if lynch_ballot else None

    ctx = Resolution(state, kind="dusk", slot=state.slot("dusk"), seed=seed(state, f"dusk:{day}"),
                     title=f"Dusk of day {day}")
    ctx.flags["lynch_tally"] = tally
    target = _lynch_target(state, tally, lynch_ballot, ctx) if tally else None
    ctx.flags["lynch_target"] = target

    def do_lynch() -> None:
        chosen = ctx.flags.get("lynch_target")
        if ctx.flags.get("lynch_stopped") or chosen is None:
            return
        ctx.flags["lynch_kill"] = ctx.kill(
            chosen, "lynch", killers=voting.voters_for(lynch_ballot, chosen), killer_role="village",
            enters_house=False, public=True)

    ctx.commit(do_lynch, order=Resolution.EARLY)
    outcome = ctx.run()
    result.add(f"Dusk of day {day}", outcome.report)

    if ctx.flags.get("needs_mayor_choice") is not None and not ctx.flags.get("lynch_stopped"):
        decision = create_decision(
            state, "lynch_tiebreak", int(ctx.flags["needs_mayor_choice"]), tally.tied,
            "The lynch vote is tied. As Mayor, you decide who is lynched:",
            day=day, voters={str(t): voting.voters_for(lynch_ballot, t) for t in tally.tied},
        )
        ctx.flags["lynch_decision"] = decision.id

    if lynch_ballot is not None:
        state.emit(VoteChannelPost(title=f"Lynch votes — day {day}", text=voting.published_votes(state, lynch_ballot)))
        lynch_ballot.result = {"outcome": tally.outcome, "target": target, "tied": tally.tied,
                               "stopped": bool(ctx.flags.get("lynch_stopped"))}
        state.emit(Announcement(title="VOTING HAS CONCLUDED", text=_lynch_announcement(state, ctx, tally)))
        voting.archive_ballot(state, voting.LYNCH)

    if ctx.flags.get("second_lynch_by") is not None:
        _open_second_lynch(state, int(ctx.flags["second_lynch_by"]))

    state.phase = Phase.NIGHT
    voting.open_ballot(state, voting.WOLVES)
    seed(state, f"night:{day}")


def _lynch_target(state: GameState, tally: voting.Tally, ballot, ctx: Resolution) -> int | None:
    if tally.outcome == "lynch":
        return tally.target
    if tally.outcome != "tie":
        return None
    mayor = state.find_player(state.mayor)
    if mayor is None or not mayor.alive:
        ctx.note("Notes", "Lynch tie and there is no Mayor - nobody is lynched.")
        return None
    mayor_vote = ballot.votes.get(mayor.user_id)
    if mayor_vote in tally.tied:
        ctx.note("Notes", f"Lynch tie broken by the Mayor's vote: {state.name(mayor_vote)}")
        ctx.flags["mayor_tiebreak"] = True
        return mayor_vote
    ctx.flags["needs_mayor_choice"] = mayor.user_id
    ctx.note("Notes", "Lynch tie - the Mayor didn't vote for one of the tied players and will choose.")
    return None


def _lynch_announcement(state: GameState, ctx: Resolution, tally: voting.Tally) -> str:
    if ctx.flags.get("lynch_stopped"):
        return "The vote has been stopped - nobody will be lynched today."
    kill = ctx.flags.get("lynch_kill")
    if kill is not None:
        victim = state.player(kill.target)
        if kill.prevented_by:
            return f"The village chose to lynch {victim.display_name}... but they survived!"
        prefix = "There was a tie, and the Mayor's vote decided: " if ctx.flags.get("mayor_tiebreak") else ""
        faction = faction_display(victim.true_faction())
        return f"{prefix}The village lynched **{victim.display_name}**. They were part of the **{faction}**."
    if ctx.flags.get("lynch_decision") is not None:
        names = ", ".join(state.name(t) for t in tally.tied)
        return f"There is a **tie** between {names}. The Mayor will decide who is lynched."
    if tally.outcome == "abstained":
        return "More than half of the village didn't vote or abstained - nobody is lynched."
    if tally.outcome == "tie":
        return "There is a **tie** and no Mayor to break it - nobody is lynched."
    return "Nobody voted - nobody is lynched."


def _finish_mayor_election(state: GameState, ballot) -> None:
    tally = voting.tally_mayor(state, ballot)
    state.emit(VoteChannelPost(title="Mayor votes", text=voting.published_votes(state, ballot)))
    if tally.outcome == "elected":
        state.mayor = tally.target
        state.emit(Announcement(title="A NEW MAYOR", text=f"**{state.name(tally.target)}** is the new Mayor!"))
        state.log("MAYOR", f"{state.name(tally.target)} was elected Mayor ({voting.describe_counts(state, tally)}).",
                  actor=tally.target)
    elif tally.outcome == "tie":
        state.emit(Announcement(title="MAYOR ELECTION", text="The mayor election is tied - the GMs will hold a re-vote."))
        state.log("MAYOR", f"Mayor election tied: {voting.describe_counts(state, tally)}", alert=True)
    else:
        state.log("MAYOR", "Nobody voted in the mayor election.", alert=True)
    voting.archive_ballot(state, voting.MAYOR)


def _open_second_lynch(state: GameState, counselor: int) -> None:
    voting.open_ballot(state, voting.LYNCH2, allow_abstain=False)
    state.data["second_lynch_by"] = counselor
    state.lockdown = True
    state.emit(Announcement(
        title="A SECOND LYNCH",
        text="The Ruthless Counselor demands a second lynch - **right now**. All discussion channels are locked "
             f"until the result is posted. Vote with `/lynch vote` before {state.settings.schedule.second_lynch_end}. "
             "Abstaining is not possible.", color="red"))
    state.log("LYNCH", f"Second lynch called by {state.name(counselor)}; lockdown on.", actor=counselor, alert=True)


def _second_lynch_end(state: GameState, result: FlowResult) -> None:
    ballot = voting.close_ballot(state, voting.LYNCH2)
    if ballot is None:
        return
    tally = voting.tally_second_lynch(state, ballot)
    counselor = state.data.get("second_lynch_by")
    state.emit(VoteChannelPost(title=f"Second lynch votes — day {state.day}", text=voting.published_votes(state, ballot)))
    ballot.result = {"outcome": tally.outcome, "target": tally.target, "tied": tally.tied}
    if tally.outcome == "lynch":
        result.add("Second lynch", execute_lynch(state, tally.target, second=True, voters=voting.voters_for(ballot, tally.target)))
    else:
        options = tally.tied or [p.user_id for p in state.alive_players()]
        chooser = state.find_player(counselor)
        create_decision(
            state, "lynch2_tiebreak", chooser.user_id if chooser and chooser.alive else None, options,
            "The second lynch is tied - as Ruthless Counselor you decide who dies:" if tally.tied
            else "Nobody voted in the second lynch - as Ruthless Counselor you decide who dies:",
            day=state.day, voters={str(t): voting.voters_for(ballot, t) for t in tally.tied},
        )
        state.emit(Announcement(title="SECOND LYNCH", text="The second lynch is undecided - the Ruthless Counselor will choose."))
    voting.archive_ballot(state, voting.LYNCH2)


def execute_lynch(state: GameState, target: int, *, second: bool, voters: list[int] | None = None,
                  by_decision: bool = False) -> str:
    """Lynch outside the dusk resolution (tiebreak decisions, second lynch)."""
    ctx = Resolution(state, kind="lynch", slot=f"lynch:{state.day}", seed=seed(state, f"lynch:{state.day}:{target}"),
                     title=f"{'Second lynch' if second else 'Lynch'} of {state.name(target)}", actions=[])
    holder: dict[str, object] = {}

    def do() -> None:
        holder["kill"] = ctx.kill(target, "lynch", killers=voters or [], killer_role="village",
                                  enters_house=False, public=True)

    ctx.commit(do, order=Resolution.EARLY)
    outcome = ctx.run()
    victim = state.player(target)
    kill = holder["kill"]
    how = "chosen by the Mayor" if by_decision and not second else "chosen by the Ruthless Counselor" if by_decision else "lynched"
    if kill.prevented_by:
        text = f"**{victim.display_name}** was {how}... but they survived!"
    else:
        text = f"**{victim.display_name}** was {how}. They were part of the **{faction_display(victim.true_faction())}**."
    state.emit(Announcement(title="SECOND LYNCH RESULT" if second else "LYNCH RESULT", text=text))
    if second:
        state.lockdown = False
        state.log("LYNCH", "Lockdown lifted.")
    return outcome.report


def _night_lock(state: GameState, result: FlowResult) -> None:
    state.phase = Phase.SLEEP
    voting.close_ballot(state, voting.WOLVES)
    seed(state, f"night:{state.day}")
    result.preview = preview_night(state)
    result.add(f"Night {state.day} — preview", result.preview.report)


def preview_night(state: GameState) -> Outcome:
    """Resolve tonight on a copy, for the GM preview. Nothing is changed."""
    seed(state, f"night:{state.day}")
    shadow = copy.deepcopy(state)
    shadow.pending_logs = []
    shadow.pending_effects = []
    return resolve_night(shadow)


def resolve_night(state: GameState) -> Outcome:
    night = state.day
    ctx = Resolution(state, kind="night", slot=state.slot("night", night), seed=seed(state, f"night:{night}"),
                     title=f"Night {night}")
    return ctx.run()


# --- decisions ------------------------------------------------------------------

def create_decision(state: GameState, kind: str, chooser: int | None, options: list[int], prompt: str,
                    **data) -> Decision:
    decision = Decision(id=state.next_id("decision"), kind=kind, chooser=chooser, options=list(options),
                        prompt=prompt, data=data)
    state.decisions.append(decision)
    state.emit(DecisionPrompt(decision_id=decision.id))
    who = state.name(chooser) if chooser is not None else "the GMs"
    state.log("DECISION", f"Waiting for {who}: {prompt} Options: {', '.join(state.name(o) for o in options)}",
              actor=chooser, alert=True, decision_id=decision.id)
    return decision


def open_decisions(state: GameState) -> list[Decision]:
    return [d for d in state.decisions if not d.resolved]


def resolve_decision(state: GameState, decision_id: int, choice: int, *, by: int, by_gm: bool = False) -> FlowResult:
    decision = next((d for d in state.decisions if d.id == decision_id), None)
    if decision is None or decision.resolved:
        raise GameError("That decision is no longer open.")
    if not by_gm and decision.chooser != by:
        raise GameError("This decision isn't yours to make.")
    if choice not in decision.options:
        raise GameError("That isn't one of the options.")
    decision.resolved = True
    decision.choice = choice
    state.log("DECISION", f"{state.name(by)}{' (GM)' if by_gm else ''} chose {state.name(choice)} for: {decision.prompt}",
              actor=by, targets=[choice], decision_id=decision.id)

    result = FlowResult()
    voters = decision.data.get("voters", {}).get(str(choice), [])
    if decision.kind == "lynch_tiebreak":
        result.add("Lynch tiebreak", execute_lynch(state, choice, second=False, voters=voters, by_decision=True))
    elif decision.kind == "lynch2_tiebreak":
        result.add("Second lynch", execute_lynch(state, choice, second=True, voters=voters, by_decision=True))
    else:
        handler = DECISION_HANDLERS.get(decision.kind)
        if handler is None:
            raise GameError(f"No handler for decision kind '{decision.kind}'")
        handler(state, decision, result)
    return result


# kind -> handler(state, decision, result); roles register their own decision kinds here
DECISION_HANDLERS: dict[str, object] = {}


# --- GM operations --------------------------------------------------------------

def gm_kill(state: GameState, target: int, *, cause: str = "gm", public: bool = False, by: int | None = None) -> str:
    player = state.player(target)
    if not (player.alive or player.life is LifeState.SKELETON):
        raise GameError(f"{player.display_name} is already dead.")
    ctx = Resolution(state, kind="instant", slot="gm", seed=state.next_id("gm_seed"), title=f"GM kill: {player.display_name}",
                     actions=[])
    ctx.commit(lambda: ctx.kill(target, cause, killer_role="gm", unstoppable=True, public=public, enters_house=False),
               order=Resolution.EARLY)
    outcome = ctx.run()
    state.log("GM", f"GM killed {player.display_name} ({cause}{', public' if public else ''})", actor=by,
              targets=[target], alert=True)
    return outcome.report


def gm_revive(state: GameState, target: int, *, by: int | None = None) -> str:
    player = state.player(target)
    if player.alive:
        raise GameError(f"{player.display_name} is alive.")
    if player.life is not LifeState.DEAD:
        raise GameError(f"{player.display_name} can't be revived ({player.life.value}).")
    ctx = Resolution(state, kind="instant", slot="gm", seed=state.next_id("gm_seed"), title=f"GM revive: {player.display_name}",
                     actions=[])
    ctx.commit(lambda: ctx.revive(target, reason="GM"))
    outcome = ctx.run()
    state.log("GM", f"GM revived {player.display_name}", actor=by, targets=[target], alert=True)
    return outcome.report


def add_night_override(state: GameState, kind: str, target: int, *, cause: str = "gm", by: int | None = None) -> None:
    if state.phase not in (Phase.NIGHT, Phase.SLEEP):
        raise GameError("Night overrides can only be added during the night.")
    if kind not in ("kill", "spare"):
        raise GameError("Override kind must be 'kill' or 'spare'.")
    state.player(target)
    state.night_overrides = [o for o in state.night_overrides if o.player != target]
    state.night_overrides.append(NightOverride(kind=kind, player=target, cause=cause, by=by))
    state.log("GM", f"Night override: {kind} {state.name(target)} ({cause})", actor=by, targets=[target], alert=True)


def remove_night_override(state: GameState, target: int, *, by: int | None = None) -> None:
    before = len(state.night_overrides)
    state.night_overrides = [o for o in state.night_overrides if o.player != target]
    if len(state.night_overrides) == before:
        raise GameError("There is no override for that player.")
    state.log("GM", f"Night override for {state.name(target)} removed", actor=by, targets=[target])


def replace_player(state: GameState, old_id: int, new_id: int, new_name: str, *, by: int | None = None) -> Player:
    """The Reaper puts another soul into a body: the new member takes over
    the player's role, state, groups and channels."""
    if new_id in state.players:
        raise GameError("That person is already playing.")
    player = state.player(old_id)
    old_name = player.display_name
    del state.players[old_id]
    player.previous_user_ids.append(old_id)
    player.user_id = new_id
    player.display_name = new_name
    for actor in player.actors():
        actor.owner = new_id
    state.players[new_id] = player
    for group in state.groups.values():
        if old_id in group.members:
            group.members[new_id] = group.members.pop(old_id)
    for action in state.actions:
        if action.actor == old_id:
            action.actor = new_id
    for ballot in state.ballots.values():
        if old_id in ballot.votes:
            ballot.votes[new_id] = ballot.votes.pop(old_id)
    if state.mayor == old_id:
        state.mayor = new_id
    if state.mayor_successor == old_id:
        state.mayor_successor = new_id
    if new_id in state.backups:
        state.backups.remove(new_id)
    player.inactivity_level = 0
    player.last_active_at = None
    state.log("REAPER", f"{new_name} replaces {old_name} (role {player.role_name}).", actor=by,
              targets=[new_id], alert=True, old_user=old_id)
    return player


def add_status(state: GameState, player: Player, key: str, *, source: int | None = None,
               expires: str | None = None, **data) -> Status:
    status = Status(key=key, source=source, expires=expires, data=data)
    player.add_status(status)
    return status


@register_final_hook
def _win_check(ctx: Resolution) -> None:
    if not ctx.state.active:
        return
    found = winners(ctx.state)
    if found:
        text = ("Win condition met for: " + ", ".join(faction_display(f) for f in found)
                + " — end the game with `/gm end_game` if this is right.")
        ctx.note("Win check", text)
        ctx.state.log("WIN", text, alert=True)
