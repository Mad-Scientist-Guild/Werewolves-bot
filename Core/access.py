"""Who may see / write in which game channel, derived purely from state.

The channel reconciler turns these into Discord permission overwrites, so
every rule about channel access lives here.

Data is never made inaccessible: leaving a chat or a chat being archived
downgrades to READ. The only full revocations are the death rules of the
rules document, written out explicitly below:
  * the dead chat is for the dead only - a raised Skeleton or a revived
    player loses it, and a Vengeful Spirit is kept out of it;
  * Membership.REVOKED, which only death-rule code may set.
"""
from __future__ import annotations

from enum import Enum

from Core.state import GameState, Chat, ChatKind, LifeState, Membership, Player, PublicRole


class Access(str, Enum):
    NONE = "none"     # can't see the channel
    READ = "read"     # read-only
    REACT = "react"   # read + add reactions (Skeletons in the village chat)
    WRITE = "write"


# channels that keep working during the Ruthless Counselor's lockdown
LOCKDOWN_EXEMPT = frozenset({ChatKind.PRIVATE, ChatKind.DEAD})


def player_access(state: GameState, chat: Chat, player: Player) -> Access:
    kind = chat.kind

    if kind is ChatKind.VILLAGE:
        if chat.archived:
            return Access.READ
        if player.life is LifeState.ALIVE:
            return Access.READ if state.lockdown else Access.WRITE
        if player.life is LifeState.SKELETON:
            return Access.REACT
        return Access.READ

    if kind is ChatKind.DEAD:
        # Death rules (explicit revocations): only the dead belong here.
        if not player.dead:
            return Access.NONE
        if any(m.blocks_dead_chat for m in player.modifiers):
            return Access.NONE
        return Access.READ if chat.archived else Access.WRITE

    membership = chat.members.get(player.user_id)
    if membership is None or membership is Membership.REVOKED:
        return Access.NONE
    if membership is Membership.FORMER or chat.archived:
        return Access.READ

    if kind is ChatKind.PRIVATE:
        return Access.WRITE   # always able to talk to the GMs, dead or alive

    if player.life is LifeState.ALIVE:
        if state.lockdown and kind not in LOCKDOWN_EXEMPT:
            return Access.READ
        return Access.WRITE
    if player.life is LifeState.SKELETON:
        return Access.WRITE if kind in (ChatKind.SKELETONS, ChatKind.UNDEAD) else Access.READ
    # dead
    if kind is ChatKind.SPIRIT_CHAT:
        return Access.WRITE
    return Access.READ


def due_public_role(player: Player) -> PublicRole:
    """The public Discord role this player should have once their state is
    made public (at the newspaper, or immediately for a lynch)."""
    for modifier in reversed(player.modifiers):
        if modifier.public_role is not None:
            return modifier.public_role
    if player.life is LifeState.SKELETON:
        return PublicRole.SKELETON
    if player.dead:
        return PublicRole.DEAD
    return PublicRole.NONE


def publish_public_roles(state: GameState) -> list[Player]:
    """Make every player's public status match their state. Returns the
    players whose status changed."""
    changed = []
    for player in state.players.values():
        due = due_public_role(player)
        if player.public_role is not due:
            player.public_role = due
            changed.append(player)
    return changed
