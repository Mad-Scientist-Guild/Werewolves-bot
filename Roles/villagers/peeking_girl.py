from datetime import datetime, timedelta

from Core import realtime
from Core.resolution import register_prepare_hook
from Roles.role import *


@register_role
class PeekingGirl(Role):
    name = "peeking_girl"
    display = "Peeking Girl"
    faction = VILLAGERS
    tags = frozenset({"villager_role"})
    description = (
        "Once per day (midnight to midnight) you can pick a 60-minute window to listen in on the werewolves. From "
        "the moment a wolf talks during that window, you get the first 15 minutes of their chat as a transcript - "
        "speakers are numbered (the same number for the same wolf every time), names they mention stay visible. "
        "The time must be in the future. Spying counts as leaving your house that night."
    )
    abilities = (
        Ability(
            "peek", Timing.INSTANT, "Listen in on the werewolf chat for an hour",
            params=(P.time("start", "When your hour starts (HH:MM, 24-hour)"),), once_per_cycle=False,
        ),
    )

    peeked_dates: list[str] = field(default_factory=list)

    def _start(self, state: GameState, action: SubmittedAction) -> datetime:
        return realtime.next_occurrence(state, action.params["start"], datetime.fromisoformat(action.submitted_at))

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if "wolves" not in state.groups:
            raise GameError("There's no werewolf chat to listen in on.")
        start = self._start(state, action)
        if start.date().isoformat() in self.peeked_dates:
            raise GameError(f"You already listen in on {start:%A} - once per day (midnight to midnight).")

    def resolve_peek(self, ctx: Resolution, action: SubmittedAction) -> None:
        start = self._start(ctx.state, action)
        now = datetime.fromisoformat(action.submitted_at)
        end = start + timedelta(minutes=realtime.WINDOW_MINUTES)

        def commit() -> None:
            realtime.schedule_relay(ctx.state, self.owner, "wolves", start, purpose="peeking_girl", now=now)
            self.peeked_dates.append(start.date().isoformat())

        ctx.commit(commit)
        ctx.inform(self.owner, f"You'll be listening in on the werewolves from {start:%H:%M} to {end:%H:%M} "
                               f"({start:%A}). You'll get what you heard right after.")


@register_prepare_hook
def spying_leaves_the_house(ctx: Resolution) -> None:
    """Spying counts as leaving the house for the night the window belongs to -
    even when the window is during the day."""
    if ctx.kind != "night":
        return
    for relay in realtime.relays_for_night(ctx.state, ctx.state.day):
        if relay.purpose == "peeking_girl":
            ctx.visits.append(Visit(visitor=relay.listener, target=None, action_id=None, source="peeking_girl",
                                    ability="peek"))


class PeekingGirlCommands(RoleCommands, group_name="peeking_girl", source="peeking_girl"):
    @app_commands.command(name="peek", description="Listen in on the werewolf chat for an hour (once per day)")
    @app_commands.describe(start="When your hour starts, HH:MM (24-hour), in the future")
    async def peek(self, interaction: discord.Interaction, start: str) -> None:
        await self.use(interaction, "peek", start=start)
