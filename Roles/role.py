from __future__ import annotations

from abc import ABC
from enum import IntEnum
from typing import ClassVar, TYPE_CHECKING

from Core.models import Faction
from Core.game import GameError, GamePhase
from Core.helpers import is_sleep_time

if TYPE_CHECKING:
    from Core.game import Game
    from Core.models import Player


class ActionPriority(IntEnum):
    LOCK = 10
    PROTECT = 20
    INFO_GATHER = 30
    CONVERT = 40
    KILL = 50
    DEATH_RESOLUTION = 60
    POST = 70


class Actor(ABC):
    """Shared shape for anything that resolves during night/day and reacts
    to deaths - a Player's base Role, and each of their stacked Modifiers,
    both are one."""

    name: ClassVar[str]
    night_priority: ClassVar[ActionPriority | None] = None
    day_priority: ClassVar[int | None] = None

    def __init__(self, player: "Player"):
        self.player = player
        self.night_target: "Player | None" = None
        self.day_target: "Player | None" = None

    async def resolve_night(self, game: "Game") -> None:
        return None

    async def resolve_day(self, game: "Game") -> None:
        return None

    def set_night_target(self, game: "Game", target: "Player | None") -> None:
        if game.phase is not GamePhase.NIGHT:
            raise GameError("It is not currently night.")
        if is_sleep_time():
            raise GameError("It's sleep time (00:01–07:59) - night actions are locked in until morning.")
        self.night_target = target

    def set_day_target(self, game: "Game", target: "Player | None") -> None:
        if game.phase is not GamePhase.DAY:
            raise GameError("It is not currently day.")
        self.day_target = target

    async def on_death(self, game: "Game") -> None:
        return None

    async def on_other_death(self, game: "Game", dead_player: "Player") -> None:
        return None


class Role(Actor):
    faction: ClassVar[Faction]
    reveals_as: ClassVar[Faction | None] = None

    def __init__(self, player: "Player"):
        super().__init__(player)
        self.charges_used = 0

    def apparent_faction(self) -> Faction:
        return self.reveals_as or self.faction


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