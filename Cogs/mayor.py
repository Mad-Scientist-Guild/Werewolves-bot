import discord
from discord import app_commands
from discord.ext import commands

from Core import game as game_module
from Core.game import GameError
from Core.helpers import reply, send_announcement, send_mod_log, send_to_channel, voted_for_preset


class Mayor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    mayor_group = app_commands.Group(name="mayor", description="Manage the mayor election")

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, GameError):
            await reply(interaction, str(original))
            return
        raise error

    @mayor_group.command(name="start_vote")
    @app_commands.checks.has_permissions(administrator=True)
    async def start_vote(self, interaction: discord.Interaction) -> None:
        game = game_module.get_game(interaction.guild_id)
        game.start_mayor_vote()
        await send_announcement(game, "VOTE FOR MAYOR HAS STARTED!", "The mayor vote has started!")
        await reply(interaction, "Started mayor vote.")

    @mayor_group.command(name="vote")
    async def vote(self, interaction: discord.Interaction, player: discord.Member) -> None:
        game = game_module.get_game(interaction.guild_id)
        voter = game.get_player(interaction.user)
        if voter is None:
            raise GameError("You're not part of this game.")
        target = game.get_player(player)
        if target is None:
            raise GameError("That person isn't part of this game.")

        game.cast_mayor_vote(voter, target)
        await send_to_channel(game.vote_channel, "MAYOR VOTE", voted_for_preset(voter, target))
        await reply(interaction, "You voted.")

    @mayor_group.command(name="end_vote")
    @app_commands.checks.has_permissions(administrator=True)
    async def end_vote(self, interaction: discord.Interaction) -> None:
        game = game_module.get_game(interaction.guild_id)
        winner, tied = game.end_mayor_vote()

        if winner is None and not tied:
            await reply(interaction, "No one was voted on.")
            return
        if tied:
            await send_announcement(game, "VOTE FOR MAYOR HAS ENDED!", "Due to a tie, the vote has to happen again!")
        else:
            await send_announcement(game, "VOTE FOR MAYOR HAS ENDED!", f"{winner.member.mention} is the new Mayor!")
        await reply(interaction, "Vote ended.")

    @mayor_group.command(name="successor")
    async def successor(self, interaction: discord.Interaction, player: discord.Member) -> None:
        game = game_module.get_game(interaction.guild_id)
        voter = game.get_player(interaction.user)
        if voter is None or game.mayor is not voter:
            raise GameError("You are not the mayor and cannot use this command.")
        successor = game.get_player(player)
        if successor is None:
            raise GameError("That person isn't part of this game.")

        game.mayor_successor = successor
        await send_mod_log(game, "SUCCESSOR CHOSEN", f"The mayor has chosen **{successor.member.display_name}** as their successor.")
        await reply(interaction, f"You set **{successor.member.display_name}** as your successor.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Mayor(bot))