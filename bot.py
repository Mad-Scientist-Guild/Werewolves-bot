import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path

import config
import Roles  # populates ROLE_REGISTRY by importing all role modules

intents = discord.Intents.default()
intents.message_content = True   # prefix commands need this
intents.members = True           # resolving/caching non-invoker members needs this

bot = commands.Bot(command_prefix="xpw ", intents=intents)

@bot.event
async def setup_hook():
    for file in Path("Cogs").rglob("*.py"):
        if file.name == "__init__.py":
            continue
        path = file.relative_to("Cogs")
        module_name = ".".join(["Cogs"] + list(path.with_suffix("").parts))
        try:
            await bot.load_extension(module_name)
            print(f"[Main] Loaded {module_name}")
        except Exception as e:
            print(f"[Main] Failed to load {module_name}: {e}")

    if config.ENV == "production":
        synced = await bot.tree.sync()
        print(f"[Main] Synced {len(synced)} commands globally")
    else:
        guild = discord.Object(id=int(config.GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"[Main] Synced {len(synced)} commands to guild {config.GUILD_ID}")


@bot.event
async def on_ready():
    print(f"[Main] Logged in as {bot.user}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    await interaction.response.send_message(f"Error: {error}", ephemeral=True)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    await ctx.send(f"Error: {error}", ephemeral=True)


@bot.command()
async def ping(ctx: commands.Context):
    if not (ctx.author.guild_permissions.administrator or await bot.is_owner(ctx.author)):
        await ctx.send(":x: You do not have permission to use this command", ephemeral=True)
        return
    await ctx.send("Pong!")


@bot.command(name="reload")
async def reload_module(ctx: commands.Context, name: str):
    if not await bot.is_owner(ctx.author):
        await ctx.send(":x: Only bot owner can reload modules", ephemeral=True)
        return
    try:
        await bot.reload_extension(name)
        await bot.tree.sync()
        await ctx.send(f":white_check_mark: Reloaded `{name}` successfully", ephemeral=True)
    except commands.ExtensionNotLoaded:
        await ctx.send(f":warning: Cog `{name}` is not loaded", ephemeral=True)
    except commands.ExtensionNotFound:
        await ctx.send(f":warning: Cog `{name}` not found", ephemeral=True)
    except Exception as e:
        await ctx.send(f":x: Error reloading `{name}`:\n```{e}```", ephemeral=True)


bot.run(config.TOKEN)