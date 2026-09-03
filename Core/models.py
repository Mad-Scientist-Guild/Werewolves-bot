from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    # roles/role.py imports Player at runtime — this file can only
    # reference Role for type-checking, or we get an import cycle.
    from roles.role import Role


class Faction(Enum):
    VILLAGERS = auto()
    WEREWOLVES = auto()
    UNDEAD = auto()
    LOVERS = auto()


@dataclass
class Player:
    member: discord.Member
    role: "Role | None" = None
    faction: "Faction | None" = None
    family: "Family | None" = None
    alive: bool = True
    protections: set[str] = field(default_factory=set)
    last_protected: "Player | None" = None

    def set_role(self, role_cls: "type[Role]", *, keep_faction: bool = False) -> None:
        self.role = role_cls(self)
        if not keep_faction:
            self.faction = role_cls.faction


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