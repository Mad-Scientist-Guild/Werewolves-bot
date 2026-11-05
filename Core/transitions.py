"""The daily transitions (morning, newspaper, dusk, second lynch end, night
lock) and the night resolution. The scheduler calls run_transition."""
from __future__ import annotations

import copy
from datetime import datetime

from Core import voting
from Core.access import publish_public_roles
from Core.clock import TransitionKind, next_transition
from Core.decisions import FlowResult
from Core.effects import Announcement, NewspaperPost, VoteResults
from Core.lynch import end_second_lynch, resolve_dusk
from Core.players import seed
from Core.resolution import Resolution
from Core.state import GameState, Phase


def run_transition(state: GameState, kind: TransitionKind, scheduled: datetime) -> FlowResult:
    result = FlowResult()
    handler = {
        TransitionKind.MORNING: _morning,
        TransitionKind.NEWSPAPER: _newspaper,
        TransitionKind.DUSK: _dusk,
        TransitionKind.SECOND_LYNCH_END: end_second_lynch,
        TransitionKind.NIGHT_LOCK: _night_lock,
    }[kind]
    state.log("PHASE", f"Transition: {kind.value} (day {state.day})")
    handler(state, result)
    state.next_transition = next_transition(state, scheduled)
    return result


def _expire_conditions(state: GameState, moment: str) -> None:
    for player in state.players.values():
        expired = [s for s in player.conditions if s.expires == moment]
        if expired:
            player.conditions = [s for s in player.conditions if s.expires != moment]
            state.log("CONDITION", f"{player.display_name}: expired {', '.join(s.key for s in expired)}",
                      actor=player.user_id)


def _morning(state: GameState, result: FlowResult) -> None:
    night = state.day
    result.add(f"Night {night} — final", resolve_night(state))
    voting.archive_ballot(state, voting.WOLVES)
    state.night_overrides.clear()

    state.day += 1
    state.phase = Phase.DAY
    _expire_conditions(state, f"morning:{state.day}")
    state.emit(Announcement(title=f"DAY {state.day}", text="The sun rises over XP. A new day begins."))


def _newspaper(state: GameState, result: FlowResult) -> None:
    changed = publish_public_roles(state)
    if changed:
        state.log("PUBLIC", "Public roles updated: " + ", ".join(
            f"{p.display_name} → {p.public_role.value}" for p in changed))
    url = state.settings.newspaper_url
    if url:
        state.emit(NewspaperPost(url=url))
        state.newspapers[state.day] = url
        state.settings.newspaper_url = None
    else:
        state.log("NEWSPAPER", f"No newspaper image was set for day {state.day}.", alert=True)
    state.newspaper_published_day = state.day
    if state.day >= 2:
        voting.open_ballot(state, voting.LYNCH)
        state.emit(Announcement(title="VOTING IS OPEN",
                                text="You can now vote to lynch someone with `/lynch vote` "
                                     f"(until {state.settings.schedule.dusk})."))


def _dusk(state: GameState, result: FlowResult) -> None:
    _expire_conditions(state, f"dusk:{state.day}")
    mayor_ballot = voting.close_ballot(state, voting.MAYOR)
    if mayor_ballot is not None:
        finish_mayor_election(state, mayor_ballot)
    resolve_dusk(state, result)
    state.phase = Phase.NIGHT
    voting.open_ballot(state, voting.WOLVES)
    seed(state, f"night:{state.day}")


def finish_mayor_election(state: GameState, ballot) -> None:
    tally = voting.tally_mayor(state, ballot)
    state.emit(VoteResults(title="Mayor votes", text=voting.published_votes(state, ballot)))
    if tally.outcome == "elected":
        state.mayor = tally.target
        state.emit(Announcement(title="A NEW MAYOR", text=f"**{state.name(tally.target)}** is the new Mayor!"))
        state.log("MAYOR", f"{state.name(tally.target)} was elected Mayor ({voting.describe_counts(state, tally)}).",
                  actor=tally.target)
    elif tally.outcome == "tie":
        state.emit(Announcement(title="MAYOR ELECTION", text="The mayor election is tied - the GMs will hold a re-vote."))
        state.log("MAYOR", f"Mayor election tied: {voting.describe_counts(state, tally)}", alert=True)
    else:
        state.log("MAYOR", "Nobody voted in the mayor election.", alert=True)
    voting.archive_ballot(state, voting.MAYOR)


def _night_lock(state: GameState, result: FlowResult) -> None:
    state.phase = Phase.SLEEP
    voting.close_ballot(state, voting.WOLVES)
    result.add(f"Night {state.day} — preview", preview_night(state))


def preview_night(state: GameState) -> str:
    """Resolve tonight on a copy, for the GM preview. Nothing is changed."""
    seed(state, f"night:{state.day}")
    shadow = copy.deepcopy(state)
    shadow.pending_logs = []
    shadow.pending_effects = []
    return resolve_night(shadow)


def resolve_night(state: GameState) -> str:
    night = state.day
    ctx = Resolution(state, kind="night", moment=state.moment("night", night), seed=seed(state, f"night:{night}"),
                     title=f"Night {night}")
    return ctx.run()
