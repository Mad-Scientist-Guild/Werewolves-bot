"""Delivers the audit log and resolution reports to each game's mod channel.

Log entries are written to the database first (in the same transaction as
the game state); this poster sends whatever hasn't been posted yet and
marks it posted. If the bot is down or the channel is missing, entries
simply wait - nothing is lost. Entries are batched into embeds to stay
well under Discord's rate limits.
"""
from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

import config
from Services.discord_utils import EMBED_LIMIT, chunks, embed, slug
from Services.game_service import GameService
from Storage.db import Database, EventRow

log = logging.getLogger("werewolves.audit")

CATEGORY_ICONS = {
    "ACTION": "🎯", "RESOLVED": "✅", "BALLOT": "🗳️", "LYNCH": "🪢", "WOLVES": "🐺", "MAYOR": "🎩",
    "PHASE": "🕰️", "GAME": "🎲", "PLAYER": "👤", "ROLE": "🎭", "MODIFIER": "➕", "GROUP": "👥",
    "DECISION": "⚖️", "GM": "🛠️", "REAPER": "💀", "ERROR": "❗", "COMMAND": "⌨️", "REJECTED": "🚫",
    "CHANNEL": "🔧", "STATUS": "⏳", "PUBLIC": "📣", "NEWSPAPER": "📰", "WIN": "🏆", "ACTIVITY": "💤",
    "SCHEDULER": "⏰", "SETUP": "🧰", "FAMILY": "🏠",
}


class AuditPoster:
    def __init__(self, bot: commands.Bot, db: Database, games: GameService):
        self.bot = bot
        self.db = db
        self.games = games
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="audit-poster")

    def wake(self, *_: object) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            await asyncio.sleep(1.5)  # gather a burst into one batch
            try:
                await self.flush()
            except Exception:
                log.exception("Posting the audit log failed")

    def _mod_channel(self, guild_id: int) -> discord.TextChannel | None:
        handle = self.games.find(guild_id)
        if handle is None:
            return None
        channel_id = handle.state.channels.get("mod_log")
        channel = self.bot.get_channel(channel_id) if channel_id else None
        return channel if isinstance(channel, discord.TextChannel) else None

    def _gm_mention(self, guild_id: int) -> str:
        handle = self.games.find(guild_id)
        role_id = (handle.state.settings.gm_role_id if handle else None) or config.GM_ROLE_ID
        return f"<@&{role_id}> " if role_id else ""

    def _fmt(self, event: EventRow) -> str:
        handle = self.games.find(event.guild_id)
        tz = ZoneInfo(handle.state.settings.schedule.timezone if handle else config.TIMEZONE)
        when = datetime.fromisoformat(event.at).astimezone(tz).strftime("%H:%M")
        icon = CATEGORY_ICONS.get(event.category, "•")
        day = f"D{event.day} " if event.day else ""
        return f"`{day}{when}` {icon} **{event.category}** {event.message}"

    async def flush(self) -> None:
        events = await self.db.unposted_events()
        by_guild: dict[int, list[EventRow]] = {}
        for event in events:
            by_guild.setdefault(event.guild_id, []).append(event)
        for guild_id, entries in by_guild.items():
            channel = self._mod_channel(guild_id)
            if channel is None:
                continue
            await self._post_entries(channel, guild_id, entries)

        for report in await self.db.unposted_reports():
            channel = self._mod_channel(report.guild_id)
            if channel is None:
                continue
            await self._post_report(channel, report.title, report.body)
            await self.db.mark_report_posted(report.id)

    async def _post_entries(self, channel: discord.TextChannel, guild_id: int, entries: list[EventRow]) -> None:
        normal = [e for e in entries if not e.alert]
        alerts = [e for e in entries if e.alert]
        if normal:
            pieces = chunks("\n".join(self._fmt(e) for e in normal), EMBED_LIMIT)
            for i in range(0, len(pieces), 10):
                embeds = [embed("", piece, color_name="grey") for piece in pieces[i:i + 10]]
                await channel.send(embeds=embeds)
            await self.db.mark_events_posted([e.id for e in normal])
        if alerts:
            text = "\n".join(self._fmt(e) for e in alerts)
            mention = self._gm_mention(guild_id)
            for piece in chunks(text, EMBED_LIMIT):
                await channel.send(mention + "attention needed", embed=embed("⚠️ GM attention", piece, color_name="orange"),
                                   allowed_mentions=discord.AllowedMentions(roles=True))
                mention = ""
            await self.db.mark_events_posted([e.id for e in alerts])

    async def _post_report(self, channel: discord.TextChannel, title: str, body: str) -> None:
        if len(body) <= EMBED_LIMIT:
            await channel.send(embed=embed(f"📋 {title}", body, color_name="purple"))
            return
        file = discord.File(io.BytesIO(body.encode("utf-8")), filename=f"{slug(title) or 'report'}.txt")
        first = chunks(body, EMBED_LIMIT)[0]
        await channel.send(embed=embed(f"📋 {title} (full report attached)", first, color_name="purple"), file=file)
