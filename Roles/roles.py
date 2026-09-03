from __future__ import annotations

from abc import ABC
from enum import IntEnum
from typing import ClassVar, TYPE_CHECKING

from core.models import Faction

if TYPE_CHECKING:
    # Only needed for type hints on night_action/day_action — Role never
    # touches Game at import time, so this stays TYPE_CHECKING-only even
    # though core/game.py currently does the same in reverse for Role.
    from core.game import Game
    from core.models import Player


class ActionPriority(IntEnum):
    LOCK = 10               # Locksmith
    PROTECT = 20            # Silver Angel
    INFO_GATHER = 30        # Seer, Fox, Prophet, Bloodhound, Trapmaker setup
    CONVERT = 40            # Ancient Wolf, Vampire Lord (turn variant)
    KILL = 50               # Wolves, Vampire Lord, Vigilante, Witch, Rabid Wolf, Cub
    DEATH_RESOLUTION = 60   # heartbreak, vengeful spirit checks, trap reveal
    POST = 70               # Undertaker-style next-day info prep


class Role(ABC):
    name: ClassVar[str]
    faction: ClassVar[Faction]
    night_priority: ClassVar[ActionPriority | None] = None
    day_priority: ClassVar[int | None] = None
    reveals_as: ClassVar[Faction | None] = None

    def __init__(self, player: "Player"):
        self.player = player
        self.charges_used = 0

        self.night_target: "Player | None" = None  # set by a cog command, read at resolution

    def apparent_faction(self) -> Faction:
        return self.reveals_as or self.faction

    async def night_action(self, game: "Game") -> None:
        """Override in subclasses that have a night action. No-op by default."""
        return None

    async def day_action(self, game: "Game") -> None:
        """Override in subclasses that have a day action. No-op by default."""
        return None

    async def resolve_night(self, game: "Game") -> None:
        """Called after all night actions have been collected, in order of
        night_priority. No-op by default."""
        return None

    async def resolve_day(self , game: "Game") -> None:
        """Called after all day actions have been collected, in order of
        day_priority. No-op by default."""
        return None

    async def on_death(self, game: "Game") -> None:
        """Called on this role's own player when they die (e.g. Hunter's
        final shot). No-op by default."""
        return None

    async def on_other_death(self, game: "Game", dead_player: "Player") -> None:
        """Called on every other alive player's role whenever someone else
        dies. No-op by default."""
        return None


ROLE_REGISTRY: dict[str, type[Role]] = {}


def register_role(cls: type[Role]) -> type[Role]:
    ROLE_REGISTRY[cls.name] = cls
    return cls


# --- Example roles, one file each once we split roles/ out -----------------

@register_role
class SilverAngel(Role):
    name = "silver_angel"
    faction = Faction.VILLAGERS
    night_priority = ActionPriority.PROTECT

    async def resolve_night(self, game: "Game") -> None:
        if self.night_target is None or self.night_target is self.player.last_protected:
            return
        self.night_target.protections.add("silver_angel")
        self.player.last_protected = self.night_target


@register_role
class Cultist(Role):
    name = "cultist"
    faction = Faction.WEREWOLVES
    reveals_as = Faction.VILLAGERS


@register_role
class GraveRobber(Role):
    name = "grave_robber"
    faction = Faction.VILLAGERS
    day_priority = 0

    async def day_action(self, game: "Game") -> None:
        dead_target = await game.prompt_dead_player(self.player)
        self.player.set_role(dead_target.role.__class__)


@register_role
class Cub(Role):
    name = "cub"
    faction = Faction.WEREWOLVES
    reveals_as = Faction.VILLAGERS
    night_priority = ActionPriority.KILL

    async def night_action(self, game: "Game") -> None:
        candidates = game.cub_guess_candidates(self.player)
        for target in candidates:
            guess = await game.prompt_role_guess(self.player, target)
            if guess == target.role.name:
                await game.kill(target, cause="cub_guess")
                self.player.faction = Faction.WEREWOLVES
                break

    def handle_mother_death(self) -> None:
        if self.player.faction is Faction.WEREWOLVES and self.charges_used == 0:
            self.player.faction = Faction.VILLAGERS