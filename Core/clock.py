"""The real-time phase clock.

Each game stores its next transition (kind + scheduled time). After a
transition runs, the next one is computed from the *scheduled* time of the
previous one, so a bot that was offline catches up in order instead of
skipping anything.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from Core.state import GameState, Phase, Schedule, Transition


class TransitionKind(str, Enum):
    MORNING = "morning"                # 08:00 - apply the night, day begins
    NEWSPAPER = "newspaper"            # 12:00 - newspaper, public statuses, lynch opens
    DUSK = "dusk"                      # 19:00 - lynch closes, day actions resolve, night begins
    SECOND_LYNCH_END = "second_lynch_end"  # 20:00 - only when a second lynch is running
    NIGHT_LOCK = "night_lock"          # 00:00 - night actions lock, preview for the GMs


def parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def times(schedule: Schedule) -> dict[TransitionKind, time]:
    return {
        TransitionKind.MORNING: parse_hhmm(schedule.morning),
        TransitionKind.NEWSPAPER: parse_hhmm(schedule.newspaper),
        TransitionKind.DUSK: parse_hhmm(schedule.dusk),
        TransitionKind.SECOND_LYNCH_END: parse_hhmm(schedule.second_lynch_end),
        TransitionKind.NIGHT_LOCK: parse_hhmm(schedule.night_lock),
    }


def zone(state: GameState) -> ZoneInfo:
    return ZoneInfo(state.settings.schedule.timezone)


def allowed_next(state: GameState) -> set[TransitionKind]:
    """Transitions that can come next from the current phase."""
    if state.phase is Phase.DAY:
        kinds = {TransitionKind.DUSK}
        if state.data.get("newspaper_day") != state.day:
            kinds.add(TransitionKind.NEWSPAPER)
        return kinds
    if state.phase is Phase.NIGHT:
        kinds = {TransitionKind.NIGHT_LOCK}
        lynch2 = state.ballots.get("lynch2")
        if lynch2 is not None and lynch2.is_open:
            kinds.add(TransitionKind.SECOND_LYNCH_END)
        return kinds
    if state.phase is Phase.SLEEP:
        return {TransitionKind.MORNING}
    return set()


def next_transition(state: GameState, after: datetime) -> Transition | None:
    kinds = allowed_next(state)
    if not kinds:
        return None
    tz = zone(state)
    local = after.astimezone(tz)
    schedule = times(state.settings.schedule)
    best: tuple[datetime, TransitionKind] | None = None
    for offset in range(0, 3):
        day = local.date() + timedelta(days=offset)
        for kind in kinds:
            at = datetime.combine(day, schedule[kind], tzinfo=tz)
            if at > after and (best is None or at < best[0]):
                best = (at, kind)
    if best is None:
        return None
    return Transition(kind=best[1].value, at=best[0].isoformat())


def game_day_at(state: GameState, when: datetime, now: datetime) -> int:
    """The game day a moment belongs to: a day runs from one morning to the
    next, so 02:00 still belongs to the previous day (and its night)."""
    tz = zone(state)
    morning = times(state.settings.schedule)[TransitionKind.MORNING]
    mornings = 0
    day = now.astimezone(tz).date()
    end = when.astimezone(tz).date()
    while day <= end:
        at = datetime.combine(day, morning, tzinfo=tz)
        if now < at <= when:
            mornings += 1
        day += timedelta(days=1)
    return state.day + mornings


def transition_time(transition: Transition) -> datetime:
    return datetime.fromisoformat(transition.at)


def now_in(state: GameState) -> datetime:
    return datetime.now(zone(state))
