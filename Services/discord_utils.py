"""Small Discord helpers shared by cogs and services."""
from __future__ import annotations

import io
import re

import discord

import config
from Core.errors import GameError
from Core.state import GameState

COLORS = {
    "blue": discord.Color.blue(),
    "red": discord.Color.red(),
    "green": discord.Color.green(),
    "gold": discord.Color.gold(),
    "purple": discord.Color.purple(),
    "grey": discord.Color.light_grey(),
    "default": discord.Color.default(),
    "orange": discord.Color.orange(),
}

EMBED_LIMIT = 4000


def color(name: str) -> discord.Color:
    return COLORS.get(name, discord.Color.default())


def embed(title: str, text: str, *, color_name: str = "default", footer: str | None = None) -> discord.Embed:
    e = discord.Embed(title=title[:256] or None, description=text[:EMBED_LIMIT], color=color(color_name))
    if footer:
        e.set_footer(text=footer[:2048])
    return e


async def reply(interaction: discord.Interaction, text: str, *, ephemeral: bool = True,
                embed_obj: discord.Embed | None = None) -> None:
    kwargs = {"ephemeral": ephemeral}
    if embed_obj is not None:
        kwargs["embed"] = embed_obj
    content = text[:2000] if text else None
    if interaction.response.is_done():
        await interaction.followup.send(content, **kwargs)
    else:
        await interaction.response.send_message(content, **kwargs)


async def reply_long(interaction: discord.Interaction, title: str, text: str, *, ephemeral: bool = True) -> None:
    """Embed if it fits, otherwise a text file."""
    if len(text) <= EMBED_LIMIT:
        await reply(interaction, "", embed_obj=embed(title, text), ephemeral=ephemeral)
        return
    file = discord.File(io.BytesIO(text.encode("utf-8")), filename=f"{slug(title) or 'report'}.txt")
    if interaction.response.is_done():
        await interaction.followup.send(f"**{title}** (attached)", file=file, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(f"**{title}** (attached)", file=file, ephemeral=ephemeral)


def slug(text: str, *, limit: int = 90) -> str:
    text = re.sub(r"[^a-z0-9\-_]+", "-", text.lower().replace(" ", "-"))
    return re.sub(r"-{2,}", "-", text).strip("-")[:limit]


def chunks(text: str, size: int = EMBED_LIMIT) -> list[str]:
    """Split on line boundaries into pieces of at most `size` characters."""
    out: list[str] = []
    current = ""
    for line in text.splitlines():
        while len(line) > size:
            out.append(line[:size])
            line = line[size:]
        if len(current) + len(line) + 1 > size:
            out.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        out.append(current)
    return out


def is_gm(member: discord.abc.User | discord.Member, state: GameState | None = None) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    role_ids = {r.id for r in member.roles}
    gm_role = (state.settings.gm_role_id if state is not None else None) or config.GM_ROLE_ID
    return gm_role is not None and gm_role in role_ids


def require_gm(interaction: discord.Interaction, state: GameState | None = None) -> None:
    if not is_gm(interaction.user, state):
        raise GameError("Only Game Masters can use this command.")
