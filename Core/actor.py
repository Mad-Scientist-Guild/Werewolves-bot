"""Base classes for roles and modifiers.

A *Role* is a player's base role (exactly one). A *Modifier* stacks on top
(Lover, Turned wolf, Skeleton, Vengeful Spirit, Mayor...). Both are
*Actors*: they can provide abilities, keep state, and react to the
resolution pipeline through hooks. All hooks are synchronous and pure -
they read and change engine state only, never Discord.

Subclasses are turned into dataclasses by `register_role` /
`register_modifier`, so role state is declared as annotated fields and is
saved automatically:

    @register_role
    class Seer(Role):
        name = "seer"
        checked: list[int] = field(default_factory=list)
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from Core.abilities import Ability
from Core.errors import GameError
from Core.serialize import Polymorphic, register_type_names
from Core.state import PublicStatus

if TYPE_CHECKING:
    from Core.resolution import Kill, Resolution, Visit
    from Core.state import DeathRecord, GameState, Player, SubmittedAction


@dataclass(eq=False)
class Actor(Polymorphic, family="actor"):
    name: ClassVar[str] = "_actor"   # every role/modifier sets its own
    display: ClassVar[str] = ""
    description: ClassVar[str] = ""
    abilities: ClassVar[tuple[Ability, ...]] = ()
    can_vote_wolf_kill: ClassVar[bool] = False
    # shared chats this actor belongs to (keys registered with Core.flow.register_group)
    groups: ClassVar[tuple[str, ...]] = ()

    owner: int = 0
    uses: dict[str, int] = field(default_factory=dict)       # ability key -> uses consumed
    last_used: dict[str, int] = field(default_factory=dict)  # ability key -> day of last use

    @classmethod
    def _poly_tag(cls) -> str:
        return cls.__dict__.get("name", cls.__name__)

    @classmethod
    def title(cls) -> str:
        return cls.display or cls.name.replace("_", " ").title()

    # --- helpers ---------------------------------------------------------
    def player(self, state: GameState) -> Player:
        return state.player(self.owner)

    def setting(self, state: GameState, key: str, default: Any) -> Any:
        return state.role_setting(self.name, key, default)

    def ability(self, key: str) -> Ability | None:
        return next((a for a in self.abilities if a.key == key), None)

    def provides(self, source: str) -> bool:
        """Whether this actor answers to the command group of `source` (the
        Actor answers for the role it's currently copying)."""
        return self.name == source

    def command_source(self, ability_key: str) -> str:
        """Whose command group offers this ability (for help texts)."""
        return self.name

    def max_uses(self, state: GameState, ability: Ability) -> int | None:
        return self.setting(state, f"uses.{ability.key}", ability.uses)

    def uses_left(self, state: GameState, ability: Ability) -> int | None:
        limit = self.max_uses(state, ability)
        if limit is None:
            return None
        return max(0, limit - self.uses.get(ability.key, 0))

    def consume(self, state: GameState, ability_key: str) -> None:
        self.uses[ability_key] = self.uses.get(ability_key, 0) + 1
        self.last_used[ability_key] = state.day

    def refund(self, ability_key: str) -> None:
        """Give back a use consumed earlier in this resolution (e.g. a turn that lost a conflict)."""
        self.uses[ability_key] = max(0, self.uses.get(ability_key, 0) - 1)

    # --- availability / validation hooks --------------------------------
    def available_abilities(self, state: GameState) -> list[Ability]:
        """Abilities this actor can currently offer. Override for conditional
        abilities (e.g. Apprentice wolf only after a wolf died)."""
        return [a for a in self.abilities if self.uses_left(state, a) != 0]

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        """Raise GameError if the action isn't allowed. Generic checks
        (phase, targets alive, uses) already ran."""

    # --- resolution hooks ------------------------------------------------
    def interact(self, ctx: Resolution, action: SubmittedAction) -> None:
        """Interaction pass: curses, locks, stalks, protections. Only called
        for this actor's own actions with priority < INFO."""
        handler = getattr(self, f"interact_{action.ability}", None)
        if handler is not None:
            handler(ctx, action)

    def resolve(self, ctx: Resolution, action: SubmittedAction) -> None:
        """Evaluation pass: read ctx.state (unchanged until commit) and
        emit intents with ctx.inform / ctx.kill / ctx.commit."""
        handler = getattr(self, f"resolve_{action.ability}", None)
        if handler is None:
            raise GameError(f"{self.name} has no resolver for '{action.ability}'")
        handler(ctx, action)

    def on_movement(self, ctx: Resolution) -> None:
        """Called once per resolution after the planned visits are known,
        before protections. Used by locks and stalks."""

    def protects_against(self, ctx: Resolution, kill: Kill) -> str | None:
        """Return a reason if this actor (on the kill's target) prevents it."""
        return None

    def on_visited(self, ctx: Resolution, visit: Visit) -> None:
        """Called on the actors of a player whose house was visited."""

    def defeats_stalkers(self, state: GameState, action: SubmittedAction) -> bool:
        """True if leaving the house for `action` kills a stalker waiting
        outside instead of being stopped (the Vigilante, an armed Monster Hunter)."""
        return False

    def on_kill_prevented(self, ctx: Resolution, kill: Kill) -> None:
        """A kill (or turn, cause "turn") on this actor's owner was prevented."""

    def on_other_killed(self, ctx: Resolution, kill: Kill) -> None:
        """A kill on someone was confirmed and is about to be applied (called for
        every actor). Used for collateral deaths, e.g. the visiting Village Slut."""

    def on_other_converted(self, ctx: Resolution, player: Player, kind: str, by: int) -> None:
        """Someone was converted (kind: "werewolf", "vampire", ...); called for every actor."""

    def on_death(self, ctx: Resolution, record: DeathRecord) -> None:
        """This actor's owner just died."""

    def on_other_death(self, ctx: Resolution, dead: Player) -> None:
        """Someone else just died (called for every actor in the game)."""

    def on_revived(self, ctx: Resolution) -> None:
        """This actor's owner was just revived."""

    def after_resolution(self, ctx: Resolution) -> None:
        """Last hook of every resolution (newspaper notes, cleanup)."""

    def on_game_start(self, state: GameState) -> None:
        """Called once when the game starts (e.g. the Normal wolf's hint)."""

    # --- appearance ------------------------------------------------------
    def apparent_faction(self, state: GameState, observer: str) -> str | None:
        """What faction an investigation (`observer` = role name) sees. None
        means no opinion; the next actor or the true faction is used."""
        return None

    def apparent_role(self, state: GameState, observer: str) -> str | None:
        return None


@dataclass(eq=False)
class Role(Actor):
    faction: ClassVar[str] = "villagers"
    tags: ClassVar[frozenset[str]] = frozenset()
    # roles a player can't start with (Turned wolf, Skeleton...) set this False
    assignable: ClassVar[bool] = True


@dataclass(eq=False)
class Modifier(Actor):
    # override the player's faction while this modifier is present
    true_faction: ClassVar[str | None] = None
    # public Discord role this modifier implies (Skeleton, Vengeful Spirit)
    public_status: ClassVar[PublicStatus | None] = None
    # explicit death-rule revocation: keep this player out of the dead chat
    blocks_dead_chat: ClassVar[bool] = False

    def faction_override(self, player: Player) -> str | None:
        return self.true_faction


@dataclass(eq=False)
class MissingActor(Actor):
    """Stands in for a stored role/modifier whose class no longer exists (the
    role file was removed). Keeps the raw data so nothing is lost."""
    name: ClassVar[str] = "_missing"
    raw: dict = field(default_factory=dict)

    def __raw_dump__(self) -> dict:
        return self.raw

    def faction_override(self, player: Player) -> str | None:
        return None

    @property
    def missing_name(self) -> str:
        return str(self.raw.get("__type__", "?"))


Actor.__missing_type__ = staticmethod(lambda data: MissingActor(owner=int(data.get("owner", 0)), raw=dict(data)))  # type: ignore[attr-defined]


ROLE_REGISTRY: dict[str, type[Role]] = {}
MODIFIER_REGISTRY: dict[str, type[Modifier]] = {}


def _check_name(cls: type[Actor]) -> None:
    if "name" not in cls.__dict__:
        raise TypeError(f"{cls.__name__} must define a `name`")


def register_role(cls: type[Role]) -> type[Role]:
    _check_name(cls)
    cls = dataclasses.dataclass(eq=False)(cls)
    if cls.name in ROLE_REGISTRY and ROLE_REGISTRY[cls.name].__qualname__ != cls.__qualname__:
        raise TypeError(f"Duplicate role name '{cls.name}'")
    ROLE_REGISTRY[cls.name] = cls
    return cls


def register_modifier(cls: type[Modifier]) -> type[Modifier]:
    _check_name(cls)
    cls = dataclasses.dataclass(eq=False)(cls)
    if cls.name in MODIFIER_REGISTRY and MODIFIER_REGISTRY[cls.name].__qualname__ != cls.__qualname__:
        raise TypeError(f"Duplicate modifier name '{cls.name}'")
    MODIFIER_REGISTRY[cls.name] = cls
    return cls


def role_class(name: str) -> type[Role]:
    cls = ROLE_REGISTRY.get(name.lower().replace(" ", "_"))
    if cls is None:
        raise GameError(f"'{name}' isn't a known role.")
    return cls


def modifier_class(name: str) -> type[Modifier]:
    cls = MODIFIER_REGISTRY.get(name.lower().replace(" ", "_"))
    if cls is None:
        raise GameError(f"'{name}' isn't a known modifier.")
    return cls


register_type_names(Actor=Actor, Role=Role, Modifier=Modifier)
