from __future__ import annotations

from datetime import datetime, time

import discord
from discord.ext import commands, tasks

from core import game as game_module
from core.game import Game, GamePhase
from core.helpers import apply_kill, send_announcement, send_mod_log, send_newspaper


def _matches(now: datetime, target: time | None) -> bool:
    return target is not None and now.hour == target.hour and now.minute == target.minute


class Scheduler(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tick.start()

    def cog_unload(self) -> None:
        self.tick.cancel()

    @tasks.loop(minutes=1)
    async def tick(self) -> None:
        now = datetime.now()
        for game in game_module.all_games():
            if not game.started or game.finished:
                continue

            if _matches(now, game.lynch_start_time):
                await self._start_lynch(game)
            if _matches(now, game.lynch_end_time):
                await self._end_lynch(game)
            if _matches(now, game.night_time):
                await self._start_night(game)
            if _matches(now, game.morning_time):
                await self._handle_morning(game)

    @tick.before_loop
    async def before_tick(self) -> None:
        await self.bot.wait_until_ready()

    # cogs/scheduler.py
    async def _start_lynch(self, game: Game) -> None:
        if game.day_number <= 1:
            return
        game.can_vote = True
        await send_announcement(game, "VOTE STARTED", "**You can now vote to lynch someone!**")

    async def _end_lynch(self, game: Game) -> None:
        if game.day_number <= 1:
            return
        winner, reason = game.resolve_lynch()

        if reason == "no_votes":
            await send_announcement(game, "Voting has concluded", "No one voted.")
        elif reason == "abstained":
            await send_announcement(game, "Voting has concluded", "Most people voted to Abstain")
        elif reason == "tie":
            await send_announcement(game, "Voting has concluded", "There is a **TIE**. No-one gets lynched")
        elif reason == "mayor_tiebreak":
            await send_announcement(
                game, "Voting has concluded",
                f"There was a TIE, but the Mayor has voted to lynch {winner.member.mention}",
            )
            await apply_kill(game, winner, cause="lynch")
        elif reason == "lynched":
            await send_announcement(
                game, "Voting has concluded",
                f"Most people voted to lynch {winner.member.mention}",
            )
            await apply_kill(game, winner, cause="lynch")

    async def _start_night(self, game: Game) -> None:
        game.phase = GamePhase.NIGHT
        await send_announcement(game, "NIGHT HAS FALLEN", "Night has begun — use your role's commands before dawn.")

    async def _handle_morning(self, game: Game) -> None:
        game.day_number += 1
        await send_mod_log(game, "New Day", f"Day {game.day_number} has started")

        await game.resolve_night()
        deaths = await game.resolve_pending_deaths()

        if not deaths:
            await send_mod_log(game, "NEW DAY, NO DEATH?", "It was awfully quiet tonight, nobody died!")
        else:
            lines = "\n".join(f"{p.member.mention} - killed by {cause}" for p, cause in deaths)
            await send_mod_log(game, "NEW DAY, NEW DEATH", f"Killed people:\n{lines}")

        await send_newspaper(game)
        game.phase = GamePhase.DAY


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Scheduler(bot))