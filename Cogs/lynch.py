import discord
from discord import app_commands
from discord.ext import commands

from Core import game as game_module
from Core.game import GameError
from Core.helpers import parse_time, reply, send_mod_log, send_to_channel


class Lynch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    lynch_group = app_commands.Group(name="lynch", description="Manage the lynch")

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, GameError):
            await reply(interaction, str(original))
            return
        raise error

    @lynch_group.command(name="lynch_start_time")
    @app_commands.checks.has_permissions(administrator=True)
    async def lynch_start_time(self, interaction: discord.Interaction, time: str) -> None:
        game = game_module.get_game(interaction.guild_id)
        game.lynch_start_time = parse_time(time)
        await reply(interaction, "Lynch start time set")

    @lynch_group.command(name="lynch_end_time")
    @app_commands.checks.has_permissions(administrator=True)
    async def lynch_end_time(self, interaction: discord.Interaction, time: str) -> None:
        game = game_module.get_game(interaction.guild_id)
        game.lynch_end_time = parse_time(time)
        await reply(interaction, "Lynch end time set")

    @lynch_group.command(name="vote")
    async def vote(self, interaction: discord.Interaction, player: discord.Member) -> None:
        game = game_module.get_game(interaction.guild_id)
        voter = game.get_player(interaction.user)
        if voter is None:
            raise GameError("You're not part of this game.")
        target = game.get_player(player)
        if target is None:
            raise GameError("That person isn't part of this game.")

        game.cast_vote(voter, target)
        await send_to_channel(
            game.vote_channel,
            "LYNCH VOTE",
            f"**{voter.member.display_name}** has voted on **{target.member.display_name}** to lynch",
        )
        await reply(interaction, f"You voted for {target.member.display_name}.")

    @lynch_group.command(name="vote_abstain")
    async def vote_abstain(self, interaction: discord.Interaction) -> None:
        game = game_module.get_game(interaction.guild_id)
        voter = game.get_player(interaction.user)
        if voter is None:
            raise GameError("You're not part of this game.")

        game.cast_vote(voter, None)
        await send_to_channel(game.vote_channel, "LYNCH VOTE", f"**{voter.member.display_name}** has abstained from voting")
        await reply(interaction, "You abstained from voting.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Lynch(bot))