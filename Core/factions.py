"""Factions and their win conditions.

Factions are registered like roles, so a new faction is one more
`register_faction` call. Win checks only *report* to the GMs (in the
resolution report); a GM ends the game with `/gm end_game`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from Core.state import GameState, LifeState, Player

VILLAGERS = "villagers"
WEREWOLVES = "werewolves"
UNDEAD = "undead"
LOVERS = "lovers"
COVEN = "coven"
NO_FACTION = "none"   # an investigation sees no faction (e.g. the Grave Robber before robbing)

EVIL_FACTIONS = frozenset({WEREWOLVES, UNDEAD, COVEN})


@dataclass(frozen=True)
class Faction:
    name: str
    display: str
    win_condition: str
    check_win: Callable[[GameState], bool]


FACTIONS: dict[str, Faction] = {}


def register_faction(faction: Faction) -> Faction:
    FACTIONS[faction.name] = faction
    return faction


def faction_display(name: str | None) -> str:
    if name is None or name == NO_FACTION:
        return "no faction"
    faction = FACTIONS.get(name)
    return faction.display if faction else name.title()


# --- counting helpers ----------------------------------------------------------

def counts_for_faction(player: Player) -> bool:
    """Whether this player keeps their faction 'alive'. Roles can opt out
    (the Cultist doesn't count as a werewolf when it comes to survival)."""
    role = player.role
    return not (role is not None and getattr(role, "never_counts_for_faction", False))


def living_members(state: GameState, faction: str) -> list[Player]:
    return [
        p for p in state.alive_players()
        if p.true_faction() == faction and counts_for_faction(p)
    ]


def faction_eliminated(state: GameState, faction: str) -> bool:
    # A faction whose only living members are lovers counts as eliminated -
    # a lover's true faction is "lovers", so they are never counted here.
    return not living_members(state, faction)


# --- default factions ---------------------------------------------------------

def _villagers_win(state: GameState) -> bool:
    return all(faction_eliminated(state, f) for f in EVIL_FACTIONS)


def _werewolves_win(state: GameState) -> bool:
    wolves = len(living_members(state, WEREWOLVES))
    if wolves == 0:
        return False
    others = [p for p in state.alive_players() if p.true_faction() != WEREWOLVES]
    return wolves > len(others)


def _undead_win(state: GameState) -> bool:
    undead = [p for p in state.players.values()
              if (p.life is LifeState.SKELETON or (p.alive and p.true_faction() == UNDEAD))]
    living_others = [p for p in state.alive_players() if p.true_faction() != UNDEAD]
    return bool(undead) and len(undead) > len(living_others)


def _lovers_win(state: GameState) -> bool:
    alive = state.alive_players()
    return bool(alive) and all(p.true_faction() == LOVERS or (p.role_name == "cupid") for p in alive)


def _coven_win(state: GameState) -> bool:
    kill_list = set(state.data.get("coven_kill_list", []))
    if not kill_list or faction_eliminated(state, COVEN):
        return False
    return not any(p.original_role in kill_list for p in state.alive_players())


register_faction(Faction(VILLAGERS, "Villagers", "The Werewolves, Coven and Undead are all gone.", _villagers_win))
register_faction(Faction(WEREWOLVES, "Werewolves", "More werewolves than non-werewolves are alive.", _werewolves_win))
register_faction(Faction(UNDEAD, "Undead", "There are more undead than living players.", _undead_win))
register_faction(Faction(LOVERS, "Lovers", "The lovers (and Cupid) are the last ones alive.", _lovers_win))
register_faction(Faction(COVEN, "Coven", "Every role on the coven kill list is gone.", _coven_win))


def winners(state: GameState) -> list[str]:
    return [name for name, faction in FACTIONS.items() if faction.check_win(state)]
