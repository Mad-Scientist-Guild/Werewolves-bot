import discord
from discord import app_commands
from discord.ext import commands

from core import game as game_module
from core.game import GameError
from core.helpers import reply, set_channel_visible
from roles.role import ROLE_REGISTRY


class Roster(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    role_group = app_commands.Group(
        name="role",
        description="Manage role assignments",
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

    def _resolve_role_name(self, role_name: str) -> str:
        key = role_name.lower()
        if key not in ROLE_REGISTRY:
            raise GameError(f"'{role_name}' isn't a known role. Use /role get_all to see valid names.")
        return key

    @role_group.command(name="get_all")
    @app_commands.checks.has_permissions(administrator=True)
    async def get_all(self, interaction: discord.Interaction) -> None:
        names = "\n".join(sorted(ROLE_REGISTRY))
        await reply(interaction, f"**Roles:**\n{names}")

    @role_group.command(name="get")
    @app_commands.checks.has_permissions(administrator=True)
    async def get(self, interaction: discord.Interaction, role_name: str) -> None:
        game = game_module.get_game(interaction.guild_id)
        key = self._resolve_role_name(role_name)
        members = game.players_with_role(key)
        channel = game.role_channels.get(key)

        lines = [
            f"**Role:** {key}",
            f"**Channel:** {channel.mention if channel else '*not set*'}",
            f"**Members:** {', '.join(p.member.display_name for p in members) or '*none*'}",
        ]
        await reply(interaction, "\n".join(lines))

    @role_group.command(name="set_channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_channel(self, interaction: discord.Interaction, role_name: str, channel: discord.TextChannel) -> None:
        game = game_module.get_game(interaction.guild_id)
        key = self._resolve_role_name(role_name)
        game.role_channels[key] = channel
        await reply(interaction, f"Channel for **{key}** set to {channel.mention}.")

    @role_group.command(name="add_user")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_user(self, interaction: discord.Interaction, user: discord.Member, role_name: str) -> None:
        game = game_module.get_game(interaction.guild_id)
        key = self._resolve_role_name(role_name)
        player = game.get_player(user)
        if player is None:
            raise GameError("That person isn't part of this game.")
        if player.role is not None and player.role.name == key:
            raise GameError("This player already has that role.")

        if player.role is not None:
            old_channel = game.role_channels.get(player.role.name)
            if old_channel is not None:
                await set_channel_visible(user, old_channel, visible=False)

        player.set_role(ROLE_REGISTRY[key])

        new_channel = game.role_channels.get(key)
        if new_channel is not None:
            await set_channel_visible(user, new_channel, visible=True)

        await reply(interaction, f"{user.display_name} has been given the role {key}.")

    @role_group.command(name="remove_user")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_user(self, interaction: discord.Interaction, user: discord.Member, role_name: str) -> None:
        game = game_module.get_game(interaction.guild_id)
        key = self._resolve_role_name(role_name)
        player = game.get_player(user)
        if player is None or player.role is None or player.role.name != key:
            raise GameError("That player doesn't have that role.")

        player.role = None
        player.faction = None

        channel = game.role_channels.get(key)
        if channel is not None:
            await set_channel_visible(user, channel, visible=False)

        await reply(interaction, f"{user.display_name} has been removed from the role {key}.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Roster(bot))