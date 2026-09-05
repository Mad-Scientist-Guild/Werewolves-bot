
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum, auto
from typing import TYPE_CHECKING

import discord

from Core.models import Player, LifeState

if TYPE_CHECKING:
    from Roles.role import Role, Actor


class GamePhase(Enum):
    LOBBY = auto()
    NIGHT = auto()
    DAY = auto()


class GameError(Exception):
    """Base for user-facing game-flow errors - cogs catch these and reply."""


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

    role_channels: dict[str, discord.TextChannel] = field(default_factory=dict)

    newspaper_url: str | None = None

    # schedule, set via `game times` / `lynch lynch_start_time` etc.
    morning_time: time | None = None
    night_time: time | None = None
    lynch_start_time: time | None = None
    lynch_end_time: time | None = None

    # various game variables
    cub_candidates: list[Player] = field(default_factory=list)

    def cub_guess_candidates(self, cub: Player) -> list[Player]:
        return self.cub_candidates

    # --- death handling ------------------------------------------------------

    pending_night_deaths: list[tuple[Player, str]] = field(default_factory=list)

    def queue_night_kill(self, player: Player, *, cause: str) -> None:
        """Marks a player to die at dawn, Resolved together via resolve_pending_deaths()."""
        if not player.alive:
            return
        if any(p is player for p, _ in self.pending_night_deaths):
            return  # already queued - e.g. two roles targeting the same player
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

    async def kill(self, player: Player, *, cause: str) -> None:
        if player.life_state in (LifeState.DEAD, LifeState.PERMA_DEAD):
            return
        player.life_state = LifeState.PERMA_DEAD if player.life_state is LifeState.SKELETON else LifeState.DEAD
        player.protections.clear()

        if self.mayor is player:
            self.mayor = self.mayor_successor
            self.mayor_successor = None

        if player.role is not None:
            await player.role.on_death(self)
        for modifier in player.modifiers:
            await modifier.on_death(self)

        for other in self.alive_players:
            if other.role is not None:
                await other.role.on_other_death(self, player)
            for modifier in other.modifiers:
                await modifier.on_other_death(self, player)

    def revive(self, player: Player) -> None:
        if player.life_state is not LifeState.DEAD:
            return  # can't revive a still-living player, a skeleton, or a perma-dead one
        player.life_state = LifeState.ALIVE

    # --- player management ---------------------------------------------
    @property
    def alive_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.alive]

    def get_player(self, member: discord.Member) -> Player | None:
        return self.players.get(member.id)

    def add_player(self, member: discord.Member) -> Player:
        if self.started:
            raise GameError("Game has already started - no new players can join.")
        if member.id in self.players:
            raise PlayerAlreadyJoined(f"{member.display_name} has already joined.")
        player = Player(member=member)
        self.players[member.id] = player
        return player

    def remove_player(self, member: discord.Member) -> None:
        self.players.pop(member.id, None)

    def assign_roles(self, role_counts: dict[str, int]) -> None:
        # Distribution logic (shuffle players, instantiate Role subclasses
        # from ROLE_REGISTRY, set player.role / player.faction) - fleshed
        # out once we build the roster/assignment cog.
        raise NotImplementedError

    def players_with_role(self, role_name: str) -> list[Player]:
        return [p for p in self.players.values() if p.role is not None and p.role.name == role_name]

    # --- voting / lynch management -------------------------------------
    can_vote: bool = False
    votes: dict["Player | None", list[Player]] = field(default_factory=dict)   # None key = abstained
    voter_choice: dict[Player, "Player | None"] = field(default_factory=dict)  # reverse index for change-vote

    def cast_vote(self, voter: Player, target: Player | None) -> None:
        """target=None means abstain. Pure state - no messaging, no I/O."""
        if self.day_number <= 1:
            raise GameError("There is no lynching on the first day.")
        if not self.can_vote:
            raise GameError("You cannot vote yet.")
        if not voter.alive:
            raise GameError("You are already dead.")
        if target is not None and not target.alive:
            raise GameError("This person is already dead.")

        if voter in self.voter_choice:
            previous = self.voter_choice[voter]
            if previous == target:
                raise GameError("You have already voted for that.")
            bucket = self.votes.get(previous)
            if bucket and voter in bucket:
                bucket.remove(voter)

        self.votes.setdefault(target, []).append(voter)
        self.voter_choice[voter] = target

    def resolve_lynch(self) -> tuple[Player | None, str]:
        """Tallies the day's votes and resets vote state. Returns
        (winner, reason) - reason is one of: no_votes, abstained, tie,
        mayor_tiebreak, lynched. winner is None unless reason is
        lynched/mayor_tiebreak."""
        self.can_vote = False

        for player in self.alive_players:
            if player not in self.voter_choice:
                self.votes.setdefault(None, []).append(player)
                self.voter_choice[player] = None

        if not self.votes:
            self.votes.clear()
            self.voter_choice.clear()
            return None, "no_votes"

        ranked = sorted(self.votes.items(), key=lambda item: len(item[1]), reverse=True)
        top_count = len(ranked[0][1])

        if ranked[0][0] is None and top_count >= len(self.alive_players) // 2:
            self.votes.clear()
            self.voter_choice.clear()
            return None, "abstained"

        tied = [target for target, voters in ranked if target is not None and len(voters) == top_count]

        winner: Player | None = None
        reason = "tie"
        if len(tied) == 1:
            winner, reason = tied[0], "lynched"
        elif len(tied) > 1 and self.mayor is not None:
            # must read the mayor's choice before clearing voter_choice below
            mayor_vote = self.voter_choice.get(self.mayor)
            if mayor_vote in tied:
                winner, reason = mayor_vote, "mayor_tiebreak"

        self.votes.clear()
        self.voter_choice.clear()
        return winner, reason

    # --- mayor ---------------------------------------------------------
    mayor: Player | None = None
    mayor_successor: Player | None = None
    mayor_can_vote: bool = False
    mayor_votes: dict[Player, list[Player]] = field(default_factory=dict)
    mayor_voter_choice: dict[Player, Player] = field(default_factory=dict)

    def start_mayor_vote(self) -> None:
        self.mayor_can_vote = True
        self.mayor_votes.clear()
        self.mayor_voter_choice.clear()

    def cast_mayor_vote(self, voter: Player, target: Player) -> None:
        if not self.mayor_can_vote:
            raise GameError("The vote for mayor has not started.")
        if voter is target:
            raise GameError("You cannot vote for yourself.")
        if not voter.alive or not target.alive:
            raise GameError("Only living players can vote or be voted for.")

        previous = self.mayor_voter_choice.get(voter)
        if previous is target:
            raise GameError("You have already voted for that.")
        if previous is not None:
            bucket = self.mayor_votes.get(previous)
            if bucket and voter in bucket:
                bucket.remove(voter)

        self.mayor_votes.setdefault(target, []).append(voter)
        self.mayor_voter_choice[voter] = target

    def end_mayor_vote(self) -> tuple[Player | None, bool]:
        """Returns (winner, tied). winner is None if no votes were cast,
        or if the top two candidates are tied."""
        self.mayor_can_vote = False
        if not self.mayor_votes:
            return None, False

        ranked = sorted(self.mayor_votes.items(), key=lambda item: len(item[1]), reverse=True)
        tied = len(ranked) > 1 and len(ranked[1][1]) == len(ranked[0][1])

        self.mayor_votes.clear()
        self.mayor_voter_choice.clear()

        if tied:
            return None, True

        self.mayor = ranked[0][0]
        return self.mayor, False

    # --- night/day orchestration ---------------------------------------
    async def resolve_night(self) -> None:
        self.cub_candidates = []
        acting: list[tuple[Player, "Actor"]] = []
        for p in self.alive_players:
            if p.role is not None and p.role.night_priority is not None:
                acting.append((p, p.role))
            for modifier in p.modifiers:
                if modifier.night_priority is not None:
                    acting.append((p, modifier))
        acting.sort(key=lambda pair: pair[1].night_priority)
        for _, actor in acting:
            await actor.resolve_night(self)

    async def resolve_day(self) -> None:
        self.cub_candidates = []
        acting: list[tuple[Player, "Actor"]] = []
        for p in self.alive_players:
            if p.role is not None and p.role.day_priority is not None:
                acting.append((p, p.role))
            for modifier in p.modifiers:
                if modifier.day_priority is not None:
                    acting.append((p, modifier))
        acting.sort(key=lambda pair: pair[1].day_priority)
        for _, actor in acting:
            await actor.resolve_day(self)

    # --- I/O stubs, to be wired up alongside role interaction prompts --
    async def prompt_target(self, player: Player, prompt: str) -> Player: ...
    async def prompt_dead_player(self, player: Player) -> Player: ...
    async def prompt_role_guess(self, player: Player, target: Player) -> str: ...
    async def notify(self, player: Player, message: str) -> None: ...


# ---------------------------------------------------------------------------
# guild -> Game registry. Keyed by guild ID (int), not the discord.Guild
# object itself - ints are stable across reconnects/cache invalidation and
# will serialize cleanly
# ---------------------------------------------------------------------------
_games: dict[int, Game] = {}

def all_games() -> list[Game]:
    return list(_games.values())

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