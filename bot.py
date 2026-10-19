"""XP Werewolves Discord bot - entry point.

Startup order: logging -> database -> load saved games -> role plug-ins and
their commands -> cogs -> command sync. After login every game is
re-synced (missing channels, permissions, undelivered effects) and the
scheduler catches up on missed transitions.
"""
from __future__ import annotations

import logging
import logging.handlers
import traceback
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

import config
from Core.errors import GameError
from Services.audit import AuditPoster
from Services.channels import ChannelManager
from Services.discord_utils import reply
from Services.effects import EffectDelivery
from Services.game_service import GameService
from Services.runtime import runtime
from Services.views import DYNAMIC_ITEMS
from Services.worker import GameWorker
from Storage.db import Database

log = logging.getLogger("werewolves")


def setup_logging() -> None:
    Path(config.LOG_DIR).mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(
        Path(config.LOG_DIR) / "bot.log", maxBytes=5_000_000, backupCount=10, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)
    logging.getLogger("discord.http").setLevel(logging.WARNING)


def describe_args(interaction: discord.Interaction) -> str:
    parts = []
    for name, value in interaction.namespace:
        if isinstance(value, (discord.Member, discord.User, discord.Role)):
            value = getattr(value, "display_name", None) or value.name
        elif isinstance(value, (discord.TextChannel, discord.CategoryChannel)):
            value = f"#{value.name}"
        elif isinstance(value, app_commands.Choice):
            value = value.value
        parts.append(f"{name}={value}")
    return " ".join(parts)


class WerewolvesBot(commands.Bot):
    async def setup_hook(self) -> None:
        db = Database(config.DB_PATH)
        await db.connect()
        games = GameService(db)
        audit = AuditPoster(self, db, games)
        channels = ChannelManager(self, games, db)
        delivery = EffectDelivery(self, games, db, channels)
        worker = GameWorker(self, games, delivery, channels, audit)
        games.listeners.append(worker.wake)

        runtime.bot, runtime.db, runtime.games = self, db, games
        runtime.audit, runtime.channels, runtime.delivery, runtime.worker = audit, channels, delivery, worker

        await games.load_all()

        import Roles  # noqa: F401 - registers every role and defines its command cog
        from Services.role_commands import COMMAND_COGS
        for cog_cls in COMMAND_COGS:
            await self.add_cog(cog_cls(self))
        log.info("Loaded %d role command groups", len(COMMAND_COGS))

        for file in sorted(Path("Cogs").glob("*.py")):
            if file.name.startswith("_"):
                continue
            module = f"Cogs.{file.stem}"
            try:
                await self.load_extension(module)
                log.info("Loaded %s", module)
            except Exception:
                log.exception("Failed to load %s", module)

        self.add_dynamic_items(*DYNAMIC_ITEMS)   # persistent buttons/menus keep working after a restart
        self.tree.on_error = self.on_tree_error

        if config.ENV == "production" or not config.GUILD_ID:
            synced = await self.tree.sync()
            log.info("Synced %d commands globally", len(synced))
        else:
            guild = discord.Object(id=int(config.GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to guild %s", len(synced), config.GUILD_ID)

        audit.start()

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)
        for handle in runtime.games.all():
            runtime.worker.wake(handle)   # re-sync channels and deliver anything left in the outbox

    async def _log_command(self, interaction: discord.Interaction, name: str, category: str, suffix: str) -> None:
        if interaction.guild_id is None:
            return
        handle = runtime.games.find(interaction.guild_id)
        state = handle.state if handle else None
        await runtime.db.add_event(
            guild_id=interaction.guild_id, game_id=handle.game_id if handle else None, category=category,
            message=f"{interaction.user.display_name} used `/{name}` {describe_args(interaction)}{suffix}".strip(),
            day=state.day if state else None, phase=state.phase.value if state else None, actor=interaction.user.id,
        )
        runtime.audit.wake()

    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        name = interaction.command.qualified_name if interaction.command else "?"
        if isinstance(original, GameError):
            await reply(interaction, f"❌ {original}")
            await self._log_command(interaction, name, "REJECTED", f" → {original}")
            return
        if isinstance(error, app_commands.CheckFailure):
            if not interaction.response.is_done():
                await reply(interaction, "❌ You can't use this command.")
            await self._log_command(interaction, name, "REJECTED", " → not allowed")
            return
        log.error("Command /%s failed:\n%s", name, "".join(traceback.format_exception(original)))
        await self._log_command(interaction, name, "ERROR", f" → crashed: {original!r} (see bot log)")
        if interaction.guild_id is not None:
            handle = runtime.games.find(interaction.guild_id)
            await runtime.db.add_event(guild_id=interaction.guild_id, game_id=handle.game_id if handle else None,
                                       category="ERROR", alert=True,
                                       message=f"`/{name}` by {interaction.user.display_name} crashed: {original!r}")
        try:
            await reply(interaction, "❌ Something went wrong. The GMs have been notified.")
        except discord.HTTPException:
            pass


def main() -> None:
    if not config.TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set (see .env.example)")
    setup_logging()
    intents = discord.Intents.default()
    intents.message_content = True   # activity tracking and prefix commands
    intents.members = True           # resolving members for permissions and roles
    bot = WerewolvesBot(command_prefix="xpw ", intents=intents)

    @bot.command()
    async def ping(ctx: commands.Context) -> None:
        await ctx.send("Pong!")

    bot.run(config.TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
