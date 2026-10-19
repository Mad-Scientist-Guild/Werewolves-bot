"""Loading, locking and persisting games.

Every change to a game goes through `mutate()`:

    async with runtime.games.mutate(guild_id) as state:
        ...change state...

It holds the game's lock (commands and the scheduler never interleave),
saves the state plus its new log entries, effects and reports in one
transaction, and restores the previous state if anything fails - so a
half-finished command never leaves the game in a broken state.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

from Core.errors import GameAlreadyActive, NoActiveGame
from Core.serialize import dump
from Core.state import GameState, Phase
from Storage.codec import STATE_VERSION, decode, encode
from Storage.db import Database

log = logging.getLogger("werewolves.games")


class GameHandle:
    def __init__(self, game_id: int, state: GameState):
        self.game_id = game_id
        self.state = state
        self.lock = asyncio.Lock()

    @property
    def guild_id(self) -> int:
        return self.state.guild_id


def status_of(state: GameState) -> str:
    if state.phase is Phase.SETUP:
        return "setup"
    if state.phase is Phase.ENDED:
        return "ended"
    return "active"


class GameService:
    def __init__(self, db: Database):
        self.db = db
        self.handles: dict[int, GameHandle] = {}
        self.listeners: list[Callable[[GameHandle], None]] = []

    # --- lookup ----------------------------------------------------------------
    def find(self, guild_id: int | None) -> GameHandle | None:
        return self.handles.get(guild_id) if guild_id is not None else None

    def get(self, guild_id: int | None) -> GameHandle:
        handle = self.find(guild_id)
        if handle is None:
            raise NoActiveGame("There is no game in this server. A GM can create one with `/game create`.")
        return handle

    def all(self) -> list[GameHandle]:
        return list(self.handles.values())

    # --- lifecycle -------------------------------------------------------------
    async def load_all(self) -> list[GameHandle]:
        for row in await self.db.active_games():
            try:
                state = decode(row.state, row.state_version)
            except Exception:
                log.exception("Could not load game %s for guild %s", row.id, row.guild_id)
                await self.db.add_event(guild_id=row.guild_id, game_id=row.id, category="ERROR", alert=True,
                                        message="This game's saved state could not be loaded - see the bot log.")
                continue
            state.game_id = row.id
            self.handles[row.guild_id] = GameHandle(row.id, state)
            log.info("Loaded game %s for guild %s (%s, day %s)", row.id, row.guild_id, state.phase.value, state.day)
        return self.all()

    async def create(self, guild_id: int) -> GameHandle:
        existing = self.handles.get(guild_id)
        if existing is not None:
            if existing.state.phase is Phase.ENDED:
                raise GameAlreadyActive("The last game in this server has ended but is still saved. Delete it with "
                                        "`/game delete` before creating a new one.")
            raise GameAlreadyActive("A game is already running in this server.")
        from Core.flow import default_role_pool
        state = GameState(guild_id=guild_id, role_pool=default_role_pool())
        game_id = await self.db.create_game(guild_id, encode(state), STATE_VERSION)
        state.game_id = game_id
        handle = GameHandle(game_id, state)
        self.handles[guild_id] = handle
        return handle

    # --- mutation --------------------------------------------------------------
    @asynccontextmanager
    async def mutate(self, guild_id: int | None, *, snapshot: str | None = None) -> AsyncIterator[GameState]:
        handle = self.get(guild_id)
        async with handle.lock:
            backup = copy.deepcopy(handle.state)
            try:
                yield handle.state
                await self._commit(handle, backup if snapshot else None, snapshot)
            except BaseException:
                handle.state = backup
                raise
        self._notify(handle)

    async def _commit(self, handle: GameHandle, before: GameState | None, label: str | None) -> None:
        state = handle.state
        events = [
            {"category": e.category, "message": e.message, "actor": e.actor, "targets": e.targets,
             "data": e.data, "alert": e.alert}
            for e in state.pending_logs
        ]
        effects = [json.dumps(dump(e), ensure_ascii=False) for e in state.pending_effects]
        reports = list(state.pending_reports)
        snap = (label, encode(before), before.phase.value, before.day) if before is not None and label else None
        await self.db.commit_game(
            game_id=handle.game_id, guild_id=handle.guild_id, status=status_of(state), phase=state.phase.value,
            day=state.day, state_json=encode(state), version=STATE_VERSION,
            events=events, effects=effects, reports=reports, snapshot=snap,
        )
        state.pending_logs.clear()
        state.pending_effects.clear()
        state.pending_reports.clear()

    async def restore(self, guild_id: int, snapshot_id: int, *, by: int) -> GameState:
        """Roll the game back to a snapshot. The current state is snapshotted
        first, so the rollback itself can be undone."""
        handle = self.get(guild_id)
        found = await self.db.snapshot(handle.game_id, snapshot_id)
        if found is None:
            raise NoActiveGame("No such snapshot for this game.")
        text, version = found
        restored = decode(text, version)
        restored.game_id = handle.game_id
        async with handle.lock:
            current = handle.state
            restored.log("GM", f"Game rolled back to snapshot #{snapshot_id}.", actor=by, alert=True)
            handle.state = restored
            try:
                await self._commit(handle, current, f"before rollback to #{snapshot_id}")
            except BaseException:
                handle.state = current
                raise
        self._notify(handle)
        return restored

    async def delete(self, guild_id: int, *, by: int) -> None:
        """Remove the game and all of its saved data (/game delete, after confirmation)."""
        handle = self.get(guild_id)
        async with handle.lock:
            await self.db.delete_game(handle.game_id)
            self.handles.pop(guild_id, None)
        log.warning("Game %s of guild %s deleted by user %s", handle.game_id, guild_id, by)

    def _notify(self, handle: GameHandle) -> None:
        for listener in self.listeners:
            try:
                listener(handle)
            except Exception:
                log.exception("Game listener failed")
