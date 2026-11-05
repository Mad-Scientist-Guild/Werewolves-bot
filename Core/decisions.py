"""Decisions: a choice a player (or the GMs) must make before something can
resolve, e.g. the Mayor breaking a lynch tie. Every kind of decision has a
handler in DECISION_HANDLERS; the lynch tiebreaks register theirs in
Core/lynch.py, roles register their own (e.g. the new Vampire Lord)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from Core.effects import DecisionPrompt
from Core.errors import GameError
from Core.state import Decision, GameState


@dataclass
class FlowResult:
    """Reports for the mod channel produced by a transition or decision."""
    reports: list[tuple[str, str]] = field(default_factory=list)

    def add(self, title: str, text: str) -> None:
        self.reports.append((title, text))


# kind -> handler(state, decision, result)
DECISION_HANDLERS: dict[str, Callable[[GameState, Decision, FlowResult], None]] = {}


def create_decision(state: GameState, kind: str, chooser: int | None, options: list[int], prompt: str,
                    **data) -> Decision:
    decision = Decision(id=state.next_id("decision"), kind=kind, chooser=chooser, options=list(options),
                        prompt=prompt, data=data)
    state.decisions.append(decision)
    state.emit(DecisionPrompt(decision_id=decision.id))
    who = state.name(chooser) if chooser is not None else "the GMs"
    state.log("DECISION", f"Waiting for {who}: {prompt} Options: {', '.join(state.name(o) for o in options)}",
              actor=chooser, alert=True, decision_id=decision.id)
    return decision


def open_decisions(state: GameState) -> list[Decision]:
    return [d for d in state.decisions if not d.resolved]


def resolve_decision(state: GameState, decision_id: int, choice: int, *, by: int, by_gm: bool = False) -> FlowResult:
    decision = next((d for d in state.decisions if d.id == decision_id), None)
    if decision is None or decision.resolved:
        raise GameError("That decision is no longer open.")
    if not by_gm and decision.chooser != by:
        raise GameError("This decision isn't yours to make.")
    if choice not in decision.options:
        raise GameError("That isn't one of the options.")
    handler = DECISION_HANDLERS.get(decision.kind)
    if handler is None:
        raise GameError(f"No handler for decision kind '{decision.kind}'")
    decision.resolved = True
    decision.choice = choice
    state.log("DECISION", f"{state.name(by)}{' (GM)' if by_gm else ''} chose {state.name(choice)} for: {decision.prompt}",
              actor=by, targets=[choice], decision_id=decision.id)

    result = FlowResult()
    handler(state, decision, result)
    return result
