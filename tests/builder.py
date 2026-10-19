"""One-line scenario setup for engine tests.

    g = GameBuilder()
    g.player("alice", "silver_angel"); g.player("wolfy", "ancient_wolf")
    g.start(); g.dusk()                     # day 1 -> night 1
    g.act("alice", "protect", target="bob")
    g.wolf_vote("wolfy", "bob")
    g.lock(); g.morning()                   # resolve night 1
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import Roles  # noqa: F401 - registers every role
from Core import actions, flow, voting
from Core.clock import TransitionKind
from Core.state import GameState, Player

TZ = ZoneInfo("Europe/Amsterdam")


class GameBuilder:
    def __init__(self) -> None:
        self.state = GameState(guild_id=1, game_id=1)
        self.ids: dict[str, int] = {}
        self.now = datetime(2026, 10, 5, 10, 0, tzinfo=TZ)
        self.reports: list[tuple[str, str]] = []

    # --- setup -------------------------------------------------------------
    def player(self, name: str, role: str) -> Player:
        uid = 100 + len(self.ids)
        self.ids[name] = uid
        player = flow.add_player(self.state, uid, name)
        flow.set_role(self.state, player, role)
        return player

    def players(self, **roles: str) -> None:
        for name, role in roles.items():
            self.player(name, role)

    def families(self, *members: tuple[str, ...]) -> None:
        """g.families(("a", "b"), ("c", "d")) - each tuple is one family (= one house)."""
        from Core.state import GroupKind
        for index, names in enumerate(members, start=1):
            key = f"family:{index}"
            self.state.ensure_group(key, GroupKind.FAMILY, f"family-{index}")
            for name in names:
                flow.set_family(self.state, self.p(name), key)

    def id(self, name: str) -> int:
        return self.ids[name]

    def p(self, name: str) -> Player:
        return self.state.player(self.ids[name])

    def start(self) -> "GameBuilder":
        flow.start_game(self.state, self.now)
        return self

    # --- time ----------------------------------------------------------------
    def _run(self, kind: TransitionKind, hour: int) -> flow.FlowResult:
        self.now = self.now.replace(hour=hour, minute=0)
        result = flow.run_transition(self.state, kind, self.now)
        self.reports.extend(result.reports)
        return result

    def newspaper(self) -> flow.FlowResult:
        return self._run(TransitionKind.NEWSPAPER, 12)

    def dusk(self) -> flow.FlowResult:
        return self._run(TransitionKind.DUSK, 19)

    def second_lynch_end(self) -> flow.FlowResult:
        return self._run(TransitionKind.SECOND_LYNCH_END, 20)

    def lock(self) -> flow.FlowResult:
        result = self._run(TransitionKind.NIGHT_LOCK, 23)
        self.now += timedelta(hours=1)
        return result

    def morning(self) -> flow.FlowResult:
        return self._run(TransitionKind.MORNING, 8)

    def night(self) -> flow.FlowResult:
        """lock + morning"""
        self.lock()
        return self.morning()

    # --- actions -------------------------------------------------------------
    def act(self, name: str, ability: str, **params):
        clean = {k: (self.ids[v] if isinstance(v, str) and v in self.ids else v) for k, v in params.items()}
        return actions.submit(self.state, self.ids[name], ability, clean, now=self.now)

    def wolf_vote(self, voter: str, target: str | None) -> None:
        voting.cast_vote(self.state, voting.WOLVES, self.ids[voter], self.ids[target] if target else None,
                         at=self.now.isoformat())

    def vote(self, voter: str, target: str | None, kind: str = voting.LYNCH) -> None:
        voting.cast_vote(self.state, kind, self.ids[voter], self.ids[target] if target else None,
                         at=self.now.isoformat())

    # --- inspection ----------------------------------------------------------
    def alive(self, name: str) -> bool:
        return self.p(name).alive

    def messages_for(self, name: str) -> list[str]:
        from Core.effects import PrivateMessage
        return [e.text for e in self.state.pending_effects
                if isinstance(e, PrivateMessage) and e.player == self.ids[name]]

    def last_report(self) -> str:
        return self.reports[-1][1] if self.reports else ""
