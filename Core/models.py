from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from Roles.role import Role
    from Roles.modifier import Modifier


class Faction(Enum):
    VILLAGERS = auto()
    WEREWOLVES = auto()
    UNDEAD = auto()
    LOVERS = auto()


class LifeState(Enum):
    ALIVE = auto()
    DEAD = auto()
    SKELETON = auto()
    PERMA_DEAD = auto()  # a skeleton killed again - cannot be revived a second time


@dataclass(eq=False)
class Player:
    member: discord.Member
    role: "Role | None" = None
    faction: Faction | None = None
    family: "Family | None" = None
    life_state: LifeState = LifeState.ALIVE
    modifiers: list["Modifier"] = field(default_factory=list)
    protections: set[str] = field(default_factory=set)
    last_protected: "Player | None" = None

    @property
    def alive(self) -> bool:
        return self.life_state is LifeState.ALIVE

    def set_role(self, role_cls: "type[Role]", *, keep_faction: bool = False) -> None:
        self.role = role_cls(self)
        if not keep_faction:
            self.faction = role_cls.faction

    def true_faction(self) -> Faction | None:
        # Most-recently-added modifier with an override wins.
        for modifier in reversed(self.modifiers):
            if modifier.true_faction_override is not None:
                return modifier.true_faction_override
        return self.faction

    def apparent_faction(self) -> Faction | None:
        for modifier in reversed(self.modifiers):
            if modifier.apparent_faction_override is not None:
                return modifier.apparent_faction_override
        if self.role is not None:
            return self.role.apparent_faction()
        return self.faction


@dataclass
class Family:
    name: str
    channel: discord.TextChannel
    members: list[Player] = field(default_factory=list)


@dataclass
class FactionChat:
    faction: Faction
    channel: discord.TextChannel
    members: list[Player] = field(default_factory=list)