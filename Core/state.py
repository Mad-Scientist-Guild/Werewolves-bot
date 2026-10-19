"""Discord-free game state.

Players and channels are referenced by ID only, so the whole state can be
serialised to the database and deep-copied for night previews. Discord
objects are looked up from these IDs in the Services layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Iterator

from Core.errors import GameError, NotAPlayer
from Core.serialize import transient

if TYPE_CHECKING:
    from Core.actor import Actor, Modifier, Role
    from Core.effects import Effect


class Phase(str, Enum):
    SETUP = "setup"
    DAY = "day"        # 08:00 - 19:00
    NIGHT = "night"    # 19:00 - 00:00
    SLEEP = "sleep"    # 00:00 - 08:00, night actions locked in
    ENDED = "ended"


ACTIVE_PHASES = (Phase.DAY, Phase.NIGHT, Phase.SLEEP)


class LifeState(str, Enum):
    ALIVE = "alive"
    DEAD = "dead"
    SKELETON = "skeleton"
    PERMA_DEAD = "perma_dead"  # a skeleton killed again - cannot be raised or revived


class GroupKind(str, Enum):
    PRIVATE = "private"          # a player's private channel with the GMs
    VILLAGE = "village"          # everyone; membership derived from the player list
    DEAD = "dead"                # the dead chat; membership derived from life states
    FAMILY = "family"
    WOLVES = "wolves"
    UNDEAD = "undead"
    SKELETONS = "skeletons"
    LOVERS = "lovers"
    BROTHERS = "brothers"
    COVEN = "coven"
    SPIRIT_LINE = "spirit_line"  # Spiritualist <-> Vengeful Spirit
    CUSTOM = "custom"


class Membership(str, Enum):
    ACTIVE = "active"
    FORMER = "former"    # left the group: keeps read-only access (nothing is made inaccessible)
    REVOKED = "revoked"  # explicit revocation - only used by the death rules


class PublicStatus(str, Enum):
    """The public Discord roles. Only these three game states have one."""
    NONE = "none"
    DEAD = "dead"
    VENGEFUL_SPIRIT = "vengeful_spirit"
    SKELETON = "skeleton"


class ActionStatus(str, Enum):
    PENDING = "pending"
    REPLACED = "replaced"    # the player submitted a new choice for the same ability
    CANCELLED = "cancelled"
    RESOLVED = "resolved"
    BLOCKED = "blocked"
    FAILED = "failed"


# --- records -----------------------------------------------------------------

@dataclass
class DeathRecord:
    day: int
    phase: str
    cause: str
    killer_ids: list[int] = field(default_factory=list)
    killer_role: str | None = None   # role name, or a group label like "werewolves"
    public: bool = False             # lynch deaths are public immediately
    revived: bool = False


@dataclass
class Status:
    """A temporary or permanent marker on a player (blessed, cursed, enchanted...)."""
    key: str
    source: int | None = None
    expires: str | None = None   # slot id, e.g. "morning:4"; None = until removed
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(eq=False)
class Player:
    user_id: int
    display_name: str
    life: LifeState = LifeState.ALIVE
    role: Role | None = None
    original_role: str | None = None   # role at game start (coven kill list, reports)
    faction: str | None = None         # base faction; modifiers may override it
    modifiers: list[Modifier] = field(default_factory=list)
    family: str | None = None          # group key
    private_group: str | None = None   # group key of their private channel
    statuses: list[Status] = field(default_factory=list)
    deaths: list[DeathRecord] = field(default_factory=list)
    public_status: PublicStatus = PublicStatus.NONE
    last_active_at: str | None = None
    inactivity_level: int = 0          # 0 = fine, 1 = warned, 2 = flagged
    previous_user_ids: list[int] = field(default_factory=list)  # reaper replacements

    # --- life ------------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self.life is LifeState.ALIVE

    @property
    def dead(self) -> bool:
        return self.life in (LifeState.DEAD, LifeState.PERMA_DEAD)

    @property
    def death(self) -> DeathRecord | None:
        return self.deaths[-1] if self.deaths and not self.deaths[-1].revived else None

    # --- actors ----------------------------------------------------------
    def actors(self) -> list[Actor]:
        out: list[Actor] = []
        if self.role is not None:
            out.append(self.role)
        out.extend(self.modifiers)
        return out

    def modifier(self, name: str) -> Modifier | None:
        return next((m for m in self.modifiers if m.name == name), None)

    def has_modifier(self, name: str) -> bool:
        return self.modifier(name) is not None

    @property
    def role_name(self) -> str | None:
        return self.role.name if self.role is not None else None

    def true_faction(self) -> str | None:
        """Most recently added modifier with an override wins."""
        for modifier in reversed(self.modifiers):
            override = modifier.faction_override(self)
            if override is not None:
                return override
        return self.faction

    def can_vote_wolf_kill(self) -> bool:
        return any(a.can_vote_wolf_kill for a in self.actors())

    # --- statuses --------------------------------------------------------
    def status(self, key: str) -> Status | None:
        return next((s for s in self.statuses if s.key == key), None)

    def has_status(self, key: str) -> bool:
        return self.status(key) is not None

    def add_status(self, status: Status) -> None:
        self.statuses = [s for s in self.statuses if not (s.key == status.key and s.source == status.source)]
        self.statuses.append(status)

    def remove_status(self, key: str) -> None:
        self.statuses = [s for s in self.statuses if s.key != key]

    def __repr__(self) -> str:
        return f"<Player {self.display_name} ({self.user_id}) {self.role_name} {self.life.value}>"


@dataclass
class Group:
    key: str
    kind: GroupKind
    name: str                      # channel name, fixed at creation (channels are never renamed)
    channel_id: int | None = None
    members: dict[int, Membership] = field(default_factory=dict)
    archived: bool = False         # superseded: every member keeps read-only access
    created_day: int = 0
    topic: str = ""

    def active_members(self) -> list[int]:
        return [uid for uid, m in self.members.items() if m is Membership.ACTIVE]

    def add(self, user_id: int) -> None:
        self.members[user_id] = Membership.ACTIVE

    def leave(self, user_id: int) -> None:
        if user_id in self.members:
            self.members[user_id] = Membership.FORMER


@dataclass
class SubmittedAction:
    id: int
    actor: int
    source: str          # name of the role/modifier that provides the ability
    ability: str
    slot: str            # "night:3", "dusk:3" or "instant"
    targets: list[int] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    submitted_at: str = ""
    submitted_phase: str = ""
    status: ActionStatus = ActionStatus.PENDING
    note: str = ""
    by_gm: bool = False

    @property
    def target(self) -> int | None:
        return self.targets[0] if self.targets else None


@dataclass
class VoteRecord:
    voter: int
    target: int | None
    at: str
    shown_as: int | None = None


@dataclass
class Ballot:
    kind: str                       # "lynch", "lynch2", "mayor", "wolves"
    day: int
    is_open: bool = True
    allow_abstain: bool = True
    votes: dict[int, int | None] = field(default_factory=dict)   # voter -> target (None = abstain)
    shown_as: dict[int, int] = field(default_factory=dict)       # voter -> name shown when published
    history: list[VoteRecord] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    """A choice a player (or the GMs) must make before something can resolve,
    e.g. the Mayor breaking a lynch tie. Persisted so it survives restarts."""
    id: int
    kind: str
    chooser: int | None          # player id; None = the GMs
    options: list[int]
    prompt: str
    created_at: str = ""
    resolved: bool = False
    choice: int | None = None
    message_id: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelayMessage:
    speaker: int
    at: str                      # ISO datetime
    text: str


@dataclass
class Relay:
    """Listening in on a group chat (Peeking Girl, Diviner's Scrying): the
    first `capture_minutes` of conversation after the first message inside
    the window are sent to the listener as a transcript."""
    id: int
    listener: int
    source_group: str
    window_start: str
    window_end: str
    purpose: str                 # "peeking_girl", "diviner"...
    night: int                   # the night this counts as leaving the house for
    capture_minutes: int = 15
    capture_until: str | None = None
    messages: list[RelayMessage] = field(default_factory=list)
    done: bool = False


@dataclass
class Seance:
    """A yes/no question with anonymous answers: the Spiritualist asking the
    dead (kind "seance"), or the Enchantress' Charm of the Open Book (kind
    "open_book", one voter)."""
    id: int
    asker: int
    question: str
    asked_at: str
    deadline: str
    voters: list[int] = field(default_factory=list)          # who may answer
    answers: dict[int, bool] = field(default_factory=dict)
    message_id: int | None = None
    done: bool = False
    kind: str = "seance"
    where: str = "dead"                                       # group whose channel gets the question


@dataclass
class TelepathyMessage:
    id: int
    sender: int
    target: int
    text: str
    sent_at: str
    reply: str | None = None
    replied_at: str | None = None


@dataclass
class Transition:
    kind: str                    # Core.clock.TransitionKind value
    at: str                      # ISO datetime (aware)


@dataclass
class NightOverride:
    """GM adjustment applied during night resolution."""
    kind: str                    # "kill" | "spare"
    player: int
    cause: str = "gm"
    by: int | None = None


@dataclass
class Schedule:
    morning: str = "08:00"
    newspaper: str = "12:00"
    dusk: str = "19:00"
    second_lynch_end: str = "20:00"
    night_lock: str = "00:00"
    timezone: str = "Europe/Amsterdam"
    catch_up_limit_minutes: int = 120


@dataclass
class Settings:
    schedule: Schedule = field(default_factory=Schedule)
    newspaper_url: str | None = None
    role_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    family_size: int = 6
    inactivity_warn_hours: int = 24
    inactivity_flag_hours: int = 48
    gm_role_id: int | None = None
    notify_blocked_actions: bool = True   # tell players (without the reason) when their action was stopped


@dataclass
class LogEntry:
    category: str
    message: str
    actor: int | None = None
    targets: list[int] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    alert: bool = False          # ping the GMs


@dataclass
class GameState:
    guild_id: int
    game_id: int = 0
    phase: Phase = Phase.SETUP
    day: int = 0
    paused: bool = False
    started_at: str | None = None
    ended_at: str | None = None
    winner: str | None = None

    players: dict[int, Player] = field(default_factory=dict)
    backups: list[int] = field(default_factory=list)
    groups: dict[str, Group] = field(default_factory=dict)
    channels: dict[str, int] = field(default_factory=dict)       # announcements, votes, mod_log
    categories: list[int] = field(default_factory=list)
    discord_roles: dict[str, int] = field(default_factory=dict)  # PublicStatus value -> role id

    settings: Settings = field(default_factory=Settings)
    role_pool: dict[str, int] = field(default_factory=dict)

    actions: list[SubmittedAction] = field(default_factory=list)
    ballots: dict[str, Ballot] = field(default_factory=dict)
    ballot_archive: list[Ballot] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    night_overrides: list[NightOverride] = field(default_factory=list)
    next_transition: Transition | None = None
    relays: list[Relay] = field(default_factory=list)
    seances: list[Seance] = field(default_factory=list)
    telepathy: list[TelepathyMessage] = field(default_factory=list)
    # "listener:group" -> {user id: speaker number}, so transcripts number people consistently
    aliases: dict[str, dict[int, int]] = field(default_factory=dict)

    mayor: int | None = None
    mayor_successor: int | None = None
    lockdown: bool = False
    seeds: dict[str, int] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)  # free-form game data owned by roles

    # transient: flushed by the service layer in the same DB transaction as the state
    pending_logs: list[LogEntry] = transient(default_factory=list)
    pending_effects: list[Effect] = transient(default_factory=list)
    pending_reports: list[tuple[str, str]] = transient(default_factory=list)  # (title, body)

    def report(self, title: str, body: str) -> None:
        self.pending_reports.append((title, body))

    # --- players ---------------------------------------------------------
    def player(self, user_id: int) -> Player:
        player = self.players.get(user_id)
        if player is None:
            raise NotAPlayer("That person isn't part of this game.")
        return player

    def find_player(self, user_id: int | None) -> Player | None:
        return self.players.get(user_id) if user_id is not None else None

    def alive_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.alive]

    def dead_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.dead]

    def players_with_role(self, role_name: str, *, alive_only: bool = False) -> list[Player]:
        return [
            p for p in self.players.values()
            if p.role is not None and p.role.name == role_name and (p.alive or not alive_only)
        ]

    def name(self, user_id: int | None) -> str:
        if user_id is None:
            return "nobody"
        player = self.players.get(user_id)
        return player.display_name if player else f"<unknown {user_id}>"

    def iter_actors(self) -> Iterator[tuple[Player, Actor]]:
        for player in sorted(self.players.values(), key=lambda p: p.user_id):
            for actor in player.actors():
                yield player, actor

    # --- houses ----------------------------------------------------------
    # A house is a family: all family members live together. A player
    # without a family lives alone. (The Adopted Child's second family is TODO.)
    def house_of(self, user_id: int) -> str:
        player = self.players.get(user_id)
        if player is not None and player.family is not None:
            return player.family
        return f"house:{user_id}"

    def house_members(self, house: str) -> list[Player]:
        if house.startswith("house:"):
            player = self.players.get(int(house.split(":", 1)[1]))
            return [player] if player is not None else []
        group = self.groups.get(house)
        if group is None:
            return []
        return [self.players[u] for u in group.active_members() if u in self.players]

    def housemates(self, user_id: int) -> list[Player]:
        """Everyone living in this player's house, the player included."""
        return self.house_members(self.house_of(user_id))

    # --- groups ----------------------------------------------------------
    def group(self, key: str) -> Group:
        group = self.groups.get(key)
        if group is None:
            raise GameError(f"Unknown group '{key}'.")
        return group

    def groups_of_kind(self, kind: GroupKind) -> list[Group]:
        return [g for g in self.groups.values() if g.kind is kind]

    def ensure_group(self, key: str, kind: GroupKind, name: str, *, topic: str = "") -> Group:
        """Return the group, creating it (and queueing its channel) if new."""
        group = self.groups.get(key)
        if group is None:
            from Core.effects import CreateChannel
            group = Group(key=key, kind=kind, name=name, created_day=self.day, topic=topic)
            self.groups[key] = group
            if self.phase is not Phase.SETUP:
                self.emit(CreateChannel(group_key=key))
        return group

    # --- misc ------------------------------------------------------------
    def next_id(self, counter: str) -> int:
        value = self.counters.get(counter, 0) + 1
        self.counters[counter] = value
        return value

    def role_setting(self, role_name: str, key: str, default: Any) -> Any:
        return self.settings.role_overrides.get(role_name, {}).get(key, default)

    def log(self, category: str, message: str, *, actor: int | None = None,
            targets: list[int] | None = None, alert: bool = False, **data: Any) -> None:
        self.pending_logs.append(LogEntry(category, message, actor, list(targets or []), data, alert))

    def emit(self, effect: Effect) -> None:
        self.pending_effects.append(effect)

    @property
    def active(self) -> bool:
        return self.phase in ACTIVE_PHASES

    def slot(self, kind: str, day: int | None = None) -> str:
        return f"{kind}:{self.day if day is None else day}"

