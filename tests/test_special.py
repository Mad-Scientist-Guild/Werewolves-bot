from datetime import timedelta

import pytest

from Core import actions, gm_tools, realtime, voting
from Core.access import Access, player_access
from Core.effects import Announcement, PrivateMessage, QuestionPrompt, TelepathPrompt
from Core.errors import GameError
from Core.factions import winners
from Core.state import PublicRole
from tests.builder import GameBuilder


def build(**roles: str) -> GameBuilder:
    g = GameBuilder()
    g.players(**roles)
    return g


def pack(g: GameBuilder, victim: str, *wolves: str) -> None:
    for wolf in wolves:
        g.wolf_vote(wolf, victim)


def announcements(g: GameBuilder) -> list[str]:
    return [e.text for e in g.state.pending_effects if isinstance(e, Announcement)]


# --- Cupid & lovers -----------------------------------------------------------------

def lovers_game() -> GameBuilder:
    g = build(cupid="cupid", w1="normal_wolf", w2="normal_wolf", a="villager", b="villager",
              v1="villager", v2="villager", v3="villager")
    g.state.data["first_death_seen"] = True
    g.start(); g.dusk()
    g.act("cupid", "link", first="a", second="b")
    return g


def test_cupid_links_two_lovers_on_the_first_night_only():
    g = lovers_game(); g.night()
    a, b = g.p("a"), g.p("b")
    assert a.modifier("lover").partner == b.user_id and a.true_faction() == "lovers"
    lovers_chat = g.state.chats[f"lovers:{g.id('cupid')}"]
    assert player_access(g.state, lovers_chat, a) is Access.WRITE
    assert player_access(g.state, lovers_chat, g.p("cupid")) is Access.NONE    # Cupid isn't in the chat
    g.newspaper(); g.dusk()
    with pytest.raises(GameError):
        g.act("cupid", "link", first="v1", second="v2")


def test_heartbreak_and_cupid_joins_the_villagers():
    g = lovers_game(); g.night(); g.newspaper(); g.dusk()
    pack(g, "a", "w1", "w2")
    g.night()
    assert not g.alive("a") and not g.alive("b")
    assert g.p("b").death.cause == "heartbreak"
    assert g.p("cupid").faction == "villagers"


def test_priest_blessing_does_not_stop_heartbreak():
    g = build(cupid="cupid", priest="priest", w1="normal_wolf", w2="normal_wolf", a="villager", b="villager",
              v="villager")
    g.state.data["first_death_seen"] = True
    g.families(("a",), ("b", "priest"), ("cupid", "w1", "w2", "v"))
    g.start(); g.dusk(); g.act("cupid", "link", first="a", second="b"); g.night(); g.newspaper()
    g.act("priest", "bless", member="b"); g.dusk()
    pack(g, "a", "w1", "w2"); g.night()
    assert not g.alive("b")


def test_cupid_survives_a_lynch_while_the_lovers_live():
    g = lovers_game(); g.night(); g.newspaper()
    for voter in ("w1", "w2", "a", "b", "v1", "v2"):
        g.vote(voter, "cupid")
    g.dusk()
    assert g.alive("cupid")
    assert any("is **Cupid**" in t for t in announcements(g))


def test_cupid_can_link_themselves():
    g = build(cupid="cupid", w="normal_wolf", a="villager", v="villager")
    g.start(); g.dusk(); g.act("cupid", "link", first="cupid", second="a"); g.night()
    assert g.p("cupid").modifier("lover").partner == g.id("a")


def test_turned_lover_does_not_die_of_heartbreak_but_partner_does():
    g = build(cupid="cupid", an="ancient_wolf", w="normal_wolf", a="villager", b="villager", v="villager",
              v2="villager")
    g.state.data["first_death_seen"] = True
    g.start(); g.dusk()
    g.act("cupid", "link", first="a", second="b"); pack(g, "a", "an", "w"); g.act("an", "turn")
    g.night()
    a, b = g.p("a"), g.p("b")
    assert a.true_faction() == "werewolves" and b.modifier("lover").bond_broken
    g.newspaper(); g.dusk(); pack(g, "b", "an", "w", "a"); g.night()        # b dies, turned a lives on
    assert not g.alive("b") and g.alive("a")
    assert g.p("b").has_modifier("vengeful_spirit")                          # dies while turned partner lives
    assert g.p("b").modifier("vengeful_spirit").allowed == [g.id("an")]      # must name the Ancient wolf


def test_betrayed_lover_becomes_a_vengeful_spirit():
    g = build(cupid="cupid", slut="village_slut", w1="normal_wolf", w2="normal_wolf", a="villager", v="villager")
    g.state.data["first_death_seen"] = True
    g.start(); g.dusk()
    g.act("cupid", "link", first="slut", second="a"); g.night(); g.newspaper(); g.dusk()
    g.act("slut", "visit", target="v"); pack(g, "v", "w1", "w2")             # the slut dies cheating
    g.night()
    assert not g.alive("slut") and not g.alive("a")
    assert g.p("a").has_modifier("vengeful_spirit")


def test_revived_lover_returns_to_original_faction():
    g = lovers_game(); g.night(); g.newspaper(); g.dusk()
    pack(g, "a", "w1", "w2"); g.night()
    gm_tools.gm_revive(g.state, g.id("a"))
    assert g.p("a").true_faction() == "villagers"


def test_lovers_win_when_they_are_the_last():
    g = lovers_game(); g.night()
    for name in ("w1", "w2", "v1", "v2", "v3"):
        gm_tools.gm_kill(g.state, g.id(name))
    assert "lovers" in winners(g.state)


# --- Vengeful Spirit -----------------------------------------------------------------

def spirit_game() -> GameBuilder:
    g = build(spirit="spiritualist", w1="normal_wolf", w2="normal_wolf", feral="feral_wolf",
              a="villager", b="villager", c="villager", d="villager")
    g.start(); g.dusk()
    return g


def test_all_first_deaths_become_vengeful_spirits():
    g = spirit_game()
    pack(g, "a", "w1", "w2", "feral"); g.act("feral", "eat", target="b")
    g.night()
    for name in ("a", "b"):
        p = g.p(name)
        assert p.has_modifier("vengeful_spirit")
        assert player_access(g.state, g.state.chats["dead"], p) is Access.NONE
        line = g.state.chats[f"spirit:{p.user_id}"]
        assert player_access(g.state, line, p) is Access.WRITE
        assert player_access(g.state, line, g.p("spirit")) is Access.WRITE
    g.newspaper()
    assert g.p("a").public_role is PublicRole.VENGEFUL_SPIRIT
    # later deaths are ordinary
    g.dusk(); pack(g, "c", "w1", "w2", "feral"); g.night()
    assert not g.p("c").has_modifier("vengeful_spirit")


def test_pack_victim_spirit_can_avenge_on_any_wolf():
    g = spirit_game()
    pack(g, "a", "w1", "w2", "feral"); g.night(); g.newspaper(); g.dusk()
    g.act("a", "avenge", target="w2")
    g.night()
    assert not g.alive("w2")
    spirit = g.p("a").modifier("vengeful_spirit")
    assert not spirit.active
    assert player_access(g.state, g.state.chats["dead"], g.p("a")) is Access.WRITE   # moved on


def test_feral_victim_spirit_must_name_the_feral_wolf():
    g = spirit_game()
    g.act("feral", "eat", target="b"); g.night(); g.newspaper(); g.dusk()
    g.act("b", "avenge", target="w1")
    g.night()
    assert g.alive("w1") and not g.p("b").modifier("vengeful_spirit").active


def test_spirit_gets_three_nights():
    g = spirit_game()
    pack(g, "a", "w1", "w2", "feral"); g.night()
    for _ in range(3):
        assert g.p("a").modifier("vengeful_spirit").active
        g.newspaper(); g.dusk(); g.night()
    assert not g.p("a").modifier("vengeful_spirit").active


def test_gm_kills_dont_make_spirits():
    g = spirit_game()
    gm_tools.gm_kill(g.state, g.id("a"))
    assert not g.p("a").has_modifier("vengeful_spirit")


# --- Brothers --------------------------------------------------------------------------

def test_brothers_add_someone_unanimously():
    g = build(b1="brother", b2="brother", b3="brother", x="villager", w="normal_wolf")
    g.start()
    g.act("b1", "invite", target="x"); g.act("b2", "invite", target="x")
    brothers = g.state.chats["brothers"]
    assert g.id("x") not in brothers.active_members()
    g.act("b3", "invite", target="x")
    assert g.id("x") in brothers.active_members()
    assert g.p("x").role_name == "villager"


# --- Pacifist & Ruthless Counselor --------------------------------------------------------

def day_two(**roles) -> GameBuilder:
    g = build(**roles)
    g.state.data["first_death_seen"] = True
    g.start(); g.dusk(); g.night(); g.newspaper()
    return g


def test_pacifist_stops_the_lynch_and_learns_the_faction():
    g = day_two(pac="pacifist", w="normal_wolf", v1="villager", v2="villager", v3="villager")
    for voter in ("pac", "v1", "v2", "v3"):
        g.vote(voter, "w")
    g.act("pac", "stop")
    g.dusk()
    assert g.alive("w")
    assert "belongs to the **Werewolves**" in g.messages_for("pac")[-1]
    assert any("vote has been stopped" in t for t in announcements(g))


def test_ruthless_counselor_second_lynch():
    g = day_two(rc="ruthless_counselor", w="normal_wolf", v1="villager", v2="villager", v3="villager")
    g.act("rc", "second_lynch")
    g.dusk()
    assert g.state.lockdown and g.state.ballots["lynch2"].is_open
    for voter in ("rc", "v1", "v2"):
        g.vote(voter, "w", voting.LYNCH2)
    g.second_lynch_end()
    assert not g.alive("w") and not g.state.lockdown
    g.lock(); g.morning(); g.newspaper()
    with pytest.raises(GameError, match="two days in a row"):
        g.act("rc", "second_lynch")


# --- Peeking Girl (eavesdrops) ---------------------------------------------------------------

def test_peeking_girl_gets_a_numbered_transcript():
    g = build(peek="peeking_girl", w1="normal_wolf", w2="normal_wolf", hound="bloodhound", v="villager")
    g.start(); g.dusk()                                   # 19:00, night 1
    g.act("peek", "peek", start="21:00")
    with pytest.raises(GameError, match="once per day"):
        g.act("peek", "peek", start="22:30")
    eavesdrop = g.state.eavesdrops[0]
    t0 = g.now.replace(hour=21, minute=59)                # first message 1 minute before the window ends
    realtime.capture(g.state, "wolves", g.id("w2"), t0, "let's eat v")
    realtime.capture(g.state, "wolves", g.id("w1"), t0 + timedelta(minutes=10), "ok")
    realtime.capture(g.state, "wolves", g.id("w2"), t0 + timedelta(minutes=16), "too late")
    assert not realtime.due_eavesdrops(g.state, t0 + timedelta(minutes=14))   # capture runs past the window
    due = realtime.due_eavesdrops(g.state, t0 + timedelta(minutes=16))
    assert due == [eavesdrop]
    realtime.finish_eavesdrop(g.state, eavesdrop)
    text = [e.text for e in g.state.pending_effects if isinstance(e, PrivateMessage)][-1]
    assert "`21:59` **Speaker 1:** let's eat v" in text and "**Speaker 2:** ok" in text and "too late" not in text
    # the same wolf keeps the same number another day
    assert realtime.speaker_number(g.state, eavesdrop, g.id("w2")) == 1


def test_silent_window_is_reported():
    g = build(peek="peeking_girl", w="normal_wolf", v="villager")
    g.start(); g.dusk(); g.act("peek", "peek", start="21:00")
    eavesdrop = g.state.eavesdrops[0]
    assert realtime.due_eavesdrops(g.state, g.now.replace(hour=22, minute=1)) == [eavesdrop]
    realtime.finish_eavesdrop(g.state, eavesdrop)
    assert "nothing was said" in [e.text for e in g.state.pending_effects if isinstance(e, PrivateMessage)][-1]


def test_spying_counts_as_leaving_the_house():
    g = build(peek="peeking_girl", hound="bloodhound", w="normal_wolf", v="villager")
    g.start(); g.dusk(); g.act("peek", "peek", start="21:00"); g.act("hound", "track", target="peek")
    g.night()
    assert "**peek** left their house" in g.messages_for("hound")[-1]


# --- Spiritualist -----------------------------------------------------------------------

def test_dead_question_counts_answers_from_the_dead():
    g = spirit_game()
    g.state.data["first_death_seen"] = True
    pack(g, "a", "w1", "w2", "feral"); g.act("feral", "eat", target="b"); g.night()
    g.act("spirit", "ask", question="Was it a wolf?")
    question = g.state.questions[0]
    assert sorted(question.voters) == sorted([g.id("a"), g.id("b")])
    assert any(isinstance(e, QuestionPrompt) for e in g.state.pending_effects)
    with pytest.raises(GameError):
        realtime.answer_question(g.state, question.id, g.id("c"), True)        # the living can't answer
    realtime.answer_question(g.state, question.id, g.id("a"), True)
    realtime.answer_question(g.state, question.id, g.id("b"), False)
    assert question.done
    assert "**1× yes**, **1× no**" in [e.text for e in g.state.pending_effects if isinstance(e, PrivateMessage)][-1]
    with pytest.raises(GameError, match="today"):
        g.act("spirit", "ask", question="Again?")


def test_vengeful_spirit_does_not_answer_dead_questions():
    g = spirit_game()
    pack(g, "a", "w1", "w2", "feral"); g.night()               # a is a vengeful spirit
    g.act("spirit", "ask", question="Anyone there?")
    assert g.state.questions[0].done and g.state.questions[0].voters == []


# --- Telepath -----------------------------------------------------------------------------

def test_telepath_message_and_one_reply():
    g = day_two(tele="telepath", w="normal_wolf", v="villager", v2="villager")
    with pytest.raises(GameError, match="20"):
        g.act("tele", "send", target="v", message=" ".join(["word"] * 21))
    g.act("tele", "send", target="v", message="Who do you trust?")
    msg = g.state.telepath_messages[0]
    assert any(isinstance(e, TelepathPrompt) for e in g.state.pending_effects)
    with pytest.raises(GameError):
        realtime.reply_telepath_message(g.state, msg.id, g.id("v2"), "not mine", g.now)
    realtime.reply_telepath_message(g.state, msg.id, g.id("v"), "nobody", g.now)
    with pytest.raises(GameError):
        realtime.reply_telepath_message(g.state, msg.id, g.id("v"), "again", g.now)
    assert "answered: “nobody”" in g.messages_for("tele")[-1]


# --- Actor -------------------------------------------------------------------------------------

def test_actor_plays_a_role_for_a_day_and_night():
    g = day_two(act="actor", w="normal_wolf", v="villager", v2="villager")
    g.act("act", "copy", role="seer")
    # the copied role's own command group works for the Actor
    actor, ability = actions.find_ability(g.state, g.p("act"), "check", source="seer")
    assert actor.name == "actor"
    g.dusk()
    actions.submit(g.state, g.id("act"), "check", {"target": g.id("w")}, now=g.now, source="seer")
    g.night()
    assert "**Werewolves**" in g.messages_for("act")[-1]
    with pytest.raises(GameError):        # the copy is over the next day
        actions.find_ability(g.state, g.p("act"), "check", source="seer")
    with pytest.raises(GameError, match="never the same"):
        g.act("act", "copy", role="seer")


def test_actor_cannot_copy_some_roles():
    g = day_two(act="actor", w="normal_wolf", v="villager")
    for role in ("brother", "cupid", "grave_robber", "adopted_child", "normal_wolf"):
        with pytest.raises(GameError):
            g.act("act", "copy", role=role)


def test_actor_as_monster_hunter_has_no_silver():
    g = day_two(act="actor", w="normal_wolf", v="villager", v2="villager")
    g.act("act", "copy", role="monster_hunter")
    assert g.p("act").role.current.has_silver is False
    assert [a.key for a in g.p("act").role.available_abilities(g.state)] == ["search"]
