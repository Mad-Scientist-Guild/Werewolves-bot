"""Engine side of the real-time features: eavesdropping relays (Peeking Girl,
Diviner), the Spiritualist's seances and the Telepath's messages.

Pure state changes; the Discord side (capturing messages, buttons, the
timer loop) lives in Cogs/realtime.py and Services/views.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from Core.access import Access, player_access
from Core.clock import TransitionKind, game_day_at, times, zone
from Core.effects import PrivateMessage, SeancePrompt, TelepathyPrompt
from Core.errors import GameError
from Core.state import GameState, Relay, RelayMessage, Seance, TelepathyMessage

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


# --- relays ---------------------------------------------------------------------

def schedule_relay(state: GameState, listener: int, source_group: str, start: datetime, *, purpose: str,
                   now: datetime, window_minutes: int = WINDOW_MINUTES,
                   capture_minutes: int = CAPTURE_MINUTES) -> Relay:
    if start <= now:
        raise GameError("The time you pick must be in the future.")
    if source_group not in state.groups:
        raise GameError("There's nothing to listen in on.")
    relay = Relay(
        id=state.next_id("relay"), listener=listener, source_group=source_group,
        window_start=start.isoformat(), window_end=(start + timedelta(minutes=window_minutes)).isoformat(),
        purpose=purpose, night=game_day_at(state, start, now), capture_minutes=capture_minutes,
    )
    state.relays.append(relay)
    state.log("RELAY", f"{state.name(listener)} will listen in on {state.groups[source_group].name} from "
                       f"{start:%a %H:%M} for {window_minutes} minutes ({purpose}).", actor=listener)
    return relay


def capture(state: GameState, group_key: str, speaker: int, at: datetime, text: str) -> list[Relay]:
    """Offer a message posted in a group chat to every active relay on it.
    The caller checks that the speaker is a member of the group."""
    taken = []
    for relay in state.relays:
        if relay.done or relay.source_group != group_key or speaker == relay.listener:
            continue
        if relay.capture_until is None:
            if not (_dt(relay.window_start) <= at <= _dt(relay.window_end)):
                continue
            # capture runs a full 15 minutes from the first message, even past the window's end
            relay.capture_until = (at + timedelta(minutes=relay.capture_minutes)).isoformat()
            state.log("RELAY", f"Listening started for {state.name(relay.listener)} ({relay.purpose}).",
                      actor=relay.listener)
        if at <= _dt(relay.capture_until):
            relay.messages.append(RelayMessage(speaker=speaker, at=at.isoformat(), text=text))
            taken.append(relay)
    return taken


def due_relays(state: GameState, now: datetime) -> list[Relay]:
    return [
        r for r in state.relays if not r.done and (
            (r.capture_until is not None and now > _dt(r.capture_until))
            or (r.capture_until is None and now > _dt(r.window_end))
        )
    ]


def speaker_number(state: GameState, relay: Relay, speaker: int) -> int:
    """Numbers stay the same for the same listener across uses."""
    aliases = state.aliases.setdefault(f"{relay.listener}:{relay.source_group}", {})
    if speaker not in aliases:
        aliases[speaker] = len(aliases) + 1
    return aliases[speaker]


def transcript(state: GameState, relay: Relay) -> str:
    tz = zone(state)
    start = _dt(relay.window_start).astimezone(tz)
    end = _dt(relay.window_end).astimezone(tz)
    if not relay.messages:
        return f"You listened from {start:%H:%M} to {end:%H:%M}, but nothing was said."
    lines = []
    for message in relay.messages:
        number = speaker_number(state, relay, message.speaker)
        lines.append(f"`{_dt(message.at).astimezone(tz):%H:%M}` **Speaker {number}:** {message.text}")
    first = _dt(relay.messages[0].at).astimezone(tz)
    until = _dt(relay.capture_until).astimezone(tz)
    return f"What you overheard ({first:%H:%M}–{until:%H:%M}):\n" + "\n".join(lines)


def finish_relay(state: GameState, relay: Relay) -> None:
    relay.done = True
    title = {"peeking_girl": "👂 What the wolves said", "diviner": "🔮 Your scrying"}.get(relay.purpose, "👂 Overheard")
    state.emit(PrivateMessage(player=relay.listener, title=title, text=transcript(state, relay)))
    state.log("RELAY", f"Transcript sent to {state.name(relay.listener)} ({len(relay.messages)} messages).",
              actor=relay.listener)


# --- seances --------------------------------------------------------------------

def seance_deadline(state: GameState, now: datetime) -> datetime:
    """End of daytime (19:00) or end of nighttime (00:00), whichever comes first."""
    schedule = times(state.settings.schedule)
    candidates = []
    for kind in (TransitionKind.DUSK, TransitionKind.NIGHT_LOCK):
        hhmm = schedule[kind].strftime("%H:%M")
        candidates.append(next_occurrence(state, hhmm, now))
    return min(candidates)


def open_seance(state: GameState, asker: int, question: str, now: datetime) -> Seance:
    dead_chat = state.groups.get("dead")
    voters = [p.user_id for p in state.dead_players()
              if dead_chat is not None and player_access(state, dead_chat, p) is Access.WRITE]
    seance = Seance(id=state.next_id("seance"), asker=asker, question=question, asked_at=now.isoformat(),
                    deadline=seance_deadline(state, now).isoformat(), voters=voters)
    state.seances.append(seance)
    state.log("SEANCE", f"{state.name(asker)} asks the dead: “{question}” ({len(voters)} may answer).", actor=asker)
    if voters:
        state.emit(SeancePrompt(seance_id=seance.id))
    else:
        close_seance(state, seance, "there are no dead to answer")
    return seance


def answer_seance(state: GameState, seance_id: int, voter: int, yes: bool) -> Seance:
    seance = next((s for s in state.seances if s.id == seance_id), None)
    if seance is None or seance.done:
        raise GameError("This question has already been answered.")
    if voter not in seance.voters:
        raise GameError("You can't answer this question.")
    seance.answers[voter] = yes
    state.log("SEANCE", f"{state.name(voter)} answered séance #{seance.id}.", actor=voter)
    if set(seance.answers) >= set(seance.voters):
        close_seance(state, seance, "all the dead have answered")
    return seance


def due_seances(state: GameState, now: datetime) -> list[Seance]:
    return [s for s in state.seances if not s.done and now >= _dt(s.deadline)]


def close_seance(state: GameState, seance: Seance, reason: str) -> None:
    seance.done = True
    yes = sum(1 for v in seance.answers.values() if v)
    no = sum(1 for v in seance.answers.values() if not v)
    silent = len(seance.voters) - len(seance.answers)
    if seance.kind == "open_book":
        target = seance.voters[0]
        answer = "**yes**" if yes else "**no**" if no else "nothing (they didn't answer in time)"
        state.emit(PrivateMessage(player=seance.asker, title="📖 Charm of the Open Book",
                                  text=f"**{state.name(target)}** answered “{seance.question}” with {answer}."))
    else:
        text = f"The dead have answered “{seance.question}”:\n**{yes}× yes**, **{no}× no**"
        if silent:
            text += f" ({silent} didn't answer)"
        state.emit(PrivateMessage(player=seance.asker, title="🕯️ The spirits speak", text=text))
    state.log("SEANCE", f"Séance #{seance.id} closed ({reason}): {yes} yes, {no} no, {silent} silent.",
              actor=seance.asker)


def ask_player(state: GameState, asker: int, target: int, question: str, now: datetime, *,
               kind: str = "open_book") -> Seance:
    """A yes/no question one player must answer honestly (Charm of the Open Book).
    Open until the next morning."""
    player = state.player(target)
    morning = times(state.settings.schedule)[TransitionKind.MORNING].strftime("%H:%M")
    seance = Seance(id=state.next_id("seance"), asker=asker, question=question, asked_at=now.isoformat(),
                    deadline=next_occurrence(state, morning, now).isoformat(), voters=[target], kind=kind,
                    where=player.private_group or "dead")
    state.seances.append(seance)
    state.emit(SeancePrompt(seance_id=seance.id))
    state.log("SEANCE", f"{state.name(asker)} asks {state.name(target)} ({kind}): “{question}”", actor=asker,
              targets=[target])
    return seance


# --- telepathy ------------------------------------------------------------------

MAX_WORDS = 20


def send_telepathy(state: GameState, sender: int, target: int, text: str, now: datetime) -> TelepathyMessage:
    message = TelepathyMessage(id=state.next_id("telepathy"), sender=sender, target=target, text=text,
                               sent_at=now.isoformat())
    state.telepathy.append(message)
    state.emit(TelepathyPrompt(telepathy_id=message.id))
    state.log("TELEPATHY", f"{state.name(sender)} → {state.name(target)}: “{text}”", actor=sender, targets=[target])
    return message


def reply_telepathy(state: GameState, telepathy_id: int, replier: int, text: str, now: datetime) -> TelepathyMessage:
    message = next((m for m in state.telepathy if m.id == telepathy_id), None)
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
    state.log("TELEPATHY", f"{state.name(replier)} replied to {state.name(message.sender)}: “{message.reply}”",
              actor=replier, targets=[message.sender])
    return message


def relays_for_night(state: GameState, night: int) -> list[Relay]:
    return [r for r in state.relays if r.night == night]
