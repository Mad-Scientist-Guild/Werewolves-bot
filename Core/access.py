"""Who may see / write in which game channel, derived purely from state.

The channel reconciler turns these into Discord permission overwrites, so
every rule about channel access lives here.

Data is never made inaccessible: leaving a group or a group being archived
downgrades to READ. The only full revocations are the death rules of the
rules document, written out explicitly below:
  * the dead chat is for the dead only - a raised Skeleton or a revived
    player loses it, and a Vengeful Spirit is kept out of it;
  * Membership.REVOKED, which only death-rule code may set.
"""
from __future__ import annotations

from enum import Enum

from Core.state import GameState, Group, GroupKind, LifeState, Membership, Player, PublicStatus


class Access(str, Enum):
    NONE = "none"     # can't see the channel
    READ = "read"     # read-only
    REACT = "react"   # read + add reactions (Skeletons in the village chat)
    WRITE = "write"


# channels that keep working during the Ruthless Counselor's lockdown
LOCKDOWN_EXEMPT = frozenset({GroupKind.PRIVATE, GroupKind.DEAD})


def player_access(state: GameState, group: Group, player: Player) -> Access:
    kind = group.kind

    if kind is GroupKind.VILLAGE:
        if group.archived:
            return Access.READ
        if player.life is LifeState.ALIVE:
            return Access.READ if state.lockdown else Access.WRITE
        if player.life is LifeState.SKELETON:
            return Access.REACT
        return Access.READ

    if kind is GroupKind.DEAD:
        # Death rules (explicit revocations): only the dead belong here.
        if not player.dead:
            return Access.NONE
        if any(m.blocks_dead_chat for m in player.modifiers):
            return Access.NONE
        return Access.READ if group.archived else Access.WRITE

    membership = group.members.get(player.user_id)
    if membership is None or membership is Membership.REVOKED:
        return Access.NONE
    if membership is Membership.FORMER or group.archived:
        return Access.READ

    if kind is GroupKind.PRIVATE:
        return Access.WRITE   # always able to talk to the GMs, dead or alive

    if player.life is LifeState.ALIVE:
        if state.lockdown and kind not in LOCKDOWN_EXEMPT:
            return Access.READ
        return Access.WRITE
    if player.life is LifeState.SKELETON:
        return Access.WRITE if kind in (GroupKind.SKELETONS, GroupKind.UNDEAD) else Access.READ
    # dead
    if kind is GroupKind.SPIRIT_LINE:
        return Access.WRITE
    return Access.READ


def due_public_status(player: Player) -> PublicStatus:
    """The public Discord role this player should have once their state is
    made public (at the newspaper, or immediately for a lynch)."""
    for modifier in reversed(player.modifiers):
        if modifier.public_status is not None:
            return modifier.public_status
    if player.life is LifeState.SKELETON:
        return PublicStatus.SKELETON
    if player.dead:
        return PublicStatus.DEAD
    return PublicStatus.NONE


def publish_statuses(state: GameState) -> list[Player]:
    """Make every player's public status match their state. Returns the
    players whose status changed."""
    changed = []
    for player in state.players.values():
        due = due_public_status(player)
        if player.public_status is not due:
            player.public_status = due
            changed.append(player)
    return changed
