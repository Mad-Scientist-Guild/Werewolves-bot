"""The lynch: the dusk resolution, the Mayor's tiebreak, the Ruthless
Counselor's second lynch and lynches decided afterwards."""
from __future__ import annotations

from Core import voting
from Core.decisions import DECISION_HANDLERS, FlowResult, create_decision
from Core.effects import Announcement, VoteResults
from Core.factions import faction_display
from Core.players import seed
from Core.resolution import Resolution
from Core.state import Decision, GameState


def resolve_dusk(state: GameState, result: FlowResult) -> None:
    """Close the lynch vote and resolve everything that happens at dusk."""
    day = state.day
    lynch_ballot = voting.close_ballot(state, voting.LYNCH)
    tally = voting.tally_lynch(state, lynch_ballot) if lynch_ballot else None

    ctx = Resolution(state, kind="dusk", moment=state.moment("dusk"), seed=seed(state, f"dusk:{day}"),
                     title=f"Dusk of day {day}")
    ctx.flags["lynch_tally"] = tally
    target = _lynch_target(state, tally, lynch_ballot, ctx) if tally else None
    ctx.flags["lynch_target"] = target

    def do_lynch() -> None:
        chosen = ctx.flags.get("lynch_target")
        if ctx.flags.get("lynch_stopped") or chosen is None:
            return
        ctx.flags["lynch_attack"] = ctx.attack(
            chosen, "lynch", killers=voting.voters_for(lynch_ballot, chosen), killer_role="village",
            enters_house=False, public=True)

    ctx.commit(do_lynch)   # registered first, so it runs before the dusk abilities' commits
    result.add(f"Dusk of day {day}", ctx.run())

    if ctx.flags.get("needs_mayor_choice") is not None and not ctx.flags.get("lynch_stopped"):
        decision = create_decision(
            state, "lynch_tiebreak", int(ctx.flags["needs_mayor_choice"]), tally.tied,
            "The lynch vote is tied. As Mayor, you decide who is lynched:",
            day=day, voters={str(t): voting.voters_for(lynch_ballot, t) for t in tally.tied},
        )
        ctx.flags["lynch_decision"] = decision.id

    if lynch_ballot is not None:
        state.emit(VoteResults(title=f"Lynch votes — day {day}", text=voting.published_votes(state, lynch_ballot)))
        state.emit(Announcement(title="VOTING HAS CONCLUDED", text=_lynch_announcement(state, ctx, tally)))
        voting.archive_ballot(state, voting.LYNCH)

    if ctx.flags.get("second_lynch_by") is not None:
        open_second_lynch(state, int(ctx.flags["second_lynch_by"]))


def _lynch_target(state: GameState, tally: voting.Tally, ballot, ctx: Resolution) -> int | None:
    if tally.outcome == "lynch":
        return tally.target
    if tally.outcome != "tie":
        return None
    mayor = state.find_player(state.mayor)
    if mayor is None or not mayor.alive:
        ctx.note("Notes", "Lynch tie and there is no Mayor - nobody is lynched.")
        return None
    mayor_vote = ballot.votes.get(mayor.user_id)
    if mayor_vote in tally.tied:
        ctx.note("Notes", f"Lynch tie broken by the Mayor's vote: {state.name(mayor_vote)}")
        ctx.flags["mayor_tiebreak"] = True
        return mayor_vote
    ctx.flags["needs_mayor_choice"] = mayor.user_id
    ctx.note("Notes", "Lynch tie - the Mayor didn't vote for one of the tied players and will choose.")
    return None


def _lynch_announcement(state: GameState, ctx: Resolution, tally: voting.Tally) -> str:
    if ctx.flags.get("lynch_stopped"):
        return "The vote has been stopped - nobody will be lynched today."
    attack = ctx.flags.get("lynch_attack")
    if attack is not None:
        victim = state.player(attack.target)
        if attack.prevented_by:
            return f"The village chose to lynch {victim.display_name}... but they survived!"
        prefix = "There was a tie, and the Mayor's vote decided: " if ctx.flags.get("mayor_tiebreak") else ""
        faction = faction_display(victim.true_faction())
        return f"{prefix}The village lynched **{victim.display_name}**. They were part of the **{faction}**."
    if ctx.flags.get("lynch_decision") is not None:
        names = ", ".join(state.name(t) for t in tally.tied)
        return f"There is a **tie** between {names}. The Mayor will decide who is lynched."
    if tally.outcome == "abstained":
        return "More than half of the village didn't vote or abstained - nobody is lynched."
    if tally.outcome == "tie":
        return "There is a **tie** and no Mayor to break it - nobody is lynched."
    return "Nobody voted - nobody is lynched."


# --- second lynch ---------------------------------------------------------------

def open_second_lynch(state: GameState, counselor: int) -> None:
    voting.open_ballot(state, voting.LYNCH2, allow_abstain=False)
    state.data["second_lynch_by"] = counselor
    state.lockdown = True
    state.emit(Announcement(
        title="A SECOND LYNCH",
        text="The Ruthless Counselor demands a second lynch - **right now**. All discussion channels are locked "
             f"until the result is posted. Vote with `/lynch vote` before {state.settings.schedule.second_lynch_end}. "
             "Abstaining is not possible.", color="red"))
    state.log("LYNCH", f"Second lynch called by {state.name(counselor)}; lockdown on.", actor=counselor, alert=True)


def end_second_lynch(state: GameState, result: FlowResult) -> None:
    ballot = voting.close_ballot(state, voting.LYNCH2)
    if ballot is None:
        return
    tally = voting.tally_second_lynch(state, ballot)
    counselor = state.data.get("second_lynch_by")
    state.emit(VoteResults(title=f"Second lynch votes — day {state.day}", text=voting.published_votes(state, ballot)))
    if tally.outcome == "lynch":
        result.add("Second lynch", execute_lynch(state, tally.target, second=True, voters=voting.voters_for(ballot, tally.target)))
    else:
        options = tally.tied or [p.user_id for p in state.alive_players()]
        chooser = state.find_player(counselor)
        create_decision(
            state, "lynch2_tiebreak", chooser.user_id if chooser and chooser.alive else None, options,
            "The second lynch is tied - as Ruthless Counselor you decide who dies:" if tally.tied
            else "Nobody voted in the second lynch - as Ruthless Counselor you decide who dies:",
            day=state.day, voters={str(t): voting.voters_for(ballot, t) for t in tally.tied},
        )
        state.emit(Announcement(title="SECOND LYNCH", text="The second lynch is undecided - the Ruthless Counselor will choose."))
    voting.archive_ballot(state, voting.LYNCH2)


# --- lynches outside the dusk resolution ----------------------------------------

def execute_lynch(state: GameState, target: int, *, second: bool, voters: list[int] | None = None,
                  by_decision: bool = False) -> str:
    """Lynch outside the dusk resolution (tiebreak decisions, second lynch)."""
    ctx = Resolution(state, kind="lynch", moment=f"lynch:{state.day}", seed=seed(state, f"lynch:{state.day}:{target}"),
                     title=f"{'Second lynch' if second else 'Lynch'} of {state.name(target)}", actions=[])
    holder: dict[str, object] = {}

    def do() -> None:
        holder["attack"] = ctx.attack(target, "lynch", killers=voters or [], killer_role="village",
                                      enters_house=False, public=True)

    ctx.commit(do)
    report = ctx.run()
    victim = state.player(target)
    attack = holder["attack"]
    how = "chosen by the Mayor" if by_decision and not second else "chosen by the Ruthless Counselor" if by_decision else "lynched"
    if attack.prevented_by:
        text = f"**{victim.display_name}** was {how}... but they survived!"
    else:
        text = f"**{victim.display_name}** was {how}. They were part of the **{faction_display(victim.true_faction())}**."
    state.emit(Announcement(title="SECOND LYNCH RESULT" if second else "LYNCH RESULT", text=text))
    if second:
        state.lockdown = False
        state.log("LYNCH", "Lockdown lifted.")
    return report


def _decide_lynch_tiebreak(state: GameState, decision: Decision, result: FlowResult) -> None:
    voters = decision.data.get("voters", {}).get(str(decision.choice), [])
    result.add("Lynch tiebreak", execute_lynch(state, decision.choice, second=False, voters=voters, by_decision=True))


def _decide_second_lynch(state: GameState, decision: Decision, result: FlowResult) -> None:
    voters = decision.data.get("voters", {}).get(str(decision.choice), [])
    result.add("Second lynch", execute_lynch(state, decision.choice, second=True, voters=voters, by_decision=True))


DECISION_HANDLERS["lynch_tiebreak"] = _decide_lynch_tiebreak
DECISION_HANDLERS["lynch2_tiebreak"] = _decide_second_lynch
