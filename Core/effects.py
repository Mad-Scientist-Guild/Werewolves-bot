"""Side effects the engine asks the Discord layer to perform.

The engine never talks to Discord. It appends Effects to
`GameState.pending_effects`; the service layer writes them to the outbox
table in the same transaction as the state, then delivers them. A crash
between saving and delivering just means they are delivered on restart.

Channel permissions and the public Discord roles are NOT effects - they are
derived from state by the channel reconciler.
"""
from __future__ import annotations

from dataclasses import dataclass

from Core.serialize import Polymorphic


@dataclass
class Effect(Polymorphic, family="effect"):
    pass


@dataclass
class PrivateMessage(Effect):
    """Posted in the player's private channel."""
    player: int
    text: str
    title: str = ""


@dataclass
class GroupMessage(Effect):
    group: str
    text: str
    title: str = ""


@dataclass
class Announcement(Effect):
    text: str
    title: str = ""
    color: str = "blue"


@dataclass
class VoteChannelPost(Effect):
    text: str
    title: str = ""


@dataclass
class RoleCard(Effect):
    """Role description + commands, posted in the player's private channel."""
    player: int
    role: str
    changed: bool = False   # True when this replaces an earlier role
    note: str = ""


@dataclass
class CreateChannel(Effect):
    """A group created mid-game needs its Discord channel."""
    group_key: str


@dataclass
class DecisionPrompt(Effect):
    decision_id: int


@dataclass
class NewspaperPost(Effect):
    url: str


@dataclass
class DirectMessage(Effect):
    """DM to a user (used sparingly, e.g. inactivity warnings)."""
    user_id: int
    text: str


@dataclass
class SeancePrompt(Effect):
    """The Spiritualist's question, with yes/no buttons, in the dead chat."""
    seance_id: int


@dataclass
class TelepathyPrompt(Effect):
    """A telepathic message (with a reply button) in the target's private channel."""
    telepathy_id: int
