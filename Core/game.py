
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum, auto
from typing import TYPE_CHECKING

import discord

from core.models import Player

if TYPE_CHECKING:
    from roles.role import Role


class GamePhase(Enum):
    LOBBY = auto()
    NIGHT = auto()
    DAY = auto()


class GameError(Exception):
    """Base for user-facing game-flow errors — cogs catch these and reply."""


class GameAlreadyActive(GameError):
    pass


class NoActiveGame(GameError):
    pass


class PlayerAlreadyJoined(GameError):
    pass


@dataclass
class Game:
    guild: discord.Guild
    phase: GamePhase = GamePhase.LOBBY
    day_number: int = 0
    started: bool = False
    finished: bool = False

    players: dict[int, Player] = field(default_factory=dict)  # keyed by member.id

    # channels, set via `game create`
    announcement_channel: discord.TextChannel | None = None
    vote_channel: discord.TextChannel | None = None
    moderator_channel: discord.TextChannel | None = None
    dead_channel: discord.TextChannel | None = None

    # schedule, set via `game times` / `lynch lynch_start_time` etc.
    morning_time: time | None = None
    night_time: time | None = None
    lynch_start_time: time | None = None
    lynch_end_time: time | None = None

    # various game variables
    cub_candidates: list[Player] = field(default_factory=list)

    def cub_guess_candidates(self, cub: Player) -> list[Player]:
        return self.cub_candidates


    pending_night_deaths: list[tuple[Player, str]] = field(default_factory=list)

    def queue_night_kill(self, player: Player, *, cause: str) -> None:
        """Marks a player to die at dawn, rather than immediately, this is
        what distinguishes a night kill (wolves, etc.) from an immediate
        one Resolved together via resolve_pending_deaths()."""
        if not player.alive:
            return
        if any(p is player for p, _ in self.pending_night_deaths):
            return  # already queued — e.g. two roles targeting the same player
        self.pending_night_deaths.append((player, cause))

    async def resolve_pending_deaths(self) -> list[tuple[Player, str]]:
        """Applies all queued night deaths (state only) and hands the list
        back to the caller to announce at dawn. Call once, when morning begins."""
        resolved: list[tuple[Player, str]] = []
        while self.pending_night_deaths:
            player, cause = self.pending_night_deaths.pop(0)
            resolved.append((player, cause))
            await self.kill(player, cause=cause)  # may itself queue more deaths via hooks
        return resolved


    @property
    def alive_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.alive]

    def get_player(self, member: discord.Member) -> Player | None:
        return self.players.get(member.id)

    def add_player(self, member: discord.Member) -> Player:
        if self.started:
            raise GameError("Game has already started — no new players can join.")
        if member.id in self.players:
            raise PlayerAlreadyJoined(f"{member.display_name} has already joined.")
        player = Player(member=member)
        self.players[member.id] = player
        return player

    def remove_player(self, member: discord.Member) -> None:
        self.players.pop(member.id, None)

    def assign_roles(self, role_counts: dict[str, int]) -> None:
        # Distribution logic (shuffle players, instantiate Role subclasses
        # from ROLE_REGISTRY, set player.role / player.faction) — fleshed
        # out once we build the roster/assignment cog.
        raise NotImplementedError

    async def kill(self, player: Player, *, cause: str) -> None:
        if not player.alive:
            return
        player.alive = False
        player.protections.clear()
        # TODO(core/helpers.py): announce death, revoke channel access,
        # move player to dead_channel. Pure state change ends here.

    # --- night/day orchestration -------------------------------------
    async def resolve_night(self) -> None:
        self.cub_candidates = []
        acting = [p for p in self.alive_players if p.role and p.role.night_priority is not None]
        acting.sort(key=lambda p: p.role.night_priority)
        for player in acting:
            await player.role.resolve_night(self)

    async def resolve_day(self) -> None:
        acting = [p for p in self.alive_players if p.role and p.role.day_priority is not None]
        acting.sort(key=lambda p: p.role.day_priority)
        for player in acting:
            await player.role.resolve_day(self)

    # --- I/O stubs, to be wired up alongside role interaction prompts --
    async def prompt_target(self, player: Player, prompt: str) -> Player: ...
    async def prompt_dead_player(self, player: Player) -> Player: ...
    async def prompt_role_guess(self, player: Player, target: Player) -> str: ...
    async def notify(self, player: Player, message: str) -> None: ...


# ---------------------------------------------------------------------------
# guild -> Game registry. Keyed by guild ID (int), not the discord.Guild
# object itself — ints are stable across reconnects/cache invalidation and
# will serialize cleanly
# ---------------------------------------------------------------------------
_games: dict[int, Game] = {}


def get_game(guild_id: int) -> Game:
    game = _games.get(guild_id)
    if game is None:
        raise NoActiveGame("There is no active game in this server.")
    return game


def create_game(guild: discord.Guild) -> Game:
    if guild.id in _games:
        raise GameAlreadyActive("A game is already active in this server.")
    game = Game(guild=guild)
    _games[guild.id] = game
    return game


def end_game(guild_id: int) -> None:
    _games.pop(guild_id, None)