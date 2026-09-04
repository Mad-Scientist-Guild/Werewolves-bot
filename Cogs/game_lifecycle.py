from __future__ import annotations

from datetime import datetime, time

import discord
from discord import app_commands
from discord.ext import commands

from core import game as game_module
from core.game import GameError, GamePhase
from core.helpers import ack_silent, reply, send_announcement, send_mod_log, parse_time


class GameLifecycle(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    game_group = app_commands.Group(name="game", description="Manage the werewolf game")

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

    @game_group.command(name="join")
    async def join(self, interaction: discord.Interaction) -> None:
        game = game_module.get_game(interaction.guild_id)
        if game.started:
            raise GameError("The game has already started — you can't join. Contact your GM.")
        if game.get_player(interaction.user) is not None:
            raise GameError("You're already part of the game!")
        game.add_player(interaction.user)
        await send_mod_log(game, "PLAYER JOINED", f"{interaction.user.display_name} joined the game.")
        await reply(interaction, "You have joined the game!")

    @game_group.command(name="get_alive_players")
    async def get_alive_players(self, interaction: discord.Interaction) -> None:
        game = game_module.get_game(interaction.guild_id)
        if not game.started or game.finished:
            raise GameError("The game has not started yet, or has already finished.")
        names = "\n".join(f"- {p.member.display_name}" for p in game.alive_players)
        await reply(interaction, f"```Alive players:\n{names}\n```")

    @game_group.command(name="create")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        announcement_channel="Channel for public announcements",
        vote_channel="Channel for lynch votes",
        moderator_channel="Channel where mod-log messages go",
        dead_channel="Channel where the dead can talk",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        announcement_channel: discord.TextChannel,
        vote_channel: discord.TextChannel,
        moderator_channel: discord.TextChannel,
        dead_channel: discord.TextChannel,
    ) -> None:
        game = game_module.create_game(interaction.guild)  # raises GameAlreadyActive if one exists
        game.announcement_channel = announcement_channel
        game.vote_channel = vote_channel
        game.moderator_channel = moderator_channel
        game.dead_channel = dead_channel

        await send_mod_log(game, "GAME CREATED", "A new game has been created.")
        await send_announcement(game, "NEW GAME!", "A new game has started — join with **/game join**!")
        await ack_silent(interaction)

    @game_group.command(name="start_game")
    @app_commands.checks.has_permissions(administrator=True)
    async def start_game(self, interaction: discord.Interaction) -> None:
        game = game_module.get_game(interaction.guild_id)
        if game.started:
            raise GameError("Game has already started.")
        if not game.players:
            raise GameError("No players have joined yet.")

        game.started = True
        game.day_number = 1
        game.phase = GamePhase.DAY

        await send_mod_log(game, "STARTED", "The game has started.")
        await send_announcement(game, "GAME START!", "The game has started — have fun everyone!")
        await ack_silent(interaction)

    @game_group.command(name="finish_game")
    @app_commands.checks.has_permissions(administrator=True)
    async def finish_game(self, interaction: discord.Interaction) -> None:
        game = game_module.get_game(interaction.guild_id)
        if not game.started:
            raise GameError("Game has not been started yet.")
        await send_mod_log(game, "FINISHED", "The game has concluded.")
        game_module.end_game(interaction.guild_id)
        await ack_silent(interaction)

    @game_group.command(name="times")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(morning="HH:MM, 24-hour", night="HH:MM, 24-hour")
    async def times(self, interaction: discord.Interaction, morning: str, night: str) -> None:
        game = game_module.get_game(interaction.guild_id)
        game.morning_time = parse_time(morning)
        game.night_time = parse_time(night)
        await reply(interaction, "Set morning and night start times.")
        await send_mod_log(game, "TIMES", f"Morning: {morning}\nNight: {night}")

    @game_group.command(name="set_dead_channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_dead_channel(self, interaction: discord.Interaction, dead_channel: discord.TextChannel) -> None:
        game = game_module.get_game(interaction.guild_id)
        game.dead_channel = dead_channel
        await send_mod_log(game, "CHANGED DEAD CHANNEL", "Changed the dead channel.")
        await ack_silent(interaction)

    @game_group.command(name="reset")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset(self, interaction: discord.Interaction) -> None:
        game_module.end_game(interaction.guild_id)
        await reply(interaction, "Game has been reset!")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameLifecycle(bot))