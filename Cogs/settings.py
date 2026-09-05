import discord
from discord import app_commands
from discord.ext import commands

from Core import game as game_module
from Core.game import GameError
from Core.helpers import reply

RULES_TEXT = (
    "**General rules**\n"
    "- Use of video's, photos, memes, stickers and gifs is encouraged.\n"
    "- This document explains how the game works. Read this carefully before you start the game, "
    "the game is very different from how it is played in real life.\n"
    "- A special discord server has been created with different channels to have conversations and discussions.\n"
    "- If you are late with reporting an action, you may no longer be able to take that action "
    "(you can always try though, the game masters might still have time)\n"
    "- If there are any questions, you can ask the game master(s) anything anytime.\n"
    "- If you are inactive for more than 48 hours (without warning us) it is possible for you to get eliminated automatically.\n"
    "- Everyone gets a personal chatroom with the gamemasters to communicate with them, ask questions, use your powers, and/or vote people out.\n"
    "- You are allowed to say or claim ANYTHING regarding the game (also roles).\n"
    "- At any time you can ping the gamemaster(s) for clarification or validation\n"
    "- Screenshots from private chats are also forbidden to be send to other players.\n\n"
    "**Play etiquette**\n"
    "We've put together a few rules to keep the game fun, exciting, and interesting, no matter your role or faction. "
    "Please try to adhere to these, if anyone cheats it could ruin the game for everyone:\n"
    "- All conversations about the game must be held in the specified discord server. "
    "Other conversations/groups of and about the game may NOT be held.\n"
    "- Sending screenshots of conversations other than the general conversation channel is prohibited. "
    "Especially (private) contact with the organizers\n"
    "- It is possible that the gamemaster(s) finds out that a role is incredibly unbalanced, "
    "in which case the rules of this role may be (slightly) adjusted.\n"
    "- Don't be an assh*le (general XP code of conduct rules apply)"
)


class Settings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    set_group = app_commands.Group(
        name="set",
        description="Configure game settings",
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

    @set_group.command(name="newspaper")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(imagelink="URL of the newspaper image")
    async def newspaper(self, interaction: discord.Interaction, imagelink: str) -> None:
        game = game_module.get_game(interaction.guild_id)
        game.newspaper_url = imagelink
        await reply(interaction, "Image has been set")

    @app_commands.command(name="rules")
    async def rules(self, interaction: discord.Interaction) -> None:
        await reply(interaction, RULES_TEXT)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Settings(bot))