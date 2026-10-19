"""Real-time features: captures messages for eavesdropping relays (Peeking
Girl, Diviner) and closes relays and séances when their time is up."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from Core import realtime
from Core.clock import now_in, zone
from Core.state import GroupKind
from Services.game_service import GameHandle
from Services.runtime import runtime

log = logging.getLogger("werewolves.realtime")


class Realtime(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.loop.start()

    def cog_unload(self) -> None:
        self.loop.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        handle = runtime.games.find(message.guild.id)
        if handle is None or not handle.state.active:
            return
        state = handle.state
        group = next((g for g in state.groups.values() if g.channel_id == message.channel.id), None)
        if group is None or not any(not r.done and r.source_group == group.key for r in state.relays):
            return
        if group.kind is not GroupKind.VILLAGE and message.author.id not in group.active_members():
            return   # only the group's own members count (not GMs)
        at = message.created_at.astimezone(zone(state))
        text = message.clean_content or ""   # mentions become names: names mentioned stay visible
        for attachment in message.attachments:
            text += f" [attachment: {attachment.url}]"
        try:
            async with runtime.games.mutate(message.guild.id) as mutable:
                realtime.capture(mutable, group.key, message.author.id, at, text.strip() or "(empty message)")
        except Exception:
            log.exception("Relay capture failed")

    @tasks.loop(seconds=15)
    async def loop(self) -> None:
        for handle in runtime.games.all():
            try:
                await self._tick(handle)
            except Exception:
                log.exception("Realtime tick failed for guild %s", handle.guild_id)

    @loop.before_loop
    async def before_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _tick(self, handle: GameHandle) -> None:
        state = handle.state
        if not state.active:
            return
        now = now_in(state)
        if not realtime.due_relays(state, now) and not realtime.due_seances(state, now):
            return
        async with runtime.games.mutate(handle.guild_id) as mutable:
            for relay in realtime.due_relays(mutable, now):
                realtime.finish_relay(mutable, relay)
            for seance in realtime.due_seances(mutable, now):
                realtime.close_seance(mutable, seance, "time is up")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Realtime(bot))
