"""Real-time features: captures chat messages for eavesdrops (Peeking Girl,
Diviner) and closes eavesdrops and yes/no questions when their time is up."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from Core import realtime
from Core.clock import now_in, zone
from Core.state import ChatKind
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
        chat = next((g for g in state.chats.values() if g.channel_id == message.channel.id), None)
        if chat is None or not any(not r.done and r.source_chat == chat.key for r in state.eavesdrops):
            return
        if chat.kind is not ChatKind.VILLAGE and message.author.id not in chat.active_members():
            return   # only the chat's own members count (not GMs)
        at = message.created_at.astimezone(zone(state))
        text = message.clean_content or ""   # mentions become names: names mentioned stay visible
        for attachment in message.attachments:
            text += f" [attachment: {attachment.url}]"
        try:
            async with runtime.games.mutate(message.guild.id) as mutable:
                realtime.capture(mutable, chat.key, message.author.id, at, text.strip() or "(empty message)")
        except Exception:
            log.exception("Eavesdrop capture failed")

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
        if not realtime.due_eavesdrops(state, now) and not realtime.due_questions(state, now):
            return
        async with runtime.games.mutate(handle.guild_id) as mutable:
            for eavesdrop in realtime.due_eavesdrops(mutable, now):
                realtime.finish_eavesdrop(mutable, eavesdrop)
            for question in realtime.due_questions(mutable, now):
                realtime.close_question(mutable, question, "time is up")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Realtime(bot))
