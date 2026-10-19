"""Runs each game's real-time transitions (morning, newspaper, dusk, second
lynch, night lock).

The next transition is stored in the game state. Every 30 seconds overdue
transitions are run, in order, each one snapshotted first. If the bot was
offline for longer than the catch-up limit, the clock pauses and the GMs
decide (`/gm clock resume` runs the missed transitions in order).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks

from Core import flow
from Core.clock import TransitionKind, now_in, transition_time
from Services.game_service import GameHandle
from Services.runtime import runtime

log = logging.getLogger("werewolves.scheduler")


def fmt_delta(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


class Scheduler(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tick.start()

    def cog_unload(self) -> None:
        self.tick.cancel()

    @tasks.loop(seconds=30)
    async def tick(self) -> None:
        for handle in runtime.games.all():
            try:
                await self._check(handle)
            except Exception as exc:
                log.exception("Scheduler failed for guild %s", handle.guild_id)
                await self._pause_after_error(handle, exc)

    async def _pause_after_error(self, handle: GameHandle, exc: Exception) -> None:
        """A transition that crashes was rolled back; pause instead of retrying
        every 30 seconds, and let the GMs look at it."""
        kind = handle.state.next_transition.kind if handle.state.next_transition else "?"
        try:
            async with runtime.games.mutate(handle.guild_id) as state:
                state.paused = True
                state.log("ERROR", f"The {kind} transition failed and was rolled back: {exc!r}. The clock is paused - "
                                   "fix the cause, then `/gm clock advance` or `/gm clock resume`.", alert=True)
        except Exception:
            log.exception("Could not pause guild %s after an error", handle.guild_id)

    @tick.before_loop
    async def before_tick(self) -> None:
        await self.bot.wait_until_ready()

    async def _check(self, handle: GameHandle) -> None:
        state = handle.state
        if not state.active or state.paused or state.next_transition is None:
            return
        at = transition_time(state.next_transition)
        now = now_in(state)
        if now < at:
            return
        kind = TransitionKind(state.next_transition.kind)
        late = now - at
        limit = timedelta(minutes=state.settings.schedule.catch_up_limit_minutes)
        if late > limit and not state.data.get("catch_up_approved"):
            async with runtime.games.mutate(handle.guild_id) as mutable:
                mutable.paused = True
                mutable.log("SCHEDULER", f"The bot missed the {kind.value} transition ({at:%a %H:%M}, "
                                         f"{fmt_delta(late)} ago). The clock is paused: use `/gm clock resume` to run the "
                                         "missed transitions in order, or `/gm clock reschedule` to skip ahead.", alert=True)
            return
        await self.run_transition(handle, kind, at, late=late)

    async def run_transition(self, handle: GameHandle, kind: TransitionKind, at: datetime, *,
                             late: timedelta | None = None, manual_by: discord.abc.User | None = None) -> None:
        night = handle.state.day
        preview = None
        if kind is TransitionKind.MORNING:
            preview = await runtime.db.latest_report(handle.game_id, f"Night {night} — preview")

        async with runtime.games.mutate(handle.guild_id, snapshot=f"before {kind.value} (day {handle.state.day})") as state:
            if manual_by is None and (state.next_transition is None or state.next_transition.kind != kind.value):
                return  # someone else already ran it
            result = flow.run_transition(state, kind, at)
            for title, text in result.reports:
                state.report(title, text)
            if late is not None and late > timedelta(minutes=2):
                state.log("SCHEDULER", f"{kind.value} ran {fmt_delta(late)} late.", alert=True)
            if manual_by is not None:
                state.log("GM", f"{manual_by.display_name} advanced the clock: {kind.value}.", actor=manual_by.id,
                          alert=True)
            if kind is TransitionKind.MORNING and result.reports:
                final = result.reports[0][1]
                if preview is None:
                    state.log("NIGHT", f"Night {night} was applied without an earlier preview.", alert=True)
                elif preview.body.strip() != final.strip():
                    state.log("NIGHT", f"The final result of night {night} differs from the last preview — "
                                       "check the final report.", alert=True)
            nt = state.next_transition
            if nt is not None and transition_time(nt) > now_in(state):
                state.data.pop("catch_up_approved", None)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Scheduler(bot))
