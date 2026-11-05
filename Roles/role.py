"""Everything a role file needs, in one import:

    from Roles.role import *

See Roles/villagers/silver_angel.py for a complete, commented example.
"""
from dataclasses import field

import discord
from discord import app_commands

from Core.abilities import Ability, P, Param, ParamKind, Priority, Timing
from Core.actor import (
    MODIFIER_REGISTRY,
    ROLE_REGISTRY,
    RoleBase,
    Modifier,
    Role,
    register_modifier,
    register_role,
)
from Core.effects import PrivateMessage, RoleCard
from Core.errors import GameError
from Core.factions import COVEN, EVIL_FACTIONS, LOVERS, NO_FACTION, UNDEAD, VILLAGERS, WEREWOLVES, faction_display
from Core.flow import (
    add_modifier,
    adopt_role,
    add_condition,
    family_members,
    join_chat,
    register_chat,
    remove_modifier,
    seed,
    set_role,
)
from Core.resolution import CONVERSIONS, Attack, Resolution, Visit, register_conversion
from Core.state import (
    DeathRecord,
    GameState,
    ChatKind,
    LifeState,
    Phase,
    Player,
    PublicRole,
    Condition,
    SubmittedAction,
)
from Services.role_commands import RoleCommands, role_autocomplete

__all__ = [
    "field", "discord", "app_commands",
    "Ability", "P", "Param", "ParamKind", "Priority", "Timing",
    "MODIFIER_REGISTRY", "ROLE_REGISTRY", "RoleBase", "Modifier", "Role", "register_modifier", "register_role",
    "GameError", "PrivateMessage", "RoleCard",
    "COVEN", "EVIL_FACTIONS", "LOVERS", "NO_FACTION", "UNDEAD", "VILLAGERS", "WEREWOLVES", "faction_display",
    "add_modifier", "adopt_role", "add_condition", "family_members", "join_chat", "register_chat", "remove_modifier", "seed", "set_role",
    "CONVERSIONS", "Attack", "Resolution", "Visit", "register_conversion",
    "DeathRecord", "GameState", "ChatKind", "LifeState", "Phase", "Player", "PublicRole", "Condition", "SubmittedAction",
    "RoleCommands", "role_autocomplete",
]
