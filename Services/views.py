"""Persistent Discord components.

Decision prompts (e.g. the Mayor breaking a lynch tie) are select menus
whose custom_id carries the guild and decision id. They are registered as
dynamic items, so they keep working after a restart."""
from __future__ import annotations

import re

import discord

from Core import decisions
from Core.state import Decision, GameState
from Services.discord_utils import embed, is_gm
from Services.runtime import runtime


class DecisionSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"xpw:decision:(?P<guild>\d+):(?P<decision>\d+)"):
    def __init__(self, guild_id: int, decision_id: int, options: list[discord.SelectOption] | None = None):
        self.guild_id = guild_id
        self.decision_id = decision_id
        super().__init__(discord.ui.Select(
            custom_id=f"xpw:decision:{guild_id}:{decision_id}",
            placeholder="Make your choice…",
            options=options or [discord.SelectOption(label="…", value="0")],
        ))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Select,
                             match: re.Match[str], /) -> "DecisionSelect":
        return cls(int(match["guild"]), int(match["decision"]), list(item.options))

    async def callback(self, interaction: discord.Interaction) -> None:
        async def run() -> None:
            choice = int(self.item.values[0])
            handle = runtime.games.get(self.guild_id)
            decision = next((d for d in handle.state.decisions if d.id == self.decision_id), None)
            by_gm = (decision is not None and decision.chooser != interaction.user.id
                     and is_gm(interaction.user, handle.state))
            async with runtime.games.mutate(self.guild_id) as state:
                result = decisions.resolve_decision(state, self.decision_id, choice, by=interaction.user.id, by_gm=by_gm)
                for title, text in result.reports:
                    state.report(title, text)
                name = state.name(choice)
            await interaction.response.send_message(f"You chose **{name}**.", ephemeral=True)
        await _safe(interaction, run())


def decision_view(state: GameState, decision: Decision) -> discord.ui.View:
    options = [discord.SelectOption(label=state.name(o)[:100], value=str(o)) for o in decision.options[:25]]
    view = discord.ui.View(timeout=None)
    view.add_item(DecisionSelect(state.guild_id, decision.id, options))
    return view


def decision_embed(state: GameState, decision: Decision) -> discord.Embed:
    return embed("A decision is needed", decision.prompt, color_name="gold",
                 footer=f"Decision #{decision.id} — only {state.name(decision.chooser)} (or a GM) can choose")


async def _safe(interaction: discord.Interaction, coro) -> None:
    """Run a component callback; game errors become an ephemeral reply."""
    from Core.errors import GameError
    try:
        await coro
    except GameError as exc:
        if interaction.response.is_done():
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)


class AnswerButton(discord.ui.DynamicItem[discord.ui.Button],
                   template=r"xpw:question:(?P<guild>\d+):(?P<question>\d+):(?P<answer>yes|no)"):
    def __init__(self, guild_id: int, question_id: int, answer: str):
        self.guild_id, self.question_id, self.answer = guild_id, question_id, answer
        super().__init__(discord.ui.Button(
            label="Yes" if answer == "yes" else "No",
            style=discord.ButtonStyle.success if answer == "yes" else discord.ButtonStyle.danger,
            custom_id=f"xpw:question:{guild_id}:{question_id}:{answer}",
        ))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str], /) -> "AnswerButton":
        return cls(int(match["guild"]), int(match["question"]), match["answer"])

    async def callback(self, interaction: discord.Interaction) -> None:
        async def run() -> None:
            from Core import realtime
            async with runtime.games.mutate(self.guild_id) as state:
                question = realtime.answer_question(state, self.question_id, interaction.user.id, self.answer == "yes")
                closed = question.done
            text = "Your answer was recorded." + (" Everyone has answered - the Spiritualist gets the result now."
                                                 if closed else " You can change it until the question closes.")
            await interaction.response.send_message(text, ephemeral=True)
        await _safe(interaction, run())


def answer_view(guild_id: int, question_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(AnswerButton(guild_id, question_id, "yes"))
    view.add_item(AnswerButton(guild_id, question_id, "no"))
    return view


class TelepathReplyModal(discord.ui.Modal, title="Reply (max 20 words)"):
    text = discord.ui.TextInput(label="Your reply", style=discord.TextStyle.paragraph, max_length=300)

    def __init__(self, guild_id: int, telepath_message_id: int):
        super().__init__()
        self.guild_id, self.telepath_message_id = guild_id, telepath_message_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async def run() -> None:
            from Core import realtime
            from Core.clock import now_in
            async with runtime.games.mutate(self.guild_id) as state:
                realtime.reply_telepath_message(state, self.telepath_message_id, interaction.user.id, str(self.text.value),
                                         now_in(state))
            await interaction.response.send_message("Your reply is on its way.", ephemeral=True)
        await _safe(interaction, run())


class TelepathReplyButton(discord.ui.DynamicItem[discord.ui.Button],
                           template=r"xpw:telepath:(?P<guild>\d+):(?P<message>\d+)"):
    def __init__(self, guild_id: int, telepath_message_id: int):
        self.guild_id, self.telepath_message_id = guild_id, telepath_message_id
        super().__init__(discord.ui.Button(label="Reply", style=discord.ButtonStyle.primary,
                                           custom_id=f"xpw:telepath:{guild_id}:{telepath_message_id}"))

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button,
                             match: re.Match[str], /) -> "TelepathReplyButton":
        return cls(int(match["guild"]), int(match["message"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TelepathReplyModal(self.guild_id, self.telepath_message_id))


def telepath_view(guild_id: int, telepath_message_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(TelepathReplyButton(guild_id, telepath_message_id))
    return view


DYNAMIC_ITEMS = (DecisionSelect, AnswerButton, TelepathReplyButton)
