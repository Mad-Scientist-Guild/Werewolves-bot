"""Ballots: the daily lynch, the Ruthless Counselor's second lynch, the
mayor election and the werewolf pack's nightly vote. Pure state, no I/O."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from Core.errors import GameError
from Core.state import Ballot, GameState, Player, VoteRecord

LYNCH = "lynch"
LYNCH2 = "lynch2"
MAYOR = "mayor"
WOLVES = "wolves"

BALLOT_LABELS = {
    LYNCH: "lynch vote",
    LYNCH2: "second lynch vote",
    MAYOR: "mayor election",
    WOLVES: "werewolf vote",
}


def open_ballot(state: GameState, kind: str, *, allow_abstain: bool = True) -> Ballot:
    existing = state.ballots.get(kind)
    if existing is not None and existing.is_open:
        return existing
    if existing is not None:
        state.ballot_archive.append(existing)
    ballot = Ballot(kind=kind, day=state.day, allow_abstain=allow_abstain)
    state.ballots[kind] = ballot
    state.log("BALLOT", f"The {BALLOT_LABELS.get(kind, kind)} opened (day {state.day}).")
    return ballot


def open_ballot_of(state: GameState, kind: str) -> Ballot:
    ballot = state.ballots.get(kind)
    if ballot is None or not ballot.is_open:
        raise GameError(f"The {BALLOT_LABELS.get(kind, kind)} isn't open right now.")
    return ballot


def close_ballot(state: GameState, kind: str) -> Ballot | None:
    ballot = state.ballots.get(kind)
    if ballot is None or not ballot.is_open:
        return None
    ballot.is_open = False
    state.log("BALLOT", f"The {BALLOT_LABELS.get(kind, kind)} closed.")
    return ballot


def archive_ballot(state: GameState, kind: str) -> None:
    ballot = state.ballots.pop(kind, None)
    if ballot is not None:
        ballot.is_open = False
        state.ballot_archive.append(ballot)


def eligible_voters(state: GameState, kind: str) -> list[Player]:
    alive = state.alive_players()  # skeletons and the dead can't vote
    if kind == WOLVES:
        return [p for p in alive if p.can_vote_wolf_kill()]
    return alive


def cast_vote(state: GameState, kind: str, voter_id: int, target_id: int | None, *, at: str,
              shown_as: int | None = None) -> int | None:
    """Records a vote and returns the voter's previous choice (or None).
    target_id None = abstain."""
    ballot = open_ballot_of(state, kind)
    voter = state.player(voter_id)
    if voter not in eligible_voters(state, kind):
        if not voter.alive:
            raise GameError("Only living players can vote.")
        raise GameError("You can't take part in this vote.")
    if target_id is None:
        if not ballot.allow_abstain:
            raise GameError("Abstaining isn't possible in this vote.")
    else:
        target = state.player(target_id)
        if not target.alive:
            raise GameError(f"{target.display_name} isn't alive.")
        if kind == MAYOR and target_id == voter_id:
            raise GameError("You can't vote for yourself.")
    if shown_as is not None:
        shown = state.player(shown_as)
        if not shown.alive:
            raise GameError(f"{shown.display_name} isn't alive.")

    previous = ballot.votes.get(voter_id, "unset")
    if previous == target_id and ballot.shown_as.get(voter_id) == shown_as and voter_id in ballot.votes:
        raise GameError("You already voted for that.")
    ballot.votes[voter_id] = target_id
    if shown_as is not None:
        ballot.shown_as[voter_id] = shown_as
    else:
        ballot.shown_as.pop(voter_id, None)
    ballot.history.append(VoteRecord(voter=voter_id, target=target_id, at=at, shown_as=shown_as))
    return None if previous == "unset" else previous


def retract_vote(state: GameState, kind: str, voter_id: int) -> None:
    ballot = open_ballot_of(state, kind)
    if voter_id not in ballot.votes:
        raise GameError("You haven't voted.")
    del ballot.votes[voter_id]
    ballot.shown_as.pop(voter_id, None)


@dataclass
class Tally:
    outcome: str                       # see the tally_* docstrings
    target: int | None = None
    tied: list[int] = field(default_factory=list)
    counts: dict[int, int] = field(default_factory=dict)
    abstained: int = 0
    eligible: int = 0


def _valid_votes(state: GameState, ballot: Ballot, eligible: list[Player]) -> dict[int, int | None]:
    eligible_ids = {p.user_id for p in eligible}
    return {
        voter: target for voter, target in ballot.votes.items()
        if voter in eligible_ids and (target is None or state.player(target).alive)
    }


def _top(counts: Counter) -> tuple[list[int], int]:
    if not counts:
        return [], 0
    best = max(counts.values())
    return sorted(t for t, c in counts.items() if c == best), best


def tally_lynch(state: GameState, ballot: Ballot) -> Tally:
    """outcome: "abstained" (more than half of the voters didn't vote or
    abstained), "no_votes", "lynch" (target set) or "tie" (tied set)."""
    eligible = eligible_voters(state, ballot.kind)
    votes = _valid_votes(state, ballot, eligible)
    counts = Counter(t for t in votes.values() if t is not None)
    abstained = len(eligible) - sum(counts.values())
    result = Tally(outcome="no_votes", counts=dict(counts), abstained=abstained, eligible=len(eligible))
    if eligible and abstained * 2 > len(eligible):
        result.outcome = "abstained"
        return result
    tied, _ = _top(counts)
    if len(tied) == 1:
        result.outcome, result.target = "lynch", tied[0]
    elif tied:
        result.outcome, result.tied = "tie", tied
    return result


def tally_second_lynch(state: GameState, ballot: Ballot) -> Tally:
    """No abstaining and someone always dies: "lynch", "tie" (the Ruthless
    Counselor picks among `tied`) or "no_votes" (the Counselor picks anyone)."""
    eligible = eligible_voters(state, ballot.kind)
    votes = _valid_votes(state, ballot, eligible)
    counts = Counter(t for t in votes.values() if t is not None)
    tied, _ = _top(counts)
    result = Tally(outcome="no_votes", counts=dict(counts), eligible=len(eligible))
    if len(tied) == 1:
        result.outcome, result.target = "lynch", tied[0]
    elif tied:
        result.outcome, result.tied = "tie", tied
    return result


def tally_wolves(state: GameState, ballot: Ballot) -> Tally:
    """A target needs votes from more than half of the eligible pack; wolves
    who don't vote count as abstaining. outcome: "kill", "no_majority",
    "tie" or "no_votes"."""
    eligible = eligible_voters(state, WOLVES)
    votes = _valid_votes(state, ballot, eligible)
    counts = Counter(t for t in votes.values() if t is not None)
    result = Tally(outcome="no_votes", counts=dict(counts), eligible=len(eligible),
                   abstained=len(eligible) - sum(counts.values()))
    tied, best = _top(counts)
    if not tied:
        return result
    if len(tied) == 1 and best * 2 > len(eligible):
        result.outcome, result.target = "kill", tied[0]
    elif len(tied) > 1:
        result.outcome, result.tied = "tie", tied
    else:
        result.outcome = "no_majority"
    return result


def tally_mayor(state: GameState, ballot: Ballot) -> Tally:
    """outcome: "elected", "tie" or "no_votes"."""
    eligible = eligible_voters(state, MAYOR)
    votes = _valid_votes(state, ballot, eligible)
    counts = Counter(t for t in votes.values() if t is not None)
    tied, _ = _top(counts)
    result = Tally(outcome="no_votes", counts=dict(counts), eligible=len(eligible))
    if len(tied) == 1:
        result.outcome, result.target = "elected", tied[0]
    elif tied:
        result.outcome, result.tied = "tie", tied
    return result


def voters_for(ballot: Ballot, target: int) -> list[int]:
    return sorted(v for v, t in ballot.votes.items() if t == target)


def published_votes(state: GameState, ballot: Ballot) -> str:
    """The public list of who voted for whom (Cunning wolf substitutions
    applied). Non-voters are listed as not voting."""
    lines = []
    eligible = {p.user_id for p in eligible_voters(state, ballot.kind)} | set(ballot.votes)
    for voter in sorted(eligible, key=state.name):
        if voter in ballot.votes:
            target = ballot.shown_as.get(voter, ballot.votes[voter])
            what = "abstained" if target is None else f"voted for **{state.name(target)}**"
        else:
            what = "did not vote"
        lines.append(f"**{state.name(voter)}** {what}")
    return "\n".join(lines) if lines else "Nobody voted."


def describe_counts(state: GameState, tally: Tally) -> str:
    parts = [f"{state.name(t)}: {c}" for t, c in sorted(tally.counts.items(), key=lambda kv: -kv[1])]
    if tally.abstained:
        parts.append(f"abstained/didn't vote: {tally.abstained}")
    return ", ".join(parts) if parts else "no votes"
