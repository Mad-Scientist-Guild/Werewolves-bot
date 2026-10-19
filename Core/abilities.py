"""Declarative description of what a role can do.

A role lists its `Ability`s; the command layer, validation, resolution
pipeline and generated documentation all read from these declarations.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class Timing(str, Enum):
    NIGHT = "night"      # submitted 19:00-00:00, resolved at the night lock, applied at 08:00
    DAY = "day"          # submitted 08:00-19:00, resolved at dusk (19:00)
    ANYTIME = "anytime"  # submitted any time, resolved at the next resolution moment
    INSTANT = "instant"  # resolved the moment it is submitted


class Priority(IntEnum):
    """Order within a resolution. Lower runs first."""
    CURSE = 5
    LOCK = 10
    STALK = 15
    PROTECT = 20
    INFO = 30
    CONVERT = 40
    KILL = 50
    POST = 70


class ParamKind(str, Enum):
    LIVING_PLAYER = "living_player"
    DEAD_PLAYER = "dead_player"
    ANY_PLAYER = "any_player"
    ROLE = "role"
    CHOICE = "choice"
    TEXT = "text"
    TIME = "time"
    FAMILY = "family"
    NUMBER = "number"


PLAYER_KINDS = (ParamKind.LIVING_PLAYER, ParamKind.DEAD_PLAYER, ParamKind.ANY_PLAYER)


@dataclass(frozen=True)
class Param:
    name: str
    kind: ParamKind
    description: str = ""
    required: bool = True
    allow_self: bool = False
    choices: tuple[str, ...] = ()
    max_words: int | None = None


class P:
    """Short constructors for the common parameter shapes."""

    @staticmethod
    def living(name: str = "target", description: str = "A living player", **kw) -> Param:
        return Param(name, ParamKind.LIVING_PLAYER, description, **kw)

    @staticmethod
    def dead(name: str = "target", description: str = "A dead player", **kw) -> Param:
        return Param(name, ParamKind.DEAD_PLAYER, description, **kw)

    @staticmethod
    def any_player(name: str = "target", description: str = "A player", **kw) -> Param:
        return Param(name, ParamKind.ANY_PLAYER, description, **kw)

    @staticmethod
    def role(name: str = "role", description: str = "A role name", **kw) -> Param:
        return Param(name, ParamKind.ROLE, description, **kw)

    @staticmethod
    def choice(name: str, choices: tuple[str, ...], description: str = "", **kw) -> Param:
        return Param(name, ParamKind.CHOICE, description, choices=choices, **kw)

    @staticmethod
    def text(name: str = "text", description: str = "", **kw) -> Param:
        return Param(name, ParamKind.TEXT, description, **kw)

    @staticmethod
    def time(name: str = "time", description: str = "HH:MM, 24-hour", **kw) -> Param:
        return Param(name, ParamKind.TIME, description, **kw)

    @staticmethod
    def family(name: str = "family", description: str = "A family", **kw) -> Param:
        return Param(name, ParamKind.FAMILY, description, **kw)


@dataclass(frozen=True)
class Ability:
    key: str
    timing: Timing
    description: str = ""
    params: tuple[Param, ...] = ()
    priority: int = Priority.INFO
    leaves_house: bool = False
    # name of the param whose house is visited (None = leaves the house without visiting anyone)
    visits: str | None = "target"
    # uses per game; None = unlimited. GMs can override with the role setting "uses.<key>".
    uses: int | None = None
    # at most one use per day/night cycle
    once_per_cycle: bool = True
    # the actor may use it while dead (e.g. the Vengeful Spirit)
    usable_while_dead: bool = False
    # for INSTANT abilities: phases in which it may be used (empty = DAY, NIGHT and SLEEP)
    phases: tuple[str, ...] = ()
    # consume a use even when the action was blocked
    consume_on_block: bool = False
    # may be used during the first day (by default nothing happens on day 1)
    first_day: bool = False

    def param(self, name: str) -> Param | None:
        return next((p for p in self.params if p.name == name), None)
