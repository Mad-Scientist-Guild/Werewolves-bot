"""Commands for every player: /me, /role_info, /rules."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from Core import actions
from Core.actor import ROLE_REGISTRY
from Core.factions import faction_display
from Core.resolution import describe_action
from Core.state import ActionStatus
from Services.discord_utils import embed, reply
from Services.role_commands import COMMAND_GROUPS, ability_help, ability_line, role_autocomplete
from Services.runtime import runtime

RULES_TEXT = (
    "**General rules** (the full rules document has all the details)\n"
    "- Read the rules document carefully - this game is very different from the card game.\n"
    "- Videos, photos, memes, stickers and gifs are encouraged.\n"
    "- All conversations about the game happen in this server - no other groups, also not in real life.\n"
    "- Late actions may not happen (you can always try - the GMs might still have time).\n"
    "- Inactive for more than 48 hours? You may be fed to the wolves or replaced from the waiting list "
    "(you'll get a warning around 24 hours).\n"
    "- You may say or claim ANYTHING, but **screenshots as proof are forbidden**, as are screenshots of private chats.\n"
    "- Forwarding messages (including 'Copy Message Link') is not allowed. Replying and tagging is fine.\n"
    "- Deleting messages is not allowed; editing only for typos.\n"
    "- No roleplaying, and don't be a dick.\n"
    "- The Game Masters are always right - but you can always ask. Please re-read the manual before tagging a GM, "
    "and give context in the same message."
)


class Player(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="me", description="Your role, abilities and pending actions")
    async def me(self, interaction: discord.Interaction) -> None:
        state = runtime.games.get(interaction.guild_id).state
        player = state.player(interaction.user.id)
        role = player.role
        title = f"You are the {role.title()}" if role else "You don't have a role yet"
        e = embed(title, role.description if role else "", color_name="purple")
        if role is not None:
            e.add_field(name="Status", value=f"{player.life.value} · faction: {faction_display(player.true_faction())}",
                        inline=False)
        if player.modifiers:
            e.add_field(name="Also", value="\n".join(f"**{m.title()}** — {m.description}" for m in player.modifiers)[:1024],
                        inline=False)
        lines = []
        for actor, ability in actions.available(state, player):
            left = actor.uses_left(state, ability)
            lines.append(ability_line(ability, COMMAND_GROUPS.get(actor.command_source(ability.key)))
                         + (f" — {left} left" if left is not None else ""))
        if lines:
            e.add_field(name="Available now", value="\n".join(lines)[:1024], inline=False)
        pending = [a for a in state.actions if a.actor == player.user_id and a.status is ActionStatus.PENDING]
        if pending:
            e.add_field(name="Pending", value="\n".join(describe_action(state, a) for a in pending)[:1024], inline=False)
        await reply(interaction, "", embed_obj=e)

    @app_commands.command(name="role_info", description="Read the description of any role")
    @app_commands.autocomplete(role=role_autocomplete)
    async def role_info(self, interaction: discord.Interaction, role: str) -> None:
        cls = ROLE_REGISTRY.get(actions.normalise_role(role))
        e = embed(cls.title(), cls.description or "No description yet.", color_name="purple")
        e.add_field(name="Faction", value=faction_display(cls.faction))
        lines = ability_help(cls)
        if lines:
            e.add_field(name="Commands", value="\n".join(lines)[:1024], inline=False)
        await reply(interaction, "", embed_obj=e)

    @app_commands.command(name="rules", description="The general rules of XP Werewolves")
    async def rules(self, interaction: discord.Interaction) -> None:
        await reply(interaction, RULES_TEXT)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Player(bot))
