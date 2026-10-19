"""Tracks when players were last active (messages and commands) and warns
about inactivity: a warning around 24 hours, a GM alert at 48 hours.

Activity is collected in memory and written to the game state every few
minutes, so chatting doesn't cause a database write per message."""
from __future__ import annotations

import logging
from datetime import datetime

import discord
from discord.ext import commands, tasks

from Core.clock import now_in
from Core.effects import PrivateMessage
from Services.runtime import runtime

log = logging.getLogger("werewolves.activity")


class Activity(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.seen: dict[int, dict[int, str]] = {}
        self.flush.start()

    def cog_unload(self) -> None:
        self.flush.cancel()

    def _touch(self, guild_id: int | None, user_id: int) -> None:
        handle = runtime.games.find(guild_id)
        if handle is None or not handle.state.active or user_id not in handle.state.players:
            return
        self.seen.setdefault(guild_id, {})[user_id] = now_in(handle.state).isoformat()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is not None and not message.author.bot:
            self._touch(message.guild.id, message.author.id)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is not None:
            self._touch(interaction.guild_id, interaction.user.id)

    @tasks.loop(minutes=5)
    async def flush(self) -> None:
        for handle in runtime.games.all():
            try:
                await self._flush_game(handle)
            except Exception:
                log.exception("Activity flush failed for guild %s", handle.guild_id)

    @flush.before_loop
    async def before_flush(self) -> None:
        await self.bot.wait_until_ready()

    async def _flush_game(self, handle) -> None:
        state = handle.state
        if not state.active:
            return
        updates = self.seen.pop(handle.guild_id, {})
        now = now_in(state)
        warn_h, flag_h = state.settings.inactivity_warn_hours, state.settings.inactivity_flag_hours

        def level_for(player) -> int:
            since = updates.get(player.user_id) or player.last_active_at or state.started_at
            if since is None:
                return 0
            hours = (now - datetime.fromisoformat(since)).total_seconds() / 3600
            return 2 if hours >= flag_h else 1 if hours >= warn_h else 0

        changes = {p.user_id: level_for(p) for p in state.alive_players()
                   if level_for(p) != p.inactivity_level}
        if not updates and not changes:
            return
        async with runtime.games.mutate(handle.guild_id) as mutable:
            for user_id, at in updates.items():
                if user_id in mutable.players:
                    mutable.players[user_id].last_active_at = at
            for user_id, level in changes.items():
                player = mutable.players.get(user_id)
                if player is None or not player.alive:
                    continue
                previous = player.inactivity_level
                player.inactivity_level = level
                if level == 0 and previous:
                    mutable.log("ACTIVITY", f"{player.display_name} is active again.", actor=user_id)
                elif level == 1:
                    mutable.log("ACTIVITY", f"{player.display_name} has been inactive for over {warn_h} hours - "
                                            "they've been warned.", actor=user_id, alert=True)
                    mutable.emit(PrivateMessage(
                        player=user_id, title="⏰ Are you still there?",
                        text=f"You haven't been active for over {warn_h} hours. If you're inactive for {flag_h} hours "
                             "you may be fed to the wolves or replaced by someone from the waiting list."))
                elif level == 2:
                    mutable.log("ACTIVITY", f"{player.display_name} has been inactive for over {flag_h} hours. "
                                            "Consider the Reaper (`/gm replace` or `/gm kill`).", actor=user_id, alert=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Activity(bot))
