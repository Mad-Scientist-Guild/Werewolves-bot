from __future__ import annotations

from typing import ClassVar, TYPE_CHECKING

from core.models import Faction
from roles.role import Actor

if TYPE_CHECKING:
    from core.game import Game
    from core.models import Player


class Modifier(Actor):
    """An addition that stacks on top of a Player's base Role — Lover,
    Turned Wolf, Vampire Spawn, Vengeful Spirit. Several can be present on
    one Player at once, unlike Role."""

    true_faction_override: ClassVar[Faction | None] = None
    apparent_faction_override: ClassVar[Faction | None] = None


MODIFIER_REGISTRY: dict[str, type[Modifier]] = {}


def register_modifier(cls: type[Modifier]) -> type[Modifier]:
    MODIFIER_REGISTRY[cls.name] = cls
    return cls