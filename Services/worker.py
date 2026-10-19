"""Background follow-up after every committed change: deliver queued effects,
create any missing channels and reconcile permissions. One worker task per
game, woken by the game service; bursts of changes are coalesced."""
from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

from Core.state import Phase
from Services.audit import AuditPoster
from Services.channels import ChannelManager
from Services.effects import EffectDelivery
from Services.game_service import GameHandle, GameService

log = logging.getLogger("werewolves.worker")


class GameWorker:
    def __init__(self, bot: commands.Bot, games: GameService, delivery: EffectDelivery,
                 channels: ChannelManager, audit: AuditPoster):
        self.bot = bot
        self.games = games
        self.delivery = delivery
        self.channels = channels
        self.audit = audit
        self._events: dict[int, asyncio.Event] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._handles: dict[int, GameHandle] = {}

    def wake(self, handle: GameHandle) -> None:
        guild_id = handle.guild_id
        self._handles[guild_id] = handle
        event = self._events.setdefault(guild_id, asyncio.Event())
        event.set()
        task = self._tasks.get(guild_id)
        if task is None or task.done():
            self._tasks[guild_id] = asyncio.create_task(self._run(guild_id), name=f"game-worker-{guild_id}")
        self.audit.wake()

    async def _run(self, guild_id: int) -> None:
        await self.bot.wait_until_ready()
        event = self._events[guild_id]
        while True:
            await event.wait()
            event.clear()
            await asyncio.sleep(0.5)  # coalesce bursts
            handle = self._handles[guild_id]
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            try:
                if handle.state.phase is not Phase.SETUP:
                    await self.channels.ensure_group_channels(guild, handle)
                await self.delivery.deliver(guild, handle)
                await self.channels.sync(guild, handle)
            except Exception:
                log.exception("Worker for guild %s failed", guild_id)
            self.audit.wake()
