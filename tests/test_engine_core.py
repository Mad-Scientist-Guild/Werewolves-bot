from datetime import datetime

import pytest

from Core import flow, voting
from Core.access import Access, player_access
from Core.actor import MODIFIER_REGISTRY, ROLE_REGISTRY
from Core.clock import TransitionKind, next_transition
from Core.effects import Announcement, DecisionPrompt
from Core.errors import GameError
from Core.state import ActionStatus, GroupKind, LifeState, Phase, PublicStatus
from Storage.codec import decode, encode
from tests.builder import TZ, GameBuilder


def basic_game() -> GameBuilder:
    g = GameBuilder()
    g.players(w1="ancient_wolf", w2="ancient_wolf", w3="ancient_wolf",
              angel="silver_angel", robber="grave_robber", v1="villager", v2="villager", cult="cultist")
    g.start()
    return g


# --- serialisation ------------------------------------------------------------

def test_every_role_and_modifier_round_trips():
    g = GameBuilder()
    for name in sorted(ROLE_REGISTRY):
        g.player(f"p_{name}", name)
    g.start()
    first = g.state.players[g.id("p_villager")]
    for name in sorted(MODIFIER_REGISTRY):
        flow.add_modifier(g.state, first, name)
    text = encode(g.state)
    restored = decode(text)
    assert encode(restored) == text
    assert restored.players[first.user_id].modifiers[0].name == sorted(MODIFIER_REGISTRY)[0]
    assert type(restored.players[first.user_id].role).__name__ == "Villager"


def test_unknown_role_survives_as_missing_actor():
    g = basic_game()
    data = encode(g.state).replace('"__type__":"cultist"', '"__type__":"deleted_role"')
    restored = decode(data)
    role = restored.player(g.id("cult")).role
    assert role.name == "_missing" and role.missing_name == "deleted_role"
    assert '"__type__":"deleted_role"' in encode(restored)  # nothing lost when saved again


# --- wolf pack ----------------------------------------------------------------

def test_wolves_need_a_majority_of_the_pack():
    g = basic_game()
    g.dusk()
    g.wolf_vote("w1", "v1")
    g.wolf_vote("w2", "v1")       # 2 of 3 -> majority
    g.night()
    assert not g.alive("v1")
    assert g.p("v1").death.killer_role == "werewolves"


def test_wolves_without_majority_eat_nobody():
    g = basic_game()
    g.dusk()
    g.wolf_vote("w1", "v1")       # 1 of 3, others don't vote (= abstain)
    g.night()
    assert g.alive("v1")


def test_wolf_tie_eats_nobody():
    g = GameBuilder()
    g.players(w1="ancient_wolf", w2="ancient_wolf", v1="villager", v2="villager")
    g.start(); g.dusk()
    g.wolf_vote("w1", "v1"); g.wolf_vote("w2", "v2")
    g.night()
    assert g.alive("v1") and g.alive("v2")


def test_cultist_cannot_vote_with_the_pack():
    g = basic_game()
    g.dusk()
    with pytest.raises(GameError):
        g.wolf_vote("cult", "v1")


# --- protection / turning -------------------------------------------------------

def test_silver_angel_protects_against_the_pack():
    g = basic_game()
    g.dusk()
    g.act("angel", "protect", target="v1")
    g.wolf_vote("w1", "v1"); g.wolf_vote("w2", "v1")
    g.night()
    assert g.alive("v1")
    assert "protected by the Silver Angel" in g.last_report()


def test_silver_angel_cannot_protect_same_person_twice_in_a_row():
    g = basic_game()
    g.dusk(); g.act("angel", "protect", target="v1"); g.night()
    g.newspaper(); g.dusk()
    with pytest.raises(GameError):
        g.act("angel", "protect", target="v1")
    g.act("angel", "protect", target="v2")


def test_ancient_wolf_turns_the_victim_instead():
    g = basic_game()
    g.dusk()
    g.wolf_vote("w1", "v1"); g.wolf_vote("w2", "v1")
    g.act("w3", "turn")
    g.night()
    victim = g.p("v1")
    assert victim.alive
    assert victim.has_modifier("turned_wolf") and victim.true_faction() == "werewolves"
    assert victim.can_vote_wolf_kill()
    assert g.state.groups["wolves"].members[victim.user_id].value == "active"
    # only the ancient wolf left the house
    assert "w1 visits" not in g.last_report()


def test_failed_turn_keeps_the_ability():
    g = basic_game()
    g.dusk()
    g.act("angel", "protect", target="v1")   # protection also stops turning
    g.wolf_vote("w1", "v1"); g.wolf_vote("w2", "v1")
    g.act("w3", "turn")
    g.night()
    assert g.alive("v1") and not g.p("v1").has_modifier("turned_wolf")
    assert g.p("w3").role.uses.get("turn", 0) == 0


def test_preview_matches_final_and_changes_nothing():
    g = basic_game()
    g.dusk()
    g.wolf_vote("w1", "v1"); g.wolf_vote("w2", "v1")
    preview = g.lock().preview
    assert g.alive("v1")                       # preview didn't kill anyone
    final = g.morning().reports[0][1]
    assert preview.report == final
    assert not g.alive("v1")


# --- grave robber & simultaneity ----------------------------------------------------

def test_grave_robber_day_plunder_resolves_at_dusk():
    g = basic_game()
    g.dusk(); g.wolf_vote("w1", "angel"); g.wolf_vote("w2", "angel"); g.night()
    g.act("robber", "rob", target="angel")
    assert g.p("robber").role_name == "grave_robber"
    g.dusk()
    robber = g.p("robber")
    assert robber.role_name == "silver_angel" and robber.original_role == "grave_robber"
    g.act("robber", "protect", target="v1")   # can use the night action straight away


def test_grave_robber_gets_the_role_only_when_it_resolves():
    g = basic_game()
    g.dusk(); g.wolf_vote("w1", "v1"); g.wolf_vote("w2", "v1"); g.night()
    g.act("robber", "rob", target="v1")
    with pytest.raises(GameError):
        g.act("robber", "protect", target="v2")   # not yet a silver angel
    g.dusk()
    assert g.p("robber").role_name == "villager"


def test_grave_robber_reads_state_from_before_the_moment():
    """Something that changes the dead player in the same resolution doesn't
    change what the Grave Robber gets."""
    g = basic_game()
    g.dusk(); g.wolf_vote("w1", "angel"); g.wolf_vote("w2", "angel"); g.night()
    g.newspaper(); g.dusk()
    g.act("robber", "rob", target="angel")      # night plunder
    # a GM changes the dead angel's role "at the same moment" via a commit; the robber
    # evaluated first and still gets the silver angel role
    from Core.resolution import register_prepare_hook, PREPARE_HOOKS

    def swap(ctx):
        if ctx.kind == "night":
            ctx.commit(lambda: flow.set_role(ctx.state, ctx.state.player(g.id("angel")), "villager"))

    register_prepare_hook(swap)
    try:
        g.night()
    finally:
        PREPARE_HOOKS.remove(swap)
    assert g.p("robber").role_name == "silver_angel"
    assert g.p("angel").role_name == "villager"


# --- actions ------------------------------------------------------------------

def test_night_actions_lock_at_sleep_time():
    g = basic_game()
    g.dusk(); g.lock()
    assert g.state.phase is Phase.SLEEP
    with pytest.raises(GameError, match="sleep time"):
        g.act("angel", "protect", target="v1")


def test_resubmitting_replaces_the_previous_choice():
    g = basic_game()
    g.dusk()
    first = g.act("angel", "protect", target="v1")
    second = g.act("angel", "protect", target="v2")
    assert first.status is ActionStatus.REPLACED and second.status is ActionStatus.PENDING


def test_nothing_happens_on_day_one():
    g = basic_game()
    with pytest.raises(GameError, match="first day"):
        g.act("robber", "rob", target="v1")


# --- lynch -----------------------------------------------------------------------

def to_day_two(g: GameBuilder) -> None:
    g.dusk(); g.night(); g.newspaper()


def test_lynch_majority_kills_and_reveals_faction():
    g = basic_game(); to_day_two(g)
    for voter in ("w1", "w2", "angel", "robber", "v2"):
        g.vote(voter, "v1")
    g.dusk()
    v1 = g.p("v1")
    assert v1.dead and v1.death.public
    assert v1.public_status is PublicStatus.DEAD    # lynch is public right away
    texts = [e.text for e in g.state.pending_effects if isinstance(e, Announcement)]
    assert any("lynched **v1**" in t and "Villagers" in t for t in texts)


def test_more_than_half_not_voting_means_no_lynch():
    g = basic_game(); to_day_two(g)
    g.vote("w1", "v1"); g.vote("w2", "v1"); g.vote("w3", "v1")   # 3 of 8 voted
    g.dusk()
    assert g.alive("v1")


def test_exactly_half_not_voting_still_lynches():
    g = basic_game(); to_day_two(g)
    for voter in ("w1", "w2", "w3", "angel"):                   # 4 of 8 voted
        g.vote(voter, "v1")
    g.dusk()
    assert not g.alive("v1")


def test_mayor_vote_breaks_a_lynch_tie():
    g = basic_game()
    g.state.mayor = g.id("angel")
    to_day_two(g)
    g.vote("w1", "v1"); g.vote("w2", "v1"); g.vote("angel", "v2"); g.vote("robber", "v2"); g.vote("w3", "cult")
    g.dusk()
    assert not g.alive("v2") and g.alive("v1")


def test_mayor_picks_when_their_vote_is_outside_the_tie():
    g = basic_game()
    g.state.mayor = g.id("angel")
    to_day_two(g)
    g.vote("w1", "v1"); g.vote("w2", "v1"); g.vote("w3", "v2"); g.vote("robber", "v2"); g.vote("angel", "cult")
    g.dusk()
    assert g.alive("v1") and g.alive("v2")
    decision = flow.open_decisions(g.state)[0]
    assert decision.chooser == g.id("angel") and sorted(decision.options) == sorted([g.id("v1"), g.id("v2")])
    assert any(isinstance(e, DecisionPrompt) for e in g.state.pending_effects)
    with pytest.raises(GameError):
        flow.resolve_decision(g.state, decision.id, g.id("v1"), by=g.id("w1"))   # not the mayor
    flow.resolve_decision(g.state, decision.id, g.id("v1"), by=g.id("angel"))
    assert not g.alive("v1")


def test_skeletons_and_dead_cannot_vote():
    g = basic_game(); to_day_two(g)
    g.p("v2").life = LifeState.SKELETON
    with pytest.raises(GameError):
        g.vote("v2", "v1")


def test_second_lynch_counselor_picks_on_tie():
    g = basic_game(); to_day_two(g)
    g.dusk()
    flow._open_second_lynch(g.state, g.id("angel"))
    assert g.state.lockdown
    g.vote("w1", "v1", voting.LYNCH2); g.vote("w2", "v2", voting.LYNCH2)
    with pytest.raises(GameError):
        g.vote("w3", None, voting.LYNCH2)     # no abstaining
    g.second_lynch_end()
    decision = flow.open_decisions(g.state)[0]
    assert decision.kind == "lynch2_tiebreak" and decision.chooser == g.id("angel")
    flow.resolve_decision(g.state, decision.id, g.id("v2"), by=g.id("angel"))
    assert not g.alive("v2") and not g.state.lockdown


# --- quiet deaths & public statuses ---------------------------------------------------

def test_night_death_is_quiet_until_the_newspaper():
    g = basic_game()
    g.state.data["first_death_seen"] = True   # not the first death (that one becomes a Vengeful Spirit)
    g.dusk(); g.wolf_vote("w1", "v1"); g.wolf_vote("w2", "v1"); g.night()
    v1 = g.p("v1")
    assert v1.dead and v1.public_status is PublicStatus.NONE
    dead_chat = g.state.groups["dead"]
    assert player_access(g.state, dead_chat, v1) is Access.WRITE
    assert player_access(g.state, g.state.groups["village"], v1) is Access.READ
    g.newspaper()
    assert v1.public_status is PublicStatus.DEAD


def test_access_rules():
    g = basic_game()
    state = g.state
    wolves = state.groups["wolves"]
    w1, v1, cult = g.p("w1"), g.p("v1"), g.p("cult")
    assert player_access(state, wolves, w1) is Access.WRITE
    assert player_access(state, wolves, cult) is Access.WRITE
    assert player_access(state, wolves, v1) is Access.NONE
    wolves.leave(w1.user_id)
    assert player_access(state, wolves, w1) is Access.READ      # never made inaccessible
    private = state.groups[w1.private_group]
    w1.life = LifeState.DEAD
    assert player_access(state, private, w1) is Access.WRITE    # can always talk to the GMs
    state.lockdown = True
    assert player_access(state, state.groups["village"], v1) is Access.READ
    v1.life = LifeState.SKELETON
    state.lockdown = False
    assert player_access(state, state.groups["village"], v1) is Access.REACT
    assert player_access(state, state.groups["dead"], v1) is Access.NONE


def test_private_channels_are_named_after_starting_role():
    g = basic_game()
    names = sorted(gr.name for gr in g.state.groups_of_kind(GroupKind.PRIVATE))
    assert "ancient-wolf" in names and "ancient-wolf-2" in names and "silver-angel" in names


# --- clock --------------------------------------------------------------------

def test_clock_sequence():
    g = basic_game()
    nt = g.state.next_transition
    assert nt.kind == TransitionKind.NEWSPAPER.value and nt.at.startswith("2026-10-05T12:00")
    g.newspaper()
    assert g.state.next_transition.kind == TransitionKind.DUSK.value
    g.dusk()
    assert g.state.next_transition.kind == TransitionKind.NIGHT_LOCK.value
    assert g.state.next_transition.at.startswith("2026-10-06T00:00")
    g.lock()
    assert g.state.next_transition.kind == TransitionKind.MORNING.value


def test_clock_catch_up_follows_scheduled_times():
    g = basic_game()
    g.state.phase = Phase.SLEEP
    after = datetime(2026, 10, 6, 0, 0, tzinfo=TZ)
    nt = next_transition(g.state, after)
    assert nt.kind == "morning" and nt.at.startswith("2026-10-06T08:00")
