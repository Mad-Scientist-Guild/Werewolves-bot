"""Delivers queued Effects (the outbox) to Discord.

Effects are delivered in order and marked delivered one by one; a failure
is retried a few times before the GMs are alerted. Nothing is dropped
silently."""
from __future__ import annotations

import json
import logging

import discord
from discord.ext import commands

from Core.actor import ROLE_REGISTRY
from Core.effects import (
    Announcement,
    CreateChannel,
    DecisionPrompt,
    DirectMessage,
    Effect,
    GroupMessage,
    NewspaperPost,
    PrivateMessage,
    RoleCard,
    SeancePrompt,
    TelepathyPrompt,
    VoteChannelPost,
)
from Core.factions import faction_display
from Core.serialize import load
from Core.state import GameState
from Services.channels import ChannelManager
from Services.discord_utils import chunks, embed
from Services.game_service import GameHandle, GameService
from Services.role_commands import ability_help
from Services.views import decision_embed, decision_view, seance_view, telepathy_view
from Storage.db import Database

log = logging.getLogger("werewolves.effects")
PACK_HELP = "`/wolves vote <target>` · `/wolves abstain` · `/wolves status` — the pack's nightly vote"
MAX_ATTEMPTS = 5


class DeliveryError(Exception):
    pass


class EffectDelivery:
    def __init__(self, bot: commands.Bot, games: GameService, db: Database, channels: ChannelManager):
        self.bot = bot
        self.games = games
        self.db = db
        self.channels = channels

    async def deliver(self, guild: discord.Guild, handle: GameHandle) -> int:
        rows = await self.db.pending_effects(handle.game_id, MAX_ATTEMPTS)
        delivered = 0
        for effect_id, text, _ in rows:
            try:
                effect = load(Effect, json.loads(text))
                await self.apply(guild, handle, effect)
            except Exception as exc:  # noqa: BLE001 - every failure is recorded
                attempts = await self.db.mark_effect_failed(effect_id, repr(exc))
                log.warning("Effect %s failed (attempt %s): %r", effect_id, attempts, exc)
                if attempts >= MAX_ATTEMPTS:
                    await self.db.add_event(
                        guild_id=guild.id, game_id=handle.game_id, category="ERROR", alert=True,
                        message=f"Could not deliver an effect after {attempts} attempts: {text[:500]} — {exc!r}")
                continue
            await self.db.mark_effect_delivered(effect_id)
            delivered += 1
        return delivered

    # --- channels ------------------------------------------------------------
    def _channel(self, guild: discord.Guild, channel_id: int | None) -> discord.TextChannel:
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            raise DeliveryError(f"channel {channel_id} not found")
        return channel

    def _group_channel(self, guild: discord.Guild, state: GameState, group_key: str | None) -> discord.TextChannel:
        group = state.groups.get(group_key) if group_key else None
        if group is None:
            raise DeliveryError(f"group {group_key} not found")
        return self._channel(guild, group.channel_id)

    def _private(self, guild: discord.Guild, state: GameState, player_id: int) -> discord.TextChannel:
        return self._group_channel(guild, state, state.player(player_id).private_group)

    # --- dispatch ------------------------------------------------------------
    async def apply(self, guild: discord.Guild, handle: GameHandle, effect: Effect) -> None:
        state = handle.state
        footer = f"Day {state.day}"
        if isinstance(effect, PrivateMessage):
            channel = self._private(guild, state, effect.player)
            pieces = chunks(effect.text)
            for index, piece in enumerate(pieces):
                title = effect.title or "📜 News for you"
                if len(pieces) > 1:
                    title = f"{title} ({index + 1}/{len(pieces)})"
                await channel.send(embed=embed(title, piece, color_name="blue", footer=footer))
        elif isinstance(effect, GroupMessage):
            channel = self._group_channel(guild, state, effect.group)
            await channel.send(embed=embed(effect.title, effect.text, color_name="blue", footer=footer))
        elif isinstance(effect, Announcement):
            channel = self._channel(guild, state.channels.get("announcements"))
            await channel.send(embed=embed(effect.title, effect.text, color_name=effect.color, footer=footer))
        elif isinstance(effect, VoteChannelPost):
            channel = self._channel(guild, state.channels.get("announcements"))
            await channel.send(embed=embed(effect.title, effect.text, color_name="gold", footer=footer))
        elif isinstance(effect, NewspaperPost):
            channel = self._channel(guild, state.channels.get("announcements"))
            e = discord.Embed(title=f"📰 The XP Herald — day {state.day}", color=discord.Color.light_grey())
            e.set_image(url=effect.url)
            await channel.send(embed=e)
        elif isinstance(effect, RoleCard):
            channel = self._private(guild, state, effect.player)
            await channel.send(embed=role_card(state, effect))
        elif isinstance(effect, CreateChannel):
            await self.channels.ensure_group_channels(guild, handle)
        elif isinstance(effect, DecisionPrompt):
            await self._decision(guild, handle, effect.decision_id)
        elif isinstance(effect, DirectMessage):
            user = guild.get_member(effect.user_id) or await self.bot.fetch_user(effect.user_id)
            await user.send(effect.text)
        elif isinstance(effect, SeancePrompt):
            seance = next((s for s in state.seances if s.id == effect.seance_id), None)
            if seance is None or seance.done:
                return
            channel = self._group_channel(guild, state, seance.where)
            if seance.kind == "open_book":
                title = "📖 You are enchanted: Charm of the Open Book"
                text = f"You must answer this question honestly:\n> **{seance.question}**"
            else:
                title = "🕯️ The Spiritualist calls upon the dead"
                text = (f"A voice from the land of the living asks:\n> **{seance.question}**\n\n"
                        "Answer honestly - the dead may not lie. The Spiritualist only learns how many said yes and no.")
            await channel.send(embed=embed(title, text, color_name="purple"), view=seance_view(guild.id, seance.id))
        elif isinstance(effect, TelepathyPrompt):
            message = next((m for m in state.telepathy if m.id == effect.telepathy_id), None)
            if message is None:
                return
            channel = self._private(guild, state, message.target)
            text = (f"A message reached you through a Game Master:\n> “{message.text}”\n\n"
                    "You can send one reply of at most 20 words.")
            await channel.send(embed=embed("📨 A telepathic message", text, color_name="blue"),
                               view=telepathy_view(guild.id, message.id))
        else:
            raise DeliveryError(f"no delivery for {type(effect).__name__}")

    async def _decision(self, guild: discord.Guild, handle: GameHandle, decision_id: int) -> None:
        state = handle.state
        decision = next((d for d in state.decisions if d.id == decision_id), None)
        if decision is None or decision.resolved:
            return
        if decision.chooser is not None:
            channel = self._private(guild, state, decision.chooser)
        else:
            channel = self._channel(guild, state.channels.get("mod_log"))
        message = await channel.send(embed=decision_embed(state, decision), view=decision_view(state, decision))
        async with self.games.mutate(guild.id) as mutable:
            for d in mutable.decisions:
                if d.id == decision_id:
                    d.message_id = message.id


def role_card(state: GameState, effect: RoleCard) -> discord.Embed:
    cls = ROLE_REGISTRY.get(effect.role)
    if cls is None:
        return embed("Your role", f"Your role is **{effect.role}**.", color_name="purple")
    title = f"Your role has changed: {cls.title()}" if effect.changed else f"Your role: {cls.title()}"
    text = cls.description or "No description yet."
    if effect.note:
        text = f"{effect.note}\n\n{text}"
    e = embed(title, text, color_name="purple")
    e.add_field(name="Faction", value=faction_display(cls.faction), inline=True)
    lines = ability_help(cls)
    if cls.can_vote_wolf_kill:
        lines.append(PACK_HELP)
    if lines:
        e.add_field(name="Commands", value="\n".join(lines)[:1024], inline=False)
    e.add_field(name="Everyone", value="`/lynch vote` · `/mayor vote` · `/me` · `/rules`", inline=False)
    return e
