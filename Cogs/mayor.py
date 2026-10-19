"""/mayor - the mayor election (day 1) and the Mayor's successor."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from Core import voting
from Core.clock import now_in
from Core.errors import GameError
from Services.discord_utils import reply
from Services.runtime import runtime


class Mayor(commands.GroupCog, group_name="mayor", group_description="The Mayor"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="vote", description="Vote in the mayor election")
    async def vote(self, interaction: discord.Interaction, candidate: discord.Member) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            voting.cast_vote(state, voting.MAYOR, interaction.user.id, candidate.id, at=now_in(state).isoformat())
            state.log("MAYOR", f"{state.name(interaction.user.id)} votes for {state.name(candidate.id)} as Mayor",
                      actor=interaction.user.id, targets=[candidate.id])
        await reply(interaction, f"You voted for **{candidate.display_name}** as Mayor.")

    @app_commands.command(name="successor", description="(Mayor) Choose who becomes Mayor if you die")
    async def successor(self, interaction: discord.Interaction, player: discord.Member) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            if state.mayor != interaction.user.id:
                raise GameError("Only the Mayor can choose a successor.")
            successor = state.player(player.id)
            if not successor.alive:
                raise GameError(f"{successor.display_name} isn't alive.")
            if successor.user_id == interaction.user.id:
                raise GameError("You can't be your own successor.")
            state.mayor_successor = successor.user_id
            state.log("MAYOR", f"The Mayor chose {successor.display_name} as successor.", actor=interaction.user.id,
                      targets=[successor.user_id])
        await reply(interaction, f"**{player.display_name}** will become Mayor if you die. You can change this any time.")

    @app_commands.command(name="who", description="Who is the Mayor?")
    async def who(self, interaction: discord.Interaction) -> None:
        state = runtime.games.get(interaction.guild_id).state
        await reply(interaction, f"The Mayor is **{state.name(state.mayor)}**." if state.mayor else "There is no Mayor.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Mayor(bot))
