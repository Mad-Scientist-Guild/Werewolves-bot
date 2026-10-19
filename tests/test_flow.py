import pytest

from Core import flow, voting
from Core.actor import ROLE_REGISTRY
from Core.effects import RoleCard
from Core.errors import GameError
from Core.state import LifeState, Phase, PublicStatus
from Services.effects import role_card
from tests.builder import GameBuilder


def game() -> GameBuilder:
    g = GameBuilder()
    g.players(w1="ancient_wolf", w2="ancient_wolf", angel="silver_angel", v1="villager", v2="villager")
    g.start()
    return g


def test_mayor_is_elected_on_day_one():
    g = game()
    for voter in ("w1", "w2", "angel"):
        g.vote(voter, "v1", voting.MAYOR)
    g.vote("v1", "v2", voting.MAYOR)
    g.dusk()
    assert g.state.mayor == g.id("v1")
    assert voting.MAYOR not in g.state.ballots


def test_mayor_successor_takes_over_quietly():
    g = game()
    g.state.mayor, g.state.mayor_successor = g.id("v1"), g.id("v2")
    g.dusk(); g.wolf_vote("w1", "v1"); g.wolf_vote("w2", "v1"); g.night()
    assert g.state.mayor == g.id("v2")
    assert "new Mayor" in g.last_report()
    assert any("you are now the Mayor" in m for m in g.messages_for("v2"))


def test_gm_kill_is_quiet_unless_public():
    g = game()
    flow.gm_kill(g.state, g.id("v1"), cause="inactive")
    assert g.p("v1").dead and g.p("v1").public_status is PublicStatus.NONE
    flow.gm_kill(g.state, g.id("v2"), public=True)
    assert g.p("v2").public_status is PublicStatus.DEAD
    with pytest.raises(GameError):
        flow.gm_kill(g.state, g.id("v2"))
    flow.gm_revive(g.state, g.id("v1"))
    assert g.p("v1").alive and g.p("v1").deaths[-1].revived


def test_reaper_replacement_moves_everything():
    g = game()
    g.dusk()
    g.act("angel", "protect", target="v1")
    old = g.id("angel")
    flow.replace_player(g.state, old, 999, "newbie")
    p = g.state.player(999)
    assert p.role_name == "silver_angel" and p.role.owner == 999 and old in p.previous_user_ids
    assert g.state.groups[p.private_group].members.get(999) is not None
    assert any(a.actor == 999 for a in g.state.actions)
    g.night()   # the transferred action still resolves


def test_night_overrides():
    g = game()
    g.dusk()
    g.wolf_vote("w1", "v1"); g.wolf_vote("w2", "v1")
    flow.add_night_override(g.state, "spare", g.id("v1"))
    flow.add_night_override(g.state, "kill", g.id("v2"), cause="reaper")
    g.night()
    assert g.alive("v1") and not g.alive("v2")
    assert g.p("v2").death.cause == "reaper"
    assert g.state.night_overrides == []


def test_skeleton_cannot_be_revived_and_dies_permanently():
    g = game()
    g.p("v1").life = LifeState.SKELETON
    flow.gm_kill(g.state, g.id("v1"))
    assert g.p("v1").life is LifeState.PERMA_DEAD
    with pytest.raises(GameError):
        flow.gm_revive(g.state, g.id("v1"))


def test_game_end():
    g = game()
    from datetime import datetime
    flow.end_game(g.state, "villagers", g.now)
    assert g.state.phase is Phase.ENDED and g.state.next_transition is None


@pytest.mark.parametrize("role", sorted(ROLE_REGISTRY))
def test_every_role_has_a_card(role):
    g = game()
    e = role_card(g.state, RoleCard(player=g.id("v1"), role=role))
    assert ROLE_REGISTRY[role].title() in e.title
    assert ROLE_REGISTRY[role].description
