import math

import pytest

from Core import flow
from Core.errors import GameError
from Core.state import ActionStatus
from tests.builder import GameBuilder


def build(**roles: str) -> GameBuilder:
    g = GameBuilder()
    g.players(**roles)
    return g


def pack(g: GameBuilder, victim: str, *wolves: str) -> None:
    for wolf in wolves:
        g.wolf_vote(wolf, victim)


def action(g: GameBuilder, ability: str):
    return next(a for a in reversed(g.state.actions) if a.ability == ability)


# --- Seer -------------------------------------------------------------------------

def test_seer_sees_faction_then_role():
    g = build(seer="seer", w="normal_wolf", v="villager", v2="villager")
    g.start(); g.dusk()
    g.act("seer", "check", target="w"); g.night()
    assert "belongs to the **Werewolves**" in g.messages_for("seer")[-1]
    g.newspaper(); g.dusk()
    g.act("seer", "check", target="w"); g.night()
    assert "is the **Normal wolf**" in g.messages_for("seer")[-1]


def test_seer_sees_cultist_as_villager_then_as_cultist():
    g = build(seer="seer", c="cultist", w="normal_wolf", v="villager")
    g.start(); g.dusk(); g.act("seer", "check", target="c"); g.night()
    assert "**Villagers**" in g.messages_for("seer")[-1]
    g.newspaper(); g.dusk(); g.act("seer", "check", target="c"); g.night()
    assert "**Cultist**" in g.messages_for("seer")[-1]


def test_seer_learns_grave_robber_role_before_robbing():
    g = build(seer="seer", gr="grave_robber", w="normal_wolf", v="villager")
    g.start(); g.dusk(); g.act("seer", "check", target="gr"); g.night()
    assert "**Grave Robber**" in g.messages_for("seer")[-1]


def test_seer_sees_the_state_from_before_a_same_night_turn():
    g = build(seer="seer", a1="ancient_wolf", a2="ancient_wolf", v="villager", v2="villager")
    g.start(); g.dusk()
    pack(g, "v", "a1", "a2"); g.act("a1", "turn")
    g.act("seer", "check", target="v")
    g.night()
    assert g.p("v").true_faction() == "werewolves"
    assert "**v** belongs to the **Villagers**" in g.messages_for("seer")[-1]


# --- Fox --------------------------------------------------------------------------

def test_fox_finds_a_non_villager():
    g = build(fox="fox", w="normal_wolf", v1="villager", v2="villager", v3="villager")
    g.start(); g.dusk()
    g.act("fox", "sniff", first="w", second="v1", third="v2"); g.night()
    assert "at least one is **not**" in g.messages_for("fox")[-1]
    assert g.p("fox").role.active


def test_fox_loses_ability_after_three_villagers():
    g = build(fox="fox", c="cultist", w="normal_wolf", v1="villager", v2="villager")
    g.start(); g.dusk()
    g.act("fox", "sniff", first="c", second="v1", third="v2"); g.night()   # the Cultist counts as a villager
    assert not g.p("fox").role.active
    g.newspaper(); g.dusk()
    with pytest.raises(GameError):
        g.act("fox", "sniff", first="w", second="v1", third="v2")


# --- Gambler ------------------------------------------------------------------------

def test_gambler_learns_the_role_and_dies_visiting_evil():
    g = build(gam="gambler", w="normal_wolf", v="villager", v2="villager")
    g.start(); g.dusk(); g.act("gam", "visit", target="v"); g.night()
    assert g.alive("gam") and "**Villager**" in g.messages_for("gam")[-1]
    g.newspaper(); g.dusk(); g.act("gam", "visit", target="w"); g.night()
    assert not g.alive("gam")
    assert g.p("gam").death.cause == "gambler"


def test_protected_gambler_survives_but_gms_are_alerted():
    g = build(gam="gambler", w="normal_wolf", angel="silver_angel", v="villager")
    g.start(); g.dusk()
    g.act("gam", "visit", target="w"); g.act("angel", "protect", target="gam")
    g.night()
    assert g.alive("gam")
    assert any(e.category == "GAMBLER" and e.alert for e in g.state.pending_logs)


# --- Monster Hunter -------------------------------------------------------------------

def test_monster_hunter_finds_silver_then_hunts_evil_only():
    g = build(mh="monster_hunter", angel="silver_angel", w="normal_wolf", c="cultist", v="villager", v2="villager")
    g.start(); g.dusk(); g.act("mh", "search", target="v"); g.night()
    assert not g.p("mh").role.has_silver
    g.newspaper(); g.dusk(); g.act("mh", "search", target="angel"); g.night()
    assert g.p("mh").role.has_silver
    g.newspaper(); g.dusk(); g.act("mh", "hunt", target="c"); g.night()
    assert g.alive("c")                                       # the Cultist isn't killed by the Monster Hunter
    g.newspaper(); g.dusk(); g.act("mh", "hunt", target="w"); g.night()
    assert not g.alive("w")


def test_armed_monster_hunter_kills_the_stalking_shadow_wolf_and_still_hunts():
    g = build(mh="monster_hunter", sw="shadow_wolf", w="normal_wolf", v="villager", v2="villager")
    g.start()
    g.p("mh").role.has_silver = True
    g.dusk()
    g.act("mh", "hunt", target="w")
    g.act("sw", "stalk", target="mh")
    g.night()
    assert not g.alive("sw") and not g.alive("w") and g.alive("mh")


# --- Locksmith ------------------------------------------------------------------------

def locked_game() -> GameBuilder:
    g = build(lock="locksmith", w1="normal_wolf", w2="normal_wolf", angel="silver_angel", hound="bloodhound",
              v1="villager", v2="villager", v3="villager")
    g.families(("v1", "v2", "angel"), ("lock", "w1", "w2", "hound", "v3"))
    g.start()
    return g


def test_lock_protects_the_whole_house_and_locks_everyone_in():
    g = locked_game(); g.dusk()
    g.act("lock", "lock", target="v1")
    pack(g, "v2", "w1", "w2", "hound")           # attacking a housemate of v1
    g.act("angel", "protect", target="v3")       # angel lives in the locked house
    g.night()
    assert g.alive("v2")
    assert action(g, "protect").status is ActionStatus.BLOCKED
    assert "locked" in g.last_report()


def test_locked_in_player_still_counts_as_leaving():
    g = build(lock="locksmith", ins="insomniac", angel="silver_angel", hound="bloodhound", w="normal_wolf",
              v="villager")
    g.families(("ins", "angel", "v"), ("lock", "hound", "w"))
    g.start(); g.dusk(); g.night(); g.newspaper()
    g.act("ins", "listen", mode="leaving"); g.dusk()
    g.act("lock", "lock", target="angel")
    g.act("angel", "protect", target="v")
    g.act("hound", "track", target="v")         # can't get into the locked house
    g.night()
    assert "**1** of your family members left" in g.messages_for("ins")[-1]
    assert action(g, "track").status is ActionStatus.BLOCKED
    assert "didn't work out" in g.messages_for("hound")[-1]


def test_locksmith_may_lock_own_house_but_never_the_same_person_twice():
    g = locked_game(); g.dusk()
    g.act("lock", "lock", target="lock")
    pack(g, "v3", "w1", "w2", "hound")           # v3 lives with the locksmith
    g.night()
    assert g.alive("v3")
    assert action(g, "lock").status is ActionStatus.RESOLVED   # the locksmith's own lock isn't blocked
    g.newspaper(); g.dusk()
    with pytest.raises(GameError, match="twice"):
        g.act("lock", "lock", target="lock")


# --- Trapmaker ----------------------------------------------------------------------

def test_trap_catches_a_random_wolf_and_makes_the_news():
    g = build(trap="trapmaker", w1="normal_wolf", w2="normal_wolf", v="villager", v2="villager", v3="villager")
    g.start(); g.dusk()
    g.act("trap", "trap", target="v"); pack(g, "v", "w1", "w2")
    g.night()
    assert not g.alive("v")                              # the attack still happens
    msg = g.messages_for("trap")[-1]
    assert "caught **w1**" in msg or "caught **w2**" in msg
    assert "A trap went off" in g.last_report()


def test_trap_is_on_the_person_not_the_house():
    g = build(trap="trapmaker", slut="village_slut", w="normal_wolf", v1="villager", v2="villager")
    g.families(("v1", "v2"), ("trap", "slut", "w"))
    g.start(); g.dusk()
    g.act("trap", "trap", target="v1")
    g.act("slut", "visit", target="v2")          # visits v1's housemate, not v1
    g.night()
    assert "Nobody walked into your trap" in g.messages_for("trap")[-1]


def test_trapmaker_can_trap_themselves():
    g = build(trap="trapmaker", slut="village_slut", w="normal_wolf", v="villager")
    g.start(); g.dusk()
    g.act("trap", "trap", target="trap"); g.act("slut", "visit", target="trap")
    g.night()
    assert "caught **slut**" in g.messages_for("trap")[-1]


# --- Wanderer -----------------------------------------------------------------------

def test_wanderer_spots_someone_and_can_follow_them():
    g = build(wan="wanderer", feral="feral_wolf", w="normal_wolf", v="villager", v2="villager")
    g.start(); g.dusk()
    with pytest.raises(GameError):
        g.act("wan", "wander", mode="same")
    g.act("wan", "wander"); g.act("feral", "eat", target="v")
    g.night()
    assert "spotted **feral**" in g.messages_for("wan")[-1]
    g.newspaper(); g.dusk()
    g.act("wan", "wander", mode="same")
    g.night()
    assert "stayed at home" in g.messages_for("wan")[-1]


# --- Insomniac -----------------------------------------------------------------------

def test_insomniac_hears_wolves_as_one_visitor():
    g = build(ins="insomniac", w1="normal_wolf", w2="normal_wolf", feral="feral_wolf", slut="village_slut",
              v="villager", v2="villager")
    g.families(("ins", "v"), ("w1", "w2", "feral", "slut", "v2"))
    g.start(); g.dusk(); g.night(); g.newspaper()
    g.act("ins", "listen", mode="visitors")
    g.dusk()
    pack(g, "v", "w1", "w2", "feral"); g.act("feral", "eat", target="ins"); g.act("slut", "visit", target="v")
    g.night()
    assert "heard **2** visitor(s)" in g.messages_for("ins")[-1]      # the wolves + the slut


def test_insomniac_counts_family_members_leaving():
    g = build(ins="insomniac", angel="silver_angel", hound="bloodhound", v="villager", w="normal_wolf")
    g.families(("ins", "angel", "hound", "v"), ("w",))
    g.start(); g.dusk(); g.night(); g.newspaper()
    g.act("ins", "listen", mode="leaving"); g.dusk()
    g.act("angel", "protect", target="v"); g.act("hound", "track", target="ins")   # visiting family still counts
    g.night()
    assert "**2** of your family members left" in g.messages_for("ins")[-1]


# --- Village Slut -------------------------------------------------------------------------

def slut_game() -> GameBuilder:
    g = build(slut="village_slut", w1="normal_wolf", w2="normal_wolf", vig="vigilante", witch="witch",
              ins="insomniac", v="villager", v2="villager")
    g.start(); g.dusk()
    return g


def test_slut_survives_an_attack_at_home():
    g = slut_game()
    g.act("slut", "visit", target="v"); pack(g, "slut", "w1", "w2")
    g.night()
    assert g.alive("slut") and "stayed at home" in g.messages_for("slut")[-1]


def test_slut_dies_with_the_attacked_host():
    g = slut_game()
    g.act("slut", "visit", target="v"); pack(g, "v", "w1", "w2")
    g.night()
    assert not g.alive("v") and not g.alive("slut")


def test_slut_dies_with_host_shot_by_the_vigilante():
    g = slut_game()
    g.act("slut", "visit", target="w1"); g.act("vig", "shoot", target="w1")
    g.night()
    assert not g.alive("w1") and not g.alive("slut")


def test_witch_potion_on_an_absent_slut_is_not_used():
    g = slut_game()
    g.act("slut", "visit", target="v"); g.act("witch", "poison", target="slut")
    g.night()
    assert g.alive("slut")
    assert g.p("witch").role.uses.get("poison", 0) == 0


def test_slut_is_turned_along_with_the_host():
    g = build(slut="village_slut", a1="ancient_wolf", a2="ancient_wolf", v="villager", v2="villager")
    g.start(); g.dusk()
    g.act("slut", "visit", target="v"); pack(g, "v", "a1", "a2"); g.act("a1", "turn")
    g.night()
    assert g.p("v").has_modifier("turned_wolf") and g.p("slut").has_modifier("turned_wolf")


def test_slut_and_insomniac_learn_each_others_roles():
    g = slut_game()
    g.act("slut", "visit", target="ins")
    g.night()
    assert any("**Insomniac**" in m for m in g.messages_for("slut"))
    assert any("**Village Slut**" in m for m in g.messages_for("ins"))


def test_heartbreak_like_deaths_dont_take_the_slut():
    g = slut_game()
    g.act("slut", "visit", target="vig"); g.act("vig", "shoot", target="v")   # vig dies of guilt (not an attack)
    g.night()
    assert not g.alive("vig") and g.alive("slut")


# --- Prophet ----------------------------------------------------------------------------

def test_prophet_gets_a_third_of_the_living():
    g = build(pro="prophet", w="normal_wolf", **{f"v{i}": "villager" for i in range(7)})
    g.start(); g.dusk(); g.act("pro", "pray", role="normal_wolf"); g.night()
    msg = g.messages_for("pro")[-1]
    names = msg.split(": ", 1)[1].rstrip(".").split(", ")
    assert len(names) == math.ceil(9 / 3) and "**w**" in names


def test_prophet_told_when_nobody_has_the_role():
    g = build(pro="prophet", w="normal_wolf", v="villager")
    g.start(); g.dusk(); g.act("pro", "pray", role="witch"); g.night()
    assert "nobody alive" in g.messages_for("pro")[-1]


# --- Undertaker ------------------------------------------------------------------------

def test_undertaker_learns_role_and_killer():
    g = build(und="undertaker", feral="feral_wolf", w="normal_wolf", v1="villager", v2="villager", v3="villager")
    g.start(); g.dusk()
    pack(g, "v1", "feral", "w"); g.act("feral", "eat", target="v2")
    g.night()
    g.act("und", "examine", target="v1")
    assert "killed by the werewolves" in g.messages_for("und")[-1]
    with pytest.raises(GameError, match="today"):
        g.act("und", "examine", target="v2")
    g.newspaper(); g.dusk(); g.night()
    g.act("und", "examine", target="v2")
    assert "killed by the **Feral wolf**" in g.messages_for("und")[-1]


# --- Old Hunter ------------------------------------------------------------------------

def test_coated_old_hunter_kills_an_attacking_wolf():
    g = build(oh="old_hunter", w1="normal_wolf", w2="normal_wolf", v="villager", v2="villager")
    g.start(); g.dusk()
    g.act("oh", "coat"); pack(g, "oh", "w1", "w2")
    g.night()
    assert g.alive("oh")
    assert (not g.alive("w1")) != (not g.alive("w2"))      # exactly one wolf dies
    assert "wolfsbane" in g.last_report()


def test_uncoated_old_hunter_dies():
    g = build(oh="old_hunter", w1="normal_wolf", w2="normal_wolf", v="villager")
    g.start(); g.dusk(); pack(g, "oh", "w1", "w2"); g.night()
    assert not g.alive("oh") and g.alive("w1") and g.alive("w2")


def test_coated_sword_stops_a_turn_and_kills_the_ancient_wolf():
    g = build(oh="old_hunter", a="ancient_wolf", w="normal_wolf", v="villager", v2="villager")
    g.start(); g.dusk()
    g.act("oh", "coat"); pack(g, "oh", "a", "w"); g.act("a", "turn")
    g.night()
    assert g.alive("oh") and not g.p("oh").has_modifier("turned_wolf")
    assert not g.alive("a") and g.alive("w")


def test_tracking_a_coated_old_hunter_is_safe():
    g = build(oh="old_hunter", hound="bloodhound", w="normal_wolf", v="villager", v2="villager")
    g.start(); g.dusk()
    g.act("oh", "coat"); g.act("hound", "track", target="oh")
    g.night()
    assert g.alive("hound")


# --- Vigilante --------------------------------------------------------------------------

def test_vigilante_guilt_only_for_villagers():
    g = build(vig="vigilante", w="normal_wolf", c="cultist", v="villager", v2="villager", v3="villager")
    g.start(); g.dusk(); g.act("vig", "shoot", target="w"); g.night()
    assert not g.alive("w") and g.alive("vig")
    g.newspaper(); g.dusk(); g.act("vig", "shoot", target="c"); g.night()   # the Cultist counts as a villager
    assert not g.alive("c") and not g.alive("vig")
    assert g.p("vig").death.cause == "guilt"


def test_vigilante_kills_a_stalking_shadow_wolf_and_still_shoots():
    g = build(vig="vigilante", sw="shadow_wolf", w="normal_wolf", v="villager", v2="villager")
    g.start(); g.dusk()
    g.act("vig", "shoot", target="w"); g.act("sw", "stalk", target="vig")
    g.night()
    assert not g.alive("sw") and not g.alive("w") and g.alive("vig")


# --- Witch -------------------------------------------------------------------------------

def test_witch_revives_last_nights_victim_after_the_lynch():
    g = build(witch="witch", w1="normal_wolf", w2="normal_wolf", v="villager", v2="villager", v3="villager")
    g.start(); g.dusk(); pack(g, "v", "w1", "w2"); g.night(); g.newspaper()
    g.act("witch", "revive", target="v")
    g.dusk()
    assert g.alive("v")
    with pytest.raises(GameError):
        g.act("witch", "poison", target="v2") if False else g.act("witch", "revive", target="v2")


def test_witch_cannot_revive_an_older_death():
    g = build(witch="witch", w1="normal_wolf", w2="normal_wolf", v="villager", v2="villager", v3="villager")
    g.start(); g.dusk(); pack(g, "v", "w1", "w2"); g.night(); g.newspaper(); g.dusk(); g.night(); g.newspaper()
    with pytest.raises(GameError, match="last night"):
        g.act("witch", "revive", target="v")


def test_witch_poison():
    g = build(witch="witch", w="normal_wolf", v="villager", v2="villager")
    g.start(); g.dusk(); g.act("witch", "poison", target="w"); g.night()
    assert not g.alive("w") and g.p("w").death.killer_role == "witch"


# --- Priest --------------------------------------------------------------------------------

def test_priest_blessing_protects_the_family_for_one_night():
    g = build(priest="priest", w1="normal_wolf", w2="normal_wolf", v1="villager", v2="villager", v3="villager")
    g.families(("v1", "v2"), ("priest", "w1", "w2", "v3"))
    g.start(); g.dusk(); g.night(); g.newspaper()
    g.act("priest", "bless", member="v1")
    g.dusk(); pack(g, "v2", "w1", "w2"); g.night()
    assert g.alive("v2")
    g.newspaper(); g.dusk(); pack(g, "v2", "w1", "w2"); g.night()      # the blessing has worn off
    assert not g.alive("v2")


def test_blessing_does_not_stop_turning():
    g = build(priest="priest", a1="ancient_wolf", a2="ancient_wolf", v="villager", v2="villager")
    g.start(); g.dusk(); g.night(); g.newspaper()
    g.act("priest", "bless", member="v"); g.dusk()
    pack(g, "v", "a1", "a2"); g.act("a1", "turn"); g.night()
    assert g.p("v").has_modifier("turned_wolf")
