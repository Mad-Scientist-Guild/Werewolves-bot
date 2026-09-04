from __future__ import annotations

import discord
from datetime import datetime, time

from core.game import Game, GameError, GamePhase
from core.models import Player


async def reply(interaction: discord.Interaction, msg: str, *, ephemeral: bool = True) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(msg, ephemeral=ephemeral)


async def ack_silent(interaction: discord.Interaction) -> None:
    """Acknowledge an interaction with no visible reply (JS's noReply)."""
    await interaction.response.defer(ephemeral=True)
    await interaction.delete_original_response()


async def send_announcement(
    game: Game, title: str, msg: str, *, color: discord.Color = discord.Color.blue()
) -> None:
    if game.announcement_channel is None:
        raise ValueError("Game has no announcement channel set.")
    embed = discord.Embed(title=title, description=msg, color=color)
    embed.set_footer(text=f"Day: {game.day_number}")
    await game.announcement_channel.send(embed=embed)


async def send_to_channel(
    channel: discord.TextChannel, title: str, msg: str, *, color: discord.Color = discord.Color.default()
) -> None:
    embed = discord.Embed(title=title, description=msg, color=color)
    await channel.send(embed=embed)


async def send_newspaper(game: Game) -> None:
    if game.announcement_channel is None:
        raise ValueError("Game has no announcement channel set.")
    if game.newspaper_url is None:
        return
    embed = discord.Embed(color=discord.Color.default())
    embed.set_image(url=game.newspaper_url)
    await game.announcement_channel.send(embed=embed)


async def send_mod_log(
    game: Game, title: str, msg: str, *, color: discord.Color = discord.Color.default()
) -> None:
    if game.moderator_channel is None:
        raise ValueError("Game has no moderator channel set.")
    embed = discord.Embed(title=title, description=msg, color=color)
    embed.set_footer(text=f"Day: {game.day_number}")
    await game.moderator_channel.send(embed=embed)


async def mute_in_channel(member: discord.Member, channel: discord.TextChannel) -> None:
    await channel.set_permissions(member, send_messages=False)


async def unmute_in_channel(member: discord.Member, channel: discord.TextChannel) -> None:
    await channel.set_permissions(member, send_messages=True)


async def set_channel_visible(member: discord.Member, channel: discord.TextChannel, *, visible: bool) -> None:
    await channel.set_permissions(member, view_channel=visible)


def voted_for_preset(voter: Player, voted_on: Player) -> str:
    return f"**{voter.member.display_name}** voted for **{voted_on.member.display_name}** for mayor"


async def apply_kill(game: Game, player: Player, *, cause: str) -> None:
    """Full death handling: state change + generic I/O. Mirrors JS's Kill(),
    minus the mayor/wildboy-specific branches — those are role-death hooks,
    deliberately deferred (see roles/role.py, Cub.handle_mother_death)."""
    await game.kill(player, cause=cause)

    for channel in game.guild.text_channels:
        await mute_in_channel(player.member, channel)

    if game.dead_channel is not None:
        await set_channel_visible(player.member, game.dead_channel, visible=True)
        await unmute_in_channel(player.member, game.dead_channel)

    await send_mod_log(game, "PLAYER DIED", f"{player.member.display_name} died.", color=discord.Color.red())

    # Hook point: role-specific reactions to this death (mayor succession,
    # wildboy mentor check, Cub/Mother Wolf, etc.) go here once we settle
    # the hook-dispatch design — e.g. a loop over game.alive_players
    # checking for a `Role.on_other_death(game, player)` method.

async def apply_revive(game: Game, player: Player) -> None:
    game.revive(player)
    for channel in game.guild.text_channels:
        await unmute_in_channel(player.member, channel)
    if game.dead_channel is not None:
        await mute_in_channel(player.member, game.dead_channel)
        await set_channel_visible(player.member, game.dead_channel, visible=False)
    await send_mod_log(game, "REVIVED", f"{player.member.display_name} was revived by a GM.", color=discord.Color.green())

def parse_time(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        raise GameError(f"'{value}' isn't a valid time — use HH:MM (24-hour), e.g. 08:30.")