"""Engine side of the real-time features: eavesdropping eavesdrops (Peeking Girl,
Diviner), the Spiritualist's questions and the Telepath's messages.

Pure state changes; the Discord side (capturing messages, buttons, the
timer loop) lives in Cogs/realtime.py and Services/views.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from Core.access import Access, player_access
from Core.clock import TransitionKind, game_day_at, times, zone
from Core.effects import PrivateMessage, QuestionPrompt, TelepathPrompt
from Core.errors import GameError
from Core.state import GameState, Eavesdrop, OverheardMessage, YesNoQuestion, TelepathMessage

WINDOW_MINUTES = 60
CAPTURE_MINUTES = 15


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def next_occurrence(state: GameState, hhmm: str, now: datetime) -> datetime:
    """The next moment the clock shows HH:MM (today if still ahead, else tomorrow)."""
    hours, minutes = (int(x) for x in hhmm.split(":"))
    local = now.astimezone(zone(state))
    at = local.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    if at <= local:
        at += timedelta(days=1)
    return at


# --- eavesdrops ---------------------------------------------------------------------

def schedule_eavesdrop(state: GameState, listener: int, source_chat: str, start: datetime, *, purpose: str,
                   now: datetime, window_minutes: int = WINDOW_MINUTES,
                   capture_minutes: int = CAPTURE_MINUTES) -> Eavesdrop:
    if start <= now:
        raise GameError("The time you pick must be in the future.")
    if source_chat not in state.chats:
        raise GameError("There's nothing to listen in on.")
    eavesdrop = Eavesdrop(
        id=state.next_id("eavesdrop"), listener=listener, source_chat=source_chat,
        window_start=start.isoformat(), window_end=(start + timedelta(minutes=window_minutes)).isoformat(),
        purpose=purpose, night=game_day_at(state, start, now), capture_minutes=capture_minutes,
    )
    state.eavesdrops.append(eavesdrop)
    state.log("EAVESDROP", f"{state.name(listener)} will listen in on {state.chats[source_chat].name} from "
                       f"{start:%a %H:%M} for {window_minutes} minutes ({purpose}).", actor=listener)
    return eavesdrop


def capture(state: GameState, chat_key: str, speaker: int, at: datetime, text: str) -> list[Eavesdrop]:
    """Offer a message posted in a group chat to every active eavesdrop on it.
    The caller checks that the speaker is a member of the group."""
    taken = []
    for eavesdrop in state.eavesdrops:
        if eavesdrop.done or eavesdrop.source_chat != chat_key or speaker == eavesdrop.listener:
            continue
        if eavesdrop.capture_until is None:
            if not (_dt(eavesdrop.window_start) <= at <= _dt(eavesdrop.window_end)):
                continue
            # capture runs a full 15 minutes from the first message, even past the window's end
            eavesdrop.capture_until = (at + timedelta(minutes=eavesdrop.capture_minutes)).isoformat()
            state.log("EAVESDROP", f"Listening started for {state.name(eavesdrop.listener)} ({eavesdrop.purpose}).",
                      actor=eavesdrop.listener)
        if at <= _dt(eavesdrop.capture_until):
            eavesdrop.messages.append(OverheardMessage(speaker=speaker, at=at.isoformat(), text=text))
            taken.append(eavesdrop)
    return taken


def due_eavesdrops(state: GameState, now: datetime) -> list[Eavesdrop]:
    return [
        r for r in state.eavesdrops if not r.done and (
            (r.capture_until is not None and now > _dt(r.capture_until))
            or (r.capture_until is None and now > _dt(r.window_end))
        )
    ]


def speaker_number(state: GameState, eavesdrop: Eavesdrop, speaker: int) -> int:
    """Numbers stay the same for the same listener across uses."""
    aliases = state.aliases.setdefault(f"{eavesdrop.listener}:{eavesdrop.source_chat}", {})
    if speaker not in aliases:
        aliases[speaker] = len(aliases) + 1
    return aliases[speaker]


def transcript(state: GameState, eavesdrop: Eavesdrop) -> str:
    tz = zone(state)
    start = _dt(eavesdrop.window_start).astimezone(tz)
    end = _dt(eavesdrop.window_end).astimezone(tz)
    if not eavesdrop.messages:
        return f"You listened from {start:%H:%M} to {end:%H:%M}, but nothing was said."
    lines = []
    for message in eavesdrop.messages:
        number = speaker_number(state, eavesdrop, message.speaker)
        lines.append(f"`{_dt(message.at).astimezone(tz):%H:%M}` **Speaker {number}:** {message.text}")
    first = _dt(eavesdrop.messages[0].at).astimezone(tz)
    until = _dt(eavesdrop.capture_until).astimezone(tz)
    return f"What you overheard ({first:%H:%M}–{until:%H:%M}):\n" + "\n".join(lines)


def finish_eavesdrop(state: GameState, eavesdrop: Eavesdrop) -> None:
    eavesdrop.done = True
    title = {"peeking_girl": "👂 What the wolves said", "diviner": "🔮 Your scrying"}.get(eavesdrop.purpose, "👂 Overheard")
    state.emit(PrivateMessage(player=eavesdrop.listener, title=title, text=transcript(state, eavesdrop)))
    state.log("EAVESDROP", f"Transcript sent to {state.name(eavesdrop.listener)} ({len(eavesdrop.messages)} messages).",
              actor=eavesdrop.listener)


# --- questions --------------------------------------------------------------------

def dead_question_deadline(state: GameState, now: datetime) -> datetime:
    """End of daytime (19:00) or end of nighttime (00:00), whichever comes first."""
    schedule = times(state.settings.schedule)
    candidates = []
    for kind in (TransitionKind.DUSK, TransitionKind.NIGHT_LOCK):
        hhmm = schedule[kind].strftime("%H:%M")
        candidates.append(next_occurrence(state, hhmm, now))
    return min(candidates)


def ask_the_dead(state: GameState, asker: int, text: str, now: datetime) -> YesNoQuestion:
    """The Spiritualist's question: every dead player in the dead chat may answer."""
    dead_chat = state.chats.get("dead")
    voters = [p.user_id for p in state.dead_players()
              if dead_chat is not None and player_access(state, dead_chat, p) is Access.WRITE]
    question = YesNoQuestion(id=state.next_id("question"), asker=asker, text=text, asked_at=now.isoformat(),
                             deadline=dead_question_deadline(state, now).isoformat(), voters=voters)
    state.questions.append(question)
    state.log("QUESTION", f"{state.name(asker)} asks the dead: “{text}” ({len(voters)} may answer).", actor=asker)
    if voters:
        state.emit(QuestionPrompt(question_id=question.id))
    else:
        close_question(state, question, "there are no dead to answer")
    return question


def answer_question(state: GameState, question_id: int, voter: int, yes: bool) -> YesNoQuestion:
    question = next((s for s in state.questions if s.id == question_id), None)
    if question is None or question.done:
        raise GameError("This question has already been answered.")
    if voter not in question.voters:
        raise GameError("You can't answer this question.")
    question.answers[voter] = yes
    state.log("QUESTION", f"{state.name(voter)} answered question #{question.id}.", actor=voter)
    if set(question.answers) >= set(question.voters):
        close_question(state, question, "everyone has answered")
    return question


def due_questions(state: GameState, now: datetime) -> list[YesNoQuestion]:
    return [s for s in state.questions if not s.done and now >= _dt(s.deadline)]


def close_question(state: GameState, question: YesNoQuestion, reason: str) -> None:
    question.done = True
    yes = sum(1 for v in question.answers.values() if v)
    no = sum(1 for v in question.answers.values() if not v)
    silent = len(question.voters) - len(question.answers)
    if question.kind == "open_book":
        target = question.voters[0]
        answer = "**yes**" if yes else "**no**" if no else "nothing (they didn't answer in time)"
        state.emit(PrivateMessage(player=question.asker, title="📖 Charm of the Open Book",
                                  text=f"**{state.name(target)}** answered “{question.text}” with {answer}."))
    else:
        text = f"The dead have answered “{question.text}”:\n**{yes}× yes**, **{no}× no**"
        if silent:
            text += f" ({silent} didn't answer)"
        state.emit(PrivateMessage(player=question.asker, title="🕯️ The spirits speak", text=text))
    state.log("QUESTION", f"Question #{question.id} closed ({reason}): {yes} yes, {no} no, {silent} silent.",
              actor=question.asker)


def ask_player(state: GameState, asker: int, target: int, text: str, now: datetime, *,
               kind: str = "open_book") -> YesNoQuestion:
    """A yes/no question one player must answer honestly (Charm of the Open Book).
    Open until the next morning."""
    player = state.player(target)
    morning = times(state.settings.schedule)[TransitionKind.MORNING].strftime("%H:%M")
    question = YesNoQuestion(id=state.next_id("question"), asker=asker, text=text, asked_at=now.isoformat(),
                             deadline=next_occurrence(state, morning, now).isoformat(), voters=[target], kind=kind,
                             where=player.private_chat or "dead")
    state.questions.append(question)
    state.emit(QuestionPrompt(question_id=question.id))
    state.log("QUESTION", f"{state.name(asker)} asks {state.name(target)} ({kind}): “{text}”", actor=asker,
              targets=[target])
    return question


# --- telepathy ------------------------------------------------------------------

MAX_WORDS = 20


def send_telepath_message(state: GameState, sender: int, target: int, text: str, now: datetime) -> TelepathMessage:
    message = TelepathMessage(id=state.next_id("telepath_message"), sender=sender, target=target, text=text,
                               sent_at=now.isoformat())
    state.telepath_messages.append(message)
    state.emit(TelepathPrompt(telepath_message_id=message.id))
    state.log("TELEPATH", f"{state.name(sender)} → {state.name(target)}: “{text}”", actor=sender, targets=[target])
    return message


def reply_telepath_message(state: GameState, telepath_message_id: int, replier: int, text: str, now: datetime) -> TelepathMessage:
    message = next((m for m in state.telepath_messages if m.id == telepath_message_id), None)
    if message is None or message.target != replier:
        raise GameError("This message wasn't meant for you.")
    if message.reply is not None:
        raise GameError("You've already replied.")
    if not state.player(replier).alive:
        raise GameError("You can't reply any more.")
    words = len(text.split())
    if words == 0 or words > MAX_WORDS:
        raise GameError(f"Your reply must be 1–{MAX_WORDS} words (it's {words}).")
    message.reply = text.strip()
    message.replied_at = now.isoformat()
    state.emit(PrivateMessage(player=message.sender, title="📨 A reply reached you",
                              text=f"**{state.name(replier)}** answered: “{message.reply}”"))
    state.log("TELEPATH", f"{state.name(replier)} replied to {state.name(message.sender)}: “{message.reply}”",
              actor=replier, targets=[message.sender])
    return message


def eavesdrops_for_night(state: GameState, night: int) -> list[Eavesdrop]:
    return [r for r in state.eavesdrops if r.night == night]
