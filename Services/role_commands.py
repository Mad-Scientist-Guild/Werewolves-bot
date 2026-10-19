"""Base class for a role's slash-command group.

    class SeerCommands(RoleCommands, group_name="seer", source="seer"):
        @app_commands.command(name="check", description="Learn a player's faction tonight")
        async def check(self, interaction: discord.Interaction, target: discord.Member):
            await self.use(interaction, "check", target=target)

`use()` does all the shared work: finds the player, checks the ability is
available to them right now (role, copied role, modifier...), validates
phase/targets/uses, stores the action, saves, logs and replies. Every
subclass is collected in COMMAND_COGS and added to the bot automatically.
"""
from __future__ import annotations

from typing import Any, ClassVar

import discord
from discord import app_commands
from discord.ext import commands

from Core import actions
from Core.abilities import Timing
from Core.actor import ROLE_REGISTRY
from Core.clock import now_in
from Core.resolution import describe_action
from Core.state import GameState, Phase, SubmittedAction
from Services.discord_utils import reply
from Services.runtime import runtime

COMMAND_COGS: list[type["RoleCommands"]] = []
COMMAND_GROUPS: dict[str, str] = {}   # actor (role/modifier) name -> slash command group


class RoleCommands(commands.GroupCog):
    source: ClassVar[str]

    def __init_subclass__(cls, source: str | None = None, abstract: bool = False, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if abstract:   # a shared base with commands for several roles (e.g. the coven's /find)
            return
        group = str(cls.__cog_group_name__)
        cls.source = group.replace("-", "_") if source is None else source
        if cls not in COMMAND_COGS:
            COMMAND_COGS.append(cls)
        COMMAND_GROUPS.setdefault(cls.source, group)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    async def use(self, interaction: discord.Interaction, ability: str, **params: Any) -> SubmittedAction:
        clean = {key: _plain(value) for key, value in params.items() if value is not None}
        async with runtime.games.mutate(interaction.guild_id) as state:
            action = actions.submit(state, interaction.user.id, ability, clean, now=now_in(state),
                                    source=self.source or None)
            if state.phase is Phase.SLEEP and action.slot == state.slot("night"):
                refresh_preview(state, f"{state.name(action.actor)} submitted during sleep time")
            text = confirmation(state, action)
        await reply(interaction, text)
        return action

    async def cancel(self, interaction: discord.Interaction, ability: str) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            action = actions.cancel(state, interaction.user.id, ability, source=self.source or None)
        await reply(interaction, f"Cancelled: {action.ability}.")


def _plain(value: Any) -> Any:
    if isinstance(value, (discord.Member, discord.User)):
        return value.id
    if isinstance(value, app_commands.Choice):
        return value.value
    return value


def confirmation(state: GameState, action: SubmittedAction) -> str:
    what = describe_action(state, action)
    schedule = state.settings.schedule
    if action.slot == "instant":
        return f"✅ Done: {what}"
    if action.slot.startswith("dusk"):
        when = f"This takes effect at {schedule.dusk}. You can change it until then."
    elif state.phase is Phase.SLEEP:
        when = f"It's sleep time - this resolves at {schedule.morning}."
    else:
        when = (f"This is locked in at {schedule.night_lock} and takes effect at {schedule.morning}. "
                "You can change it until the lock.")
    return f"✅ Submitted: {what}\n{when}"


def refresh_preview(state: GameState, reason: str) -> None:
    """Re-run the night preview after something changed during sleep time."""
    from Core.flow import preview_night
    outcome = preview_night(state)
    state.report(f"Night {state.day} — preview (updated: {reason})", outcome.report)


async def role_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    current = current.lower().replace(" ", "_")
    names = sorted(n for n in ROLE_REGISTRY if current in n)
    return [app_commands.Choice(name=ROLE_REGISTRY[n].title(), value=n) for n in names[:25]]


TIMING_LABELS = {
    Timing.NIGHT: "night action",
    Timing.DAY: "day action",
    Timing.ANYTIME: "any time",
    Timing.INSTANT: "instant",
}


def ability_line(ability, group: str | None) -> str:
    uses = f", {ability.uses}× per game" if ability.uses else ""
    params = " ".join(f"<{p.name}>" if p.required else f"[{p.name}]" for p in ability.params)
    command = f"`/{group} {ability.key}{(' ' + params) if params else ''}`" if group else f"**{ability.key}**"
    return f"{command} — {ability.description} *({TIMING_LABELS[ability.timing]}{uses})*"


def ability_help(actor_cls: type, *, group: str | None = None) -> list[str]:
    """One line per ability, for role cards and generated docs."""
    group = group or COMMAND_GROUPS.get(actor_cls.name)
    return [ability_line(ability, group) for ability in actor_cls.abilities]
