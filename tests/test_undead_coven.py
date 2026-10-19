import pytest

from Core import actions, flow, voting
from Core.access import Access, player_access
from Core.errors import GameError
from Core.factions import winners
from Core.state import LifeState
from Roles.coven._coven import group_of
from tests.builder import GameBuilder


def build(**roles: str) -> GameBuilder:
    g = GameBuilder()
    g.players(**roles)
    g.state.data["first_death_seen"] = True   # keep the Vengeful Spirit out of these scenarios
    return g


def pack(g: GameBuilder, victim: str, *wolves: str) -> None:
    for wolf in wolves:
        g.wolf_vote(wolf, victim)


# --- Lich & Skeletons -------------------------------------------------------------------

def lich_game() -> GameBuilder:
    g = build(lich="lich", w1="normal_wolf", w2="normal_wolf", seery="seer", angie="silver_angel",
              v1="villager", v2="villager", v3="villager")
    g.start(); g.dusk(); pack(g, "seery", "w1", "w2"); g.night()          # the seer dies
    g.newspaper(); g.dusk(); pack(g, "angie", "w1", "w2"); g.night()     # the angel dies
    g.newspaper(); g.dusk()
    return g


def test_lich_raises_correct_guesses():
    g = lich_game()
    g.act("lich", "raise", first="seery", first_role="seer", second="angie", second_role="villager")
    g.night()
    seer, angel = g.p("seery"), g.p("angie")
    assert seer.life is LifeState.SKELETON and seer.true_faction() == "undead"
    assert angel.life is LifeState.DEAD
    assert player_access(g.state, g.state.groups["village"], seer) is Access.REACT
    assert player_access(g.state, g.state.groups["dead"], seer) is Access.NONE
    assert player_access(g.state, g.state.groups[f"skeletons:{g.id('lich')}"], seer) is Access.WRITE
    g.newspaper()
    with pytest.raises(GameError):
        g.vote("seery", "v1")                                              # skeletons can't vote


def test_lich_only_dies_by_lynch_and_takes_the_skeletons_along():
    g = lich_game()
    g.act("lich", "raise", first="seery", first_role="seer"); pack(g, "lich", "w1", "w2")
    g.night()
    assert g.alive("lich")
    g.newspaper()
    for voter in ("w1", "w2", "v1", "v2", "v3"):
        g.vote(voter, "lich")
    g.dusk()
    assert not g.alive("lich")
    assert g.p("seery").life is LifeState.PERMA_DEAD
    g.night(); g.newspaper(); g.dusk()


def test_dead_skeleton_never_rises_again():
    g = lich_game()
    g.act("lich", "raise", first="seery", first_role="seer"); g.night()
    flow.gm_kill(g.state, g.id("seery"))
    g.newspaper(); g.dusk()
    with pytest.raises(GameError):
        g.act("lich", "raise", first="seery", first_role="seer")


def test_gambler_visiting_the_lich_becomes_a_skeleton():
    g = build(gam="gambler", lich="lich", w="normal_wolf", v="villager")
    g.start(); g.dusk(); g.act("gam", "visit", target="lich"); g.night()
    assert g.p("gam").life is LifeState.SKELETON


# --- Vampires ----------------------------------------------------------------------------

def vampire_game() -> GameBuilder:
    g = build(vl="vampire_lord", w1="normal_wolf", w2="normal_wolf", a="villager", b="villager", c="villager",
              d="villager", e="villager")
    g.start(); g.dusk()
    return g


def test_vampire_bite_kills():
    g = vampire_game(); g.act("vl", "bite", target="a"); g.night()
    assert not g.alive("a") and g.p("a").death.killer_role == "vampire_lord"


def test_vampire_turns_a_spawn_and_only_one_at_a_time():
    g = vampire_game(); g.act("vl", "bite", target="a", mode="turn"); g.night()
    a = g.p("a")
    assert a.alive and a.true_faction() == "undead"
    assert player_access(g.state, g.state.groups["undead"], a) is Access.WRITE
    g.newspaper(); g.dusk()
    with pytest.raises(GameError, match="already have"):
        g.act("vl", "bite", target="b", mode="turn")


def test_ancient_wolf_and_vampire_turning_the_same_person():
    g = build(vl="vampire_lord", an="ancient_wolf", w="normal_wolf", a="villager", b="villager", c="villager")
    g.start(); g.dusk()
    pack(g, "a", "an", "w"); g.act("an", "turn"); g.act("vl", "bite", target="a", mode="turn")
    g.night()
    a = g.p("a")
    assert a.alive and (a.has_modifier("turned_wolf") != a.has_modifier("vampire_spawn"))   # exactly one wins


def test_spawn_becomes_lord_after_sharing_a_kill():
    g = vampire_game(); g.act("vl", "bite", target="a", mode="turn"); g.night(); g.newspaper(); g.dusk()
    g.act("vl", "bite", target="b"); g.night()                       # the spawn shares in this kill
    assert g.p("a").modifier("vampire_spawn").participated
    g.newspaper()
    for voter in ("w1", "w2", "c", "d", "e"):
        g.vote(voter, "vl")
    g.dusk()
    assert g.p("a").role_name == "vampire_lord" and not g.p("a").has_modifier("vampire_spawn")


def test_spawn_without_a_kill_stays_spawn():
    g = vampire_game(); g.act("vl", "bite", target="a", mode="turn"); g.night(); g.newspaper()
    for voter in ("w1", "w2", "c", "d", "e"):
        g.vote(voter, "vl")
    g.dusk()
    assert g.p("a").has_modifier("vampire_spawn") and g.p("a").role_name == "villager"


def test_slut_is_turned_along_by_a_vampire():
    g = build(vl="vampire_lord", slut="village_slut", w="normal_wolf", a="villager", b="villager")
    g.start(); g.dusk()
    g.act("slut", "visit", target="a"); g.act("vl", "bite", target="a", mode="turn")
    g.night()
    assert g.p("slut").has_modifier("vampire_spawn")


def test_undead_win():
    g = lich_game()
    g.act("lich", "raise", first="seery", first_role="seer", second="angie", second_role="silver_angel")
    g.night()
    for name in ("w1", "w2", "v1", "v2"):
        flow.gm_kill(g.state, g.id(name))
    assert "undead" in winners(g.state)       # lich + 2 skeletons vs 1 living villager


# --- Coven discovery & chats ---------------------------------------------------------------

def coven_game() -> GameBuilder:
    g = build(curse="curseweaver", div="diviner", ench="enchantress", hag="hag_mother",
              w="normal_wolf", seery="seer", a="villager", b="villager", c="villager", d="villager")
    g.families(("curse", "a", "b"), ("div", "c", "seery"), ("ench", "d"), ("hag", "w"))
    g.start(); g.dusk()
    return g


def test_kill_list_is_generated():
    g = coven_game()
    kill_list = g.state.data["coven_kill_list"]
    in_game = {"normal_wolf", "seer", "villager"}
    assert in_game <= set(kill_list) and len(kill_list) == len(in_game) + 3
    assert not any(role in kill_list for role in ("curseweaver", "diviner", "enchantress", "hag_mother"))


def test_finding_members_builds_and_merges_chats():
    g = coven_game()
    g.act("curse", "find", target="div")
    g.act("ench", "find", target="seery")                     # wrong
    g.night()
    assert group_of(g.state, g.id("curse")) == {g.id("curse"), g.id("div")}
    first_chat = g.state.data["coven_chat_of"][str(g.id("curse"))]
    assert any("kill list" in m for m in g.messages_for("div"))
    assert "not part of the Coven" in g.messages_for("ench")[-1]
    g.newspaper(); g.dusk()
    g.act("ench", "find", target="div")                     # finding ONE member joins the whole group
    g.night()
    assert group_of(g.state, g.id("ench")) == {g.id("curse"), g.id("div"), g.id("ench")}
    assert g.state.data["coven_chat_of"][str(g.id("ench"))] == first_chat
    assert player_access(g.state, g.state.groups[first_chat], g.p("ench")) is Access.WRITE


def test_merging_two_groups_archives_their_chats():
    g = coven_game()
    g.act("curse", "find", target="div"); g.act("ench", "find", target="hag")
    g.night(); g.newspaper(); g.dusk()
    old_a = g.state.data["coven_chat_of"][str(g.id("curse"))]
    old_b = g.state.data["coven_chat_of"][str(g.id("ench"))]
    g.act("div", "find", target="ench")
    g.night()
    new = g.state.data["coven_chat_of"][str(g.id("curse"))]
    assert new not in (old_a, old_b)
    assert g.state.groups[old_a].archived and g.state.groups[old_b].archived
    assert player_access(g.state, g.state.groups[old_a], g.p("curse")) is Access.READ       # still readable
    assert player_access(g.state, g.state.groups[new], g.p("hag")) is Access.WRITE


def test_hag_mother_check_needs_the_whole_coven():
    g = coven_game()
    with pytest.raises(GameError):
        g.act("hag", "check", role="seer")
    g.act("hag", "find", target="curse", target2="div", target3="ench")
    g.night(); g.newspaper(); g.dusk()
    g.act("hag", "check", role="seer")
    g.night()
    assert "still alive" in g.messages_for("hag")[-1]


# --- Curseweaver ---------------------------------------------------------------------------

def test_curse_of_transformation_blocks_the_night_action():
    g = coven_game()
    g.act("seery", "check", target="w"); g.act("curse", "curse", target="seery", curse="transformation")
    g.night()
    check = next(a for a in g.state.actions if a.ability == "check")
    assert check.status.value == "blocked"
    assert any("Curse of Transformation" in m for m in g.messages_for("seery"))
    g.newspaper(); g.dusk()
    with pytest.raises(GameError, match="twice in a row"):
        g.act("curse", "curse", target="seery", curse="puppet")


def test_curse_of_the_puppet_redirects_away_from_known_coven():
    g = coven_game()
    g.act("curse", "find", target="div"); g.night(); g.newspaper(); g.dusk()
    g.act("seery", "check", target="w"); g.act("curse", "curse", target="seery", curse="puppet")
    g.night()
    msg = g.messages_for("seery")
    assert not any("**w**" in m for m in msg if "vision" in m)                     # redirected away from w
    assert not any(f"**{name}**" in m for m in msg for name in ("div", "curse") if "vision" in m)


# --- Diviner ------------------------------------------------------------------------------

def test_diviner_detection_and_vision():
    g = coven_game()
    g.act("div", "divine", target="a", method="detection")
    g.night()
    assert "nothing happened" in g.messages_for("div")[-1]
    g.newspaper(); g.dusk()
    g.act("div", "divine", target="ench", method="vision")
    g.night()
    assert "**Villager**" in g.messages_for("div")[-1] or "**Enchantress**" in g.messages_for("div")[-1]


def test_diviner_scrying_schedules_a_relay_on_the_family():
    g = coven_game()
    g.act("div", "scry", target="a", start="21:30")
    relay = g.state.relays[0]
    assert relay.source_group == g.p("a").family and relay.purpose == "diviner"
    with pytest.raises(GameError, match="already"):
        g.act("div", "divine", target="a", method="vision")


# --- Enchantress ----------------------------------------------------------------------------

def day_two_coven() -> GameBuilder:
    g = coven_game(); g.night(); g.newspaper()
    return g


def test_charm_of_protection():
    g = day_two_coven()
    g.act("ench", "enchant", target="a", charm="protection")
    g.dusk(); pack(g, "a", "w"); g.night()
    assert g.alive("a")
    g.newspaper()
    with pytest.raises(GameError, match="twice"):
        g.act("ench", "enchant", target="a", charm="protection")


def test_charm_of_the_open_book_asks_the_target():
    g = day_two_coven()
    g.act("ench", "enchant", target="a", charm="open_book", question="Do you trust b?")
    seance = g.state.seances[0]
    assert seance.kind == "open_book" and seance.voters == [g.id("a")] and seance.where == g.p("a").private_group
    from Core import realtime
    realtime.answer_seance(g.state, seance.id, g.id("a"), True)
    assert "answered “Do you trust b?” with **yes**" in g.messages_for("ench")[-1]


def test_charm_of_revenge():
    g = day_two_coven()
    g.act("ench", "enchant", target="a", charm="revenge")
    g.dusk(); pack(g, "a", "w"); g.night()
    assert not g.alive("a")
    g.now = g.now.replace(hour=10)
    g.act("ench", "revenge", target="w")
    assert not g.alive("w")
    assert g.p("ench").role.protection_lost


def test_revenge_only_before_18():
    g = day_two_coven()
    g.act("ench", "enchant", target="a", charm="revenge")
    g.dusk(); pack(g, "a", "w"); g.night()
    g.now = g.now.replace(hour=18, minute=30)
    with pytest.raises(GameError, match="18:00"):
        g.act("ench", "revenge", target="w")


# --- Hag Mother & Changeling -----------------------------------------------------------------

def test_changeling_grows_up_after_three_nights_and_joins_the_hag():
    g = coven_game()
    g.act("hag", "changeling", target="a"); g.act("seery", "check", target="a")
    g.night()
    assert g.p("a").true_faction() == "villagers"                 # hidden while growing
    for _ in range(3):
        g.newspaper(); g.dusk(); g.night()
    a = g.p("a")
    assert a.modifier("changeling").grown and a.true_faction() == "coven"
    assert g.id("a") in group_of(g.state, g.id("hag"))
    assert a.role_name == "villager"                              # keeps their own role


def test_changeling_withers_if_the_hag_mother_dies():
    g = coven_game()
    g.act("hag", "changeling", target="a"); g.night()
    flow.gm_kill(g.state, g.id("hag"))
    for _ in range(3):
        g.newspaper(); g.dusk(); g.night()
    assert not g.p("a").modifier("changeling").grown and g.p("a").true_faction() == "villagers"


def test_grown_changeling_lover_does_not_die_of_heartbreak():
    g = build(cupid="cupid", hag="hag_mother", c2="curseweaver", w1="normal_wolf", w2="normal_wolf",
              a="villager", b="villager", v="villager")
    g.start(); g.dusk()
    g.act("cupid", "link", first="a", second="b"); g.act("hag", "changeling", target="a")
    g.night()
    for _ in range(3):
        g.newspaper(); g.dusk(); g.night()
    g.newspaper(); g.dusk(); pack(g, "b", "w1", "w2"); g.night()
    assert not g.alive("b") and g.alive("a")
