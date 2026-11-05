"""Before and around the game: the role pool, role assignment, families,
starting and ending the game, and the win check."""
from __future__ import annotations

import random
from datetime import datetime

from Core import voting
from Core.clock import next_transition
from Core.effects import Announcement, RoleCard
from Core.errors import GameError
from Core.factions import faction_display, winners
from Core.players import join_actor_chats, set_role
from Core.resolution import Resolution, register_final_hook
from Core.state import Chat, ChatKind, GameState, Phase


# --- role pool & assignment -----------------------------------------------------

# roles that appear more than once in the default setup
DEFAULT_COUNTS = {"brother": 3}
# registered roles that aren't part of the default setup (the plain Villager is filler)
NOT_IN_DEFAULT = frozenset({"villager"})


def default_role_pool() -> dict[str, int]:
    """One of every role that can be dealt out, three Brothers."""
    from Core.actor import ROLE_REGISTRY
    return {name: DEFAULT_COUNTS.get(name, 1) for name, cls in sorted(ROLE_REGISTRY.items())
            if cls.assignable and name not in NOT_IN_DEFAULT}


def plan_assignment(state: GameState, rng_seed: int | None = None) -> dict[int, str]:
    pool = [name for name, count in sorted(state.role_pool.items()) for _ in range(count)]
    players = sorted(state.players)
    if len(pool) != len(players):
        raise GameError(f"The role pool has {len(pool)} roles but there are {len(players)} players.")
    rng = random.Random(rng_seed)
    rng.shuffle(pool)
    return dict(zip(players, pool))


def apply_assignment(state: GameState, mapping: dict[int, str]) -> None:
    for user_id, role_name in mapping.items():
        set_role(state, state.player(user_id), role_name, reason="assignment")


# --- families & base chats ------------------------------------------------------

def split_families(state: GameState, *, size: int, rng_seed: int | None = None) -> list[Chat]:
    if state.phase is not Phase.SETUP:
        raise GameError("Families can only be formed before the game starts.")
    players = sorted(state.players)
    if not players:
        raise GameError("No players have joined yet.")
    rng = random.Random(rng_seed)
    rng.shuffle(players)
    count = max(1, round(len(players) / max(1, size)))
    for chat in state.chats_of_kind(ChatKind.FAMILY):
        del state.chats[chat.key]
    families = [
        state.ensure_chat(f"family:{i + 1}", ChatKind.FAMILY, f"family-{i + 1}") for i in range(count)
    ]
    for index, user_id in enumerate(players):
        family = families[index % count]
        family.add(user_id)
        state.players[user_id].family = family.key
    state.log("SETUP", "Families formed: " + "; ".join(
        f"{f.name}: {', '.join(state.name(u) for u in f.active_members())}" for f in families))
    return families


def ensure_base_chats(state: GameState) -> None:
    """Village, dead chat and one private chat per player."""
    state.ensure_chat("village", ChatKind.VILLAGE, "village-chat")
    state.ensure_chat("dead", ChatKind.DEAD, "dead-chat")
    taken: dict[str, int] = {}
    for player in sorted(state.players.values(), key=lambda p: p.user_id):
        if player.private_chat is not None:
            continue
        base = (player.role_name or "player").replace("_", "-")
        taken[base] = taken.get(base, 0) + 1
        name = base if taken[base] == 1 else f"{base}-{taken[base]}"
        chat = state.ensure_chat(f"private:{player.user_id}", ChatKind.PRIVATE, name,
                                 topic=f"Private channel of {player.display_name}")
        chat.add(player.user_id)
        player.private_chat = chat.key
    for player in state.players.values():
        join_actor_chats(state, player)


# --- start / end ----------------------------------------------------------------

def start_game(state: GameState, now: datetime) -> None:
    if state.phase is not Phase.SETUP:
        raise GameError("The game has already started.")
    if not state.players:
        raise GameError("No players have joined yet.")
    missing = [p.display_name for p in state.players.values() if p.role is None]
    if missing:
        raise GameError(f"These players have no role yet: {', '.join(missing)}")

    ensure_base_chats(state)
    state.phase = Phase.DAY
    state.day = 1
    state.started_at = now.isoformat()
    for player in state.players.values():
        if player.original_role is None:
            player.original_role = player.role_name
        state.emit(RoleCard(player=player.user_id, role=player.role_name))
    for _, actor in list(state.iter_actors()):
        hook = getattr(actor, "on_game_start", None)
        if hook is not None:
            hook(state)

    voting.open_ballot(state, voting.MAYOR, allow_abstain=False)
    state.emit(Announcement(
        title="THE GAME HAS STARTED",
        text="Welcome to XP Werewolves! Today is the first day - get to know each other.\n"
             "Vote for a **Mayor** with `/mayor vote`. The first night begins at "
             f"{state.settings.schedule.dusk}.",
    ))
    state.next_transition = next_transition(state, now)
    state.log("GAME", f"Game started with {len(state.players)} players.", alert=True)


def end_game(state: GameState, winner: str | None, now: datetime) -> None:
    """End the game. Also works before it started; all data is kept until /game delete."""
    if state.phase is Phase.ENDED:
        raise GameError("The game has already ended.")
    state.phase = Phase.ENDED
    state.winner = winner
    state.ended_at = now.isoformat()
    state.next_transition = None
    text = f"The game is over! **{faction_display(winner)}** win." if winner else "The game is over!"
    state.emit(Announcement(title="GAME OVER", text=text, color="gold"))
    state.log("GAME", f"Game ended. Winner: {winner or 'none declared'}", alert=True)


@register_final_hook
def _win_check(ctx: Resolution) -> None:
    """After every resolution: tell the GMs when a win condition is met (they end the game)."""
    if not ctx.state.active:
        return
    found = winners(ctx.state)
    if found:
        text = ("Win condition met for: " + ", ".join(faction_display(f) for f in found)
                + " — end the game with `/gm end_game` if this is right.")
        ctx.note("Win check", text)
        ctx.state.log("WIN", text, alert=True)
