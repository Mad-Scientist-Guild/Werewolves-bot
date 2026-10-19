"""/game - creating, joining and starting a game, and public game info."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from Core import flow
from Core.clock import now_in, transition_time
from Core.errors import GameError
from Core.state import Phase, PublicStatus
from Services.discord_utils import embed, reply, require_gm
from Services.runtime import runtime

STATUS_LABELS = {
    PublicStatus.NONE: "alive",
    PublicStatus.DEAD: "dead",
    PublicStatus.VENGEFUL_SPIRIT: "vengeful spirit",
    PublicStatus.SKELETON: "skeleton",
}


class Game(commands.GroupCog, group_name="game", group_description="The werewolves game"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="create", description="(GM) Create a new game in this server")
    @app_commands.describe(announcements="Existing announcements channel (optional - created if empty)",
                           votes="Existing vote results channel (optional)",
                           mod_log="Existing GM moderation channel (optional)")
    async def create(self, interaction: discord.Interaction, announcements: discord.TextChannel | None = None,
                     votes: discord.TextChannel | None = None, mod_log: discord.TextChannel | None = None) -> None:
        require_gm(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        handle = await runtime.games.create(interaction.guild_id)
        async with runtime.games.mutate(interaction.guild_id) as state:
            state.log("GAME", f"Game #{state.game_id} created by {interaction.user.display_name}.", actor=interaction.user.id)
        done = await runtime.channels.setup_base(interaction.guild, handle, announcements=announcements,
                                                 votes=votes, mod_log=mod_log)
        async with runtime.games.mutate(interaction.guild_id) as state:
            from Core.effects import Announcement
            state.emit(Announcement(title="A NEW GAME OF XP WEREWOLVES",
                                    text="A new game is being prepared - join with `/game join`!"))
        await reply(interaction, "Game created. " + (", ".join(done) if done else "") +
                    "\nNext: players `/game join`, then `/setup roles_add`, `/setup families`, `/setup assign`, "
                    "`/setup channels` and finally `/game start`.")

    @app_commands.command(name="join", description="Join the upcoming game")
    async def join(self, interaction: discord.Interaction) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            flow.add_player(state, interaction.user.id, interaction.user.display_name)
            count = len(state.players)
        await reply(interaction, f"You joined the game! ({count} players so far)")

    @app_commands.command(name="leave", description="Leave the game before it starts")
    async def leave(self, interaction: discord.Interaction) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            flow.remove_player(state, interaction.user.id)
        await reply(interaction, "You left the game.")

    @app_commands.command(name="players", description="List the players and what is publicly known about them")
    async def players(self, interaction: discord.Interaction) -> None:
        state = runtime.games.get(interaction.guild_id).state
        if not state.players:
            raise GameError("Nobody has joined yet.")
        lines = []
        for player in sorted(state.players.values(), key=lambda p: p.display_name.lower()):
            status = STATUS_LABELS[player.public_status] if state.phase is not Phase.SETUP else "joined"
            mayor = " 🎩 Mayor" if state.mayor == player.user_id else ""
            lines.append(f"**{player.display_name}** — {status}{mayor}")
        await reply(interaction, "", embed_obj=embed(f"Players ({len(state.players)})", "\n".join(lines)))

    @app_commands.command(name="status", description="Current phase, day and what happens next")
    async def status(self, interaction: discord.Interaction) -> None:
        state = runtime.games.get(interaction.guild_id).state
        lines = [f"**Phase:** {state.phase.value}", f"**Day:** {state.day}"]
        if state.next_transition is not None:
            at = transition_time(state.next_transition).astimezone(now_in(state).tzinfo)
            lines.append(f"**Next:** {state.next_transition.kind.replace('_', ' ')} at {at:%a %H:%M}")
        if state.paused:
            lines.append("⏸️ The game clock is paused by the GMs.")
        if state.mayor:
            lines.append(f"**Mayor:** {state.name(state.mayor)}")
        if state.lockdown:
            lines.append("🔒 Lockdown: a second lynch is in progress.")
        await reply(interaction, "\n".join(lines))

    @app_commands.command(name="start", description="(GM) Start the game: create missing channels and begin day 1")
    async def start(self, interaction: discord.Interaction) -> None:
        handle = runtime.games.get(interaction.guild_id)
        require_gm(interaction, handle.state)
        if handle.state.phase is not Phase.SETUP:
            raise GameError("The game has already started.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with runtime.games.mutate(interaction.guild_id) as state:
            missing = [p.display_name for p in state.players.values() if p.role is None]
            if missing:
                raise GameError(f"These players have no role yet: {', '.join(missing)}")
            flow.ensure_base_groups(state)
        await runtime.channels.setup_base(interaction.guild, handle)
        await runtime.channels.ensure_group_channels(interaction.guild, handle)
        async with runtime.games.mutate(interaction.guild_id, snapshot="before game start") as state:
            flow.start_game(state, now_in(state))
        await reply(interaction, "The game has started! Role cards are being posted in the private channels.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Game(bot))
