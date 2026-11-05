"""Changing who a player is: roles, modifiers, conditions, chats and families.

These are the building blocks the roles use (re-exported by Roles/role.py);
everything is a pure function on GameState.
"""
from __future__ import annotations

import copy
import random

from Core.actor import Modifier, Role, modifier_class, role_class
from Core.effects import RoleCard
from Core.errors import GameError
from Core.state import Chat, ChatKind, Condition, GameState, Membership, Phase, Player


# --- seeds ----------------------------------------------------------------------

def seed(state: GameState, key: str) -> int:
    """A persisted random seed, so previews and final resolutions match."""
    if key not in state.seeds:
        state.seeds[key] = random.SystemRandom().randrange(1, 2**31)
    return state.seeds[key]


# --- shared chats ---------------------------------------------------------------

# chat key -> (kind, channel name). Roles declare membership with `chats = ("wolves",)`.
CHAT_DEFS: dict[str, tuple[ChatKind, str]] = {}


def register_chat(key: str, kind: ChatKind, channel_name: str) -> None:
    CHAT_DEFS[key] = (kind, channel_name)


register_chat("wolves", ChatKind.WOLVES, "werewolves")
register_chat("undead", ChatKind.UNDEAD, "undead")


def join_chat(state: GameState, player: Player, key: str) -> Chat:
    kind, name = CHAT_DEFS.get(key, (ChatKind.CUSTOM, key))
    chat = state.ensure_chat(key, kind, name)
    if chat.members.get(player.user_id) is not Membership.ACTIVE:
        chat.add(player.user_id)
        state.log("CHAT", f"{player.display_name} joins {chat.name}.", actor=player.user_id)
    return chat


def join_actor_chats(state: GameState, player: Player) -> None:
    for actor in player.actors():
        for key in actor.chats:
            join_chat(state, player, key)


# --- players --------------------------------------------------------------------

def add_player(state: GameState, user_id: int, display_name: str) -> Player:
    if state.phase is not Phase.SETUP:
        raise GameError("The game has already started - new players can't join. Contact a GM.")
    if user_id in state.players:
        raise GameError(f"{display_name} has already joined.")
    player = Player(user_id=user_id, display_name=display_name)
    state.players[user_id] = player
    if user_id in state.backups:
        state.backups.remove(user_id)
    state.log("PLAYER", f"{display_name} joined the game.", actor=user_id)
    return player


def remove_player(state: GameState, user_id: int) -> None:
    if state.phase is not Phase.SETUP:
        raise GameError("Players can't be removed once the game has started - use the reaper instead.")
    player = state.player(user_id)
    del state.players[user_id]
    for chat in state.chats.values():
        chat.members.pop(user_id, None)
    state.log("PLAYER", f"{player.display_name} left the game.", actor=user_id)


# --- roles, modifiers, conditions -----------------------------------------------

def set_role(state: GameState, player: Player, role_name: str, *, keep_faction: bool = False,
             notify: bool = True, note: str = "", reason: str = "") -> Role:
    cls = role_class(role_name)
    old = player.role_name
    if state.phase is Phase.SETUP:
        private = state.chats.get(player.private_chat) if player.private_chat else None
        if private is not None and private.channel_id is not None:
            raise GameError(f"{player.display_name}'s private channel already exists and is named after their "
                            "role - change roles before creating channels, or use `/gm set_role` once the game runs.")
        for key in (player.role.chats if player.role else ()):
            if key in state.chats:
                state.chats[key].members.pop(player.user_id, None)
    player.role = cls(owner=player.user_id)
    if not keep_faction:
        player.faction = cls.faction
    if state.phase is Phase.SETUP:
        player.original_role = cls.name
    else:
        join_actor_chats(state, player)
        if notify:
            state.emit(RoleCard(player=player.user_id, role=cls.name, changed=old is not None, note=note))
    state.log("ROLE", f"{player.display_name}: {old or 'no role'} → {cls.name}"
              + (f" ({reason})" if reason else ""), actor=player.user_id)
    return player.role


def adopt_role(state: GameState, player: Player, role: Role, *, reason: str, note: str = "") -> Role:
    """Give a player a copy of an existing role instance - its state and used
    charges carry over (the Apprentice wolf taking over a fallen wolf)."""
    new = copy.deepcopy(role)
    new.owner = player.user_id
    old = player.role_name
    player.role = new
    join_actor_chats(state, player)
    state.emit(RoleCard(player=player.user_id, role=new.name, changed=True, note=note))
    state.log("ROLE", f"{player.display_name}: {old} → {new.name} ({reason}, charges carried over)", actor=player.user_id)
    return new


def add_modifier(state: GameState, player: Player, name: str, *, reason: str = "", **fields) -> Modifier:
    cls = modifier_class(name)
    existing = player.modifier(cls.name)
    if existing is not None:
        return existing
    modifier = cls(owner=player.user_id, **fields)
    player.modifiers.append(modifier)
    if state.phase is not Phase.SETUP:
        join_actor_chats(state, player)
    state.log("MODIFIER", f"{player.display_name} gains {cls.name}" + (f" ({reason})" if reason else ""),
              actor=player.user_id)
    return modifier


def remove_modifier(state: GameState, player: Player, name: str, *, reason: str = "") -> None:
    before = len(player.modifiers)
    player.modifiers = [m for m in player.modifiers if m.name != name]
    if len(player.modifiers) != before:
        state.log("MODIFIER", f"{player.display_name} loses {name}" + (f" ({reason})" if reason else ""),
                  actor=player.user_id)


def add_condition(state: GameState, player: Player, key: str, *, source: int | None = None,
                  expires: str | None = None, **data) -> Condition:
    condition = Condition(key=key, source=source, expires=expires, data=data)
    player.add_condition(condition)
    return condition


# --- families -------------------------------------------------------------------

def set_family(state: GameState, player: Player, family_key: str) -> None:
    family = state.chat(family_key)
    if family.kind is not ChatKind.FAMILY:
        raise GameError("That isn't a family.")
    if player.family and player.family in state.chats:
        old = state.chats[player.family]
        if state.phase is Phase.SETUP:
            old.members.pop(player.user_id, None)
        else:
            old.leave(player.user_id)
    family.add(player.user_id)
    player.family = family.key
    state.log("FAMILY", f"{player.display_name} is now in {family.name}.", actor=player.user_id)


def family_members(state: GameState, family_key: str | None) -> list[Player]:
    if family_key is None or family_key not in state.chats:
        return []
    return [state.players[u] for u in state.chats[family_key].active_members() if u in state.players]
