import discord
from discord import app_commands
from discord.ext import commands

from core import game as game_module
from core.game import GameError
from core.helpers import ack_silent, apply_kill, apply_revive, reply, send_mod_log
from core.models import Player


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    admin_group = app_commands.Group(
        name="admin",
        description="Admin overrides for the game",
        default_permissions=discord.Permissions(administrator=True),
    )

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, GameError):
            await reply(interaction, str(original))
            return
        raise error

    def _resolve(self, game: game_module.Game, member: discord.Member) -> Player:
        player = game.get_player(member)
        if player is None:
            raise GameError("That person isn't part of this game.")
        return player

    @admin_group.command(name="kill")
    @app_commands.checks.has_permissions(administrator=True)
    async def kill(self, interaction: discord.Interaction, target: discord.Member) -> None:
        game = game_module.get_game(interaction.guild_id)
        player = self._resolve(game, target)
        if not player.alive:
            raise GameError("That player is already dead.")
        await apply_kill(game, player, cause="admin_kill")
        await ack_silent(interaction)

    @admin_group.command(name="kill_overnight")
    @app_commands.checks.has_permissions(administrator=True)
    async def kill_overnight(self, interaction: discord.Interaction, target: discord.Member, cause: str) -> None:
        game = game_module.get_game(interaction.guild_id)
        player = self._resolve(game, target)
        if not player.alive:
            raise GameError("That player is already dead.")
        game.queue_night_kill(player, cause=cause)
        await send_mod_log(game, "KILLING OVERNIGHT", f"A GM has decided to kill {target.display_name} overnight.")
        await ack_silent(interaction)

    @admin_group.command(name="revive")
    @app_commands.checks.has_permissions(administrator=True)
    async def revive(self, interaction: discord.Interaction, target: discord.Member) -> None:
        game = game_module.get_game(interaction.guild_id)
        player = self._resolve(game, target)
        if player.alive:
            raise GameError("That player is already alive.")
        await apply_revive(game, player)
        await ack_silent(interaction)

    @admin_group.command(name="force_join")
    @app_commands.checks.has_permissions(administrator=True)
    async def force_join(self, interaction: discord.Interaction, target: discord.Member) -> None:
        game = game_module.get_game(interaction.guild_id)
        if game.started:
            raise GameError("The game has already started.")
        if game.get_player(target) is not None:
            raise GameError("This player has already joined.")
        game.add_player(target)
        await send_mod_log(game, "PLAYER JOINED!", f"**{target.display_name}** joined the game.")
        await reply(interaction, "You have put the player into the game!")

    @admin_group.command(name="get_joined")
    @app_commands.checks.has_permissions(administrator=True)
    async def get_joined(self, interaction: discord.Interaction) -> None:
        game = game_module.get_game(interaction.guild_id)
        if not game.players:
            raise GameError("No players have joined yet.")
        names = "\n".join(p.member.display_name for p in game.players.values())
        await reply(interaction, f"**Joined Players:**\n{names}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))