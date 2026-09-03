import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import game as game_module
from core.game import GameError, GamePhase
from core.helpers import ack_silent, reply, send_announcement, send_mod_log, _parse_time

class Lynch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    lynch_group = app_commands.Group(name="lynch", description="Manage the lynch")

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        # app_commands wraps exceptions raised inside a command in
        # CommandInvokeError — unwrap GameError so it reaches the user as a
        # clean message instead of a generic tree-level error.
        original = getattr(error, "original", error)
        if isinstance(original, GameError):
            await reply(interaction, str(original))
            return
        raise error

    @lynch_group.command(name="lynch_start_time")
    @app_commands.checks.has_permissions(administrator=True)
    async def lynch_start_time(self, interaction: discord.Interaction, time: str) -> None:
        game = game_module.get_game(interaction.guild_id)

        parsed_time = _parse_time(time)
        if parsed_time is None:
            raise GameError("Invalid time format. Please use HH:MM (24-hour format).")

        await game.lynch_start_time = parsed_time
        await reply(interaction, "Lynch start time set")

    @lynch_group.command(name="lynch_end_time")
    @app_commands.checks.has_permissions(administrator=True)
    async def lynch_end_time(self, interaction: discord.Interaction, time: str) -> None:
        game = game_module.get_game(interaction.guild_id)

        parsed_time = _parse_time(time)
        if parsed_time is None:
            raise GameError("Invalid time format. Please use HH:MM (24-hour format).")

        await game.lynch_end_time = parsed_time
        await reply(interaction, "Lynch end time set")

    @lynch_group.command(name="vote")
    async def vote(self, interaction: discord.Interaction, target: discord.Member) -> None:
        game = game_module.get_game(interaction.guild_id)
        if game.phase != GamePhase.DAY:
            raise GameError("You can only vote during the day phase.")
        player = game.get_player(interaction.user)
        if player is None:
            raise GameError("You're not part of the game!")
        target_player = game.get_player(target)

        if target_player is None:
            raise GameError("The target is not part of the game!")

        # Record the vote
        player.vote = target_player
        await send_mod_log(game, "VOTE CAST", f"{interaction.user.display_name} voted for {target.display_name}.")
        await reply(interaction, f"You have voted for {target.display_name}.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Lynch(bot))