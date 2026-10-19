import pytest

from Core import flow, voting
from Core.actor import ROLE_REGISTRY
from Core.effects import PrivateMessage, VoteChannelPost
from Core.errors import GameError
from Core.state import ActionStatus
from tests.builder import GameBuilder


def eat(g: GameBuilder, victim: str, *wolves: str) -> None:
    for wolf in wolves:
        g.wolf_vote(wolf, victim)


# --- pack -----------------------------------------------------------------------

def test_whole_living_pack_attacks():
    g = GameBuilder()
    g.players(w1="normal_wolf", w2="normal_wolf", w3="normal_wolf", v1="villager", v2="villager", hound="bloodhound")
    g.start(); g.dusk()
    eat(g, "v1", "w1", "w2", "hound")  # 3 of 4; w3 doesn't vote but still attacks with the pack
    g.act("hound", "track", target="w3")
    g.night()
    assert not g.alive("v1")
    assert set(g.p("v1").death.killer_ids) == {g.id("w1"), g.id("w2"), g.id("w3"), g.id("hound")}
    assert "w3** left their house" in g.messages_for("hound")[0]


# --- normal wolf ------------------------------------------------------------------

def test_normal_wolf_learns_a_villager_role_not_in_the_game():
    g = GameBuilder()
    g.players(w="normal_wolf", a="silver_angel", v="villager")
    g.start()
    hint = g.p("w").role.hint
    assert hint is not None and hint not in ("silver_angel", "villager")
    assert ROLE_REGISTRY[hint].faction == "villagers"
    assert any(ROLE_REGISTRY[hint].title() in m for m in g.messages_for("w"))


def test_gm_can_choose_the_normal_wolf_hint():
    g = GameBuilder()
    g.players(w="normal_wolf", v="villager")
    g.state.settings.role_overrides["normal_wolf"] = {"hint": "grave_robber"}
    g.start()
    assert g.p("w").role.hint == "grave_robber"


# --- apprentice -------------------------------------------------------------------

def apprentice_game() -> GameBuilder:
    g = GameBuilder()
    g.players(feral="feral_wolf", app="apprentice_wolf", w="normal_wolf", angel="silver_angel",
              v1="villager", v2="villager", v3="villager", v4="villager")
    g.start()
    return g


def test_apprentice_takes_over_the_fallen_wolf_with_its_charges():
    g = apprentice_game()
    g.dusk()
    g.act("feral", "eat", target="v1")          # feral uses 1 of 3
    g.night(); g.newspaper()
    for voter in ("v2", "v3", "v4", "angel", "w"):
        g.vote(voter, "feral")
    g.dusk()                                    # feral lynched -> apprentice may take over tonight
    assert not g.alive("feral")
    g.act("app", "take_over", target="feral")
    g.night()
    app = g.p("app")
    assert app.role_name == "feral_wolf" and app.role.uses == {"eat": 1}
    assert app.role.owner == app.user_id
    assert app.original_role == "apprentice_wolf"
    # the fallen wolf comes back without abilities
    flow.gm_revive(g.state, g.id("feral"))
    assert g.p("feral").role_name == "werewolf"


def test_apprentice_offer_is_only_for_that_night():
    g = apprentice_game()
    g.dusk(); eat(g, "w", "feral", "app")       # the pack eats a fellow wolf at night 1
    g.night()                                   # w died at night 1 -> offer for night 2
    with pytest.raises(GameError):
        g.act("app", "take_over", target="w")   # day 2: not a night action time
    g.newspaper(); g.dusk()
    g.act("app", "take_over", target="w")       # night 2 works
    g.act("app", "take_over", target="w")
    g.lock(); g.morning()
    assert g.p("app").role_name == "normal_wolf"


def test_apprentice_offer_expires():
    g = apprentice_game()
    g.dusk(); eat(g, "w", "feral", "app"); g.night()
    g.newspaper(); g.dusk(); g.night()          # night 2 passes without taking over
    g.newspaper(); g.dusk()
    with pytest.raises(GameError):
        g.act("app", "take_over", target="w")


# --- bloodhound ---------------------------------------------------------------------

def test_bloodhound_sees_who_stayed_home():
    g = GameBuilder()
    g.players(hound="bloodhound", w="normal_wolf", angel="silver_angel", v="villager", v2="villager")
    g.start(); g.dusk()
    g.act("hound", "track", target="v")
    g.night()
    assert "**v** stayed at home" in g.messages_for("hound")[0]


# --- cunning wolf -------------------------------------------------------------------

def test_cunning_wolf_vote_is_published_under_another_name():
    g = GameBuilder()
    g.players(cun="cunning_wolf", w="normal_wolf", v1="villager", v2="villager", v3="villager")
    g.start(); g.dusk(); g.night(); g.newspaper()
    g.act("cun", "vote", target="v1", shown_as="v2")
    for voter in ("w", "v3"):
        g.vote(voter, "v1")
    g.dusk()
    assert not g.alive("v1")
    published = [e.text for e in g.state.pending_effects if isinstance(e, VoteChannelPost)][-1]
    assert "**cun** voted for **v2**" in published


def test_cunning_wolf_cannot_vote_when_voting_is_closed():
    g = GameBuilder()
    g.players(cun="cunning_wolf", v1="villager", v2="villager")
    g.start(); g.dusk(); g.night()
    with pytest.raises(GameError):
        g.act("cun", "vote", target="v1", shown_as="v2")


# --- feral wolf ------------------------------------------------------------------------

def test_feral_wolf_extra_kill_three_times():
    g = GameBuilder()
    g.players(feral="feral_wolf", w="normal_wolf", angel="silver_angel",
              **{f"v{i}": "villager" for i in range(6)})
    g.start()
    for i in range(3):
        g.dusk()
        g.act("feral", "eat", target=f"v{i}")
        g.night(); g.newspaper()
        assert not g.alive(f"v{i}")
    g.dusk()
    with pytest.raises(GameError, match="no uses"):
        g.act("feral", "eat", target="v4")


def test_silver_angel_protects_against_the_feral_wolf():
    g = GameBuilder()
    g.players(feral="feral_wolf", angel="silver_angel", v="villager", v2="villager")
    g.start(); g.dusk()
    g.act("feral", "eat", target="v")
    g.act("angel", "protect", target="v")
    g.night()
    assert g.alive("v")
    assert g.p("feral").role.uses == {"eat": 1}   # an attempt that was stopped still counts


# --- shadow wolf ----------------------------------------------------------------------

def test_shadow_wolf_forces_a_leaving_player_back():
    g = GameBuilder()
    g.players(shadow="shadow_wolf", w="normal_wolf", angel="silver_angel", v="villager", v2="villager")
    g.start(); g.dusk()
    g.act("angel", "protect", target="v")      # the angel leaves the house to protect...
    g.act("shadow", "stalk", target="angel")   # ...and finds the shadow wolf waiting
    eat(g, "v", "shadow", "w")
    g.night()
    assert not g.alive("v")
    protect = next(a for a in g.state.actions if a.ability == "protect")
    assert protect.status is ActionStatus.BLOCKED
    assert any("Shadow wolf" in m for m in g.messages_for("angel"))


def test_shadow_wolf_stalked_player_keeps_limited_uses():
    g = GameBuilder()
    g.players(shadow="shadow_wolf", feral="feral_wolf", v="villager", v2="villager", v3="villager")
    g.start(); g.dusk()
    g.act("feral", "eat", target="v")
    g.act("shadow", "stalk", target="feral")
    g.night()
    assert g.alive("v")
    assert g.p("feral").role.uses.get("eat", 0) == 0


def test_shadow_wolf_never_stalks_the_same_player_twice():
    g = GameBuilder()
    g.players(shadow="shadow_wolf", v="villager", v2="villager")
    g.start(); g.dusk()
    g.act("shadow", "stalk", target="v")
    g.night(); g.newspaper(); g.dusk()
    with pytest.raises(GameError, match="twice"):
        g.act("shadow", "stalk", target="v")


def test_stalked_player_who_stays_home_is_still_notified():
    g = GameBuilder()
    g.players(shadow="shadow_wolf", v="villager", v2="villager")
    g.start(); g.dusk()
    g.act("shadow", "stalk", target="v")
    g.night()
    assert any("Shadow wolf" in m for m in g.messages_for("v"))


# --- rabid wolf ------------------------------------------------------------------------

def test_rabid_wolf_is_gm_resolved_for_now():
    assert ROLE_REGISTRY["rabid_wolf"].abilities == ()
    assert "resolved by the GMs" in ROLE_REGISTRY["rabid_wolf"].description
