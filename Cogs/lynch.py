"""/lynch - the daily lynch vote (and the Ruthless Counselor's second lynch).

Votes are private until voting closes; then the full list is published in
the announcements channel. Every vote is logged for the GMs straight away."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from Core import voting
from Core.clock import now_in
from Core.errors import GameError
from Core.state import GameState
from Services.discord_utils import reply
from Services.runtime import runtime


def current_lynch(state: GameState) -> str:
    second = state.ballots.get(voting.LYNCH2)
    if second is not None and second.is_open:
        return voting.LYNCH2
    first = state.ballots.get(voting.LYNCH)
    if first is not None and first.is_open:
        return voting.LYNCH
    if state.day <= 1:
        raise GameError("There is no lynch on the first day.")
    raise GameError(f"Voting isn't open right now (it opens at {state.settings.schedule.newspaper}).")


class Lynch(commands.GroupCog, group_name="lynch", group_description="Vote on who to lynch"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="vote", description="Vote to lynch a player (you can change your vote until voting closes)")
    async def vote(self, interaction: discord.Interaction, target: discord.Member) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            kind = current_lynch(state)
            previous = voting.cast_vote(state, kind, interaction.user.id, target.id, at=now_in(state).isoformat())
            change = f" (was: {state.name(previous) if previous else 'abstain'})" if previous is not None else ""
            state.log("LYNCH", f"{state.name(interaction.user.id)} votes for {state.name(target.id)}{change} "
                               f"[{voting.BALLOT_LABELS[kind]}]", actor=interaction.user.id, targets=[target.id])
        await reply(interaction, f"Your vote for **{target.display_name}** is in. Votes are published when voting closes.")

    @app_commands.command(name="abstain", description="Vote to lynch nobody today")
    async def abstain(self, interaction: discord.Interaction) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            kind = current_lynch(state)
            voting.cast_vote(state, kind, interaction.user.id, None, at=now_in(state).isoformat())
            state.log("LYNCH", f"{state.name(interaction.user.id)} abstains [{voting.BALLOT_LABELS[kind]}]",
                      actor=interaction.user.id)
        await reply(interaction, "You abstained.")

    @app_commands.command(name="retract", description="Take back your vote")
    async def retract(self, interaction: discord.Interaction) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            kind = current_lynch(state)
            voting.retract_vote(state, kind, interaction.user.id)
            state.log("LYNCH", f"{state.name(interaction.user.id)} retracts their vote", actor=interaction.user.id)
        await reply(interaction, "Your vote was retracted.")

    @app_commands.command(name="my_vote", description="See your current vote")
    async def my_vote(self, interaction: discord.Interaction) -> None:
        state = runtime.games.get(interaction.guild_id).state
        ballot = state.ballots.get(current_lynch(state))
        if interaction.user.id not in ballot.votes:
            await reply(interaction, "You haven't voted yet.")
            return
        target = ballot.votes[interaction.user.id]
        await reply(interaction, f"You voted for **{state.name(target)}**." if target else "You abstained.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Lynch(bot))
