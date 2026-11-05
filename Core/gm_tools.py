"""GM interventions: kills, revives, night overrides and the Reaper's
replacements."""
from __future__ import annotations

from Core.errors import GameError
from Core.resolution import Resolution
from Core.state import GameState, LifeState, NightOverride, Phase, Player


def gm_kill(state: GameState, target: int, *, cause: str = "gm", public: bool = False, by: int | None = None) -> str:
    player = state.player(target)
    if not (player.alive or player.life is LifeState.SKELETON):
        raise GameError(f"{player.display_name} is already dead.")
    ctx = Resolution(state, kind="instant", moment="gm", seed=state.next_id("gm_seed"), title=f"GM kill: {player.display_name}",
                     actions=[])
    ctx.commit(lambda: ctx.attack(target, cause, killer_role="gm", unstoppable=True, public=public, enters_house=False))
    report = ctx.run()
    state.log("GM", f"GM killed {player.display_name} ({cause}{', public' if public else ''})", actor=by,
              targets=[target], alert=True)
    return report


def gm_revive(state: GameState, target: int, *, by: int | None = None) -> str:
    player = state.player(target)
    if player.alive:
        raise GameError(f"{player.display_name} is alive.")
    if player.life is not LifeState.DEAD:
        raise GameError(f"{player.display_name} can't be revived ({player.life.value}).")
    ctx = Resolution(state, kind="instant", moment="gm", seed=state.next_id("gm_seed"), title=f"GM revive: {player.display_name}",
                     actions=[])
    ctx.commit(lambda: ctx.revive(target, reason="GM"))
    report = ctx.run()
    state.log("GM", f"GM revived {player.display_name}", actor=by, targets=[target], alert=True)
    return report


def add_night_override(state: GameState, kind: str, target: int, *, cause: str = "gm", by: int | None = None) -> None:
    if state.phase not in (Phase.NIGHT, Phase.SLEEP):
        raise GameError("Night overrides can only be added during the night.")
    if kind not in ("kill", "spare"):
        raise GameError("Override kind must be 'kill' or 'spare'.")
    state.player(target)
    state.night_overrides = [o for o in state.night_overrides if o.player != target]
    state.night_overrides.append(NightOverride(kind=kind, player=target, cause=cause, by=by))
    state.log("GM", f"Night override: {kind} {state.name(target)} ({cause})", actor=by, targets=[target], alert=True)


def remove_night_override(state: GameState, target: int, *, by: int | None = None) -> None:
    before = len(state.night_overrides)
    state.night_overrides = [o for o in state.night_overrides if o.player != target]
    if len(state.night_overrides) == before:
        raise GameError("There is no override for that player.")
    state.log("GM", f"Night override for {state.name(target)} removed", actor=by, targets=[target])


def replace_player(state: GameState, old_id: int, new_id: int, new_name: str, *, by: int | None = None) -> Player:
    """The Reaper puts another soul into a body: the new member takes over
    the player's role, state, chats and channels."""
    if new_id in state.players:
        raise GameError("That person is already playing.")
    player = state.player(old_id)
    old_name = player.display_name
    del state.players[old_id]
    player.previous_user_ids.append(old_id)
    player.user_id = new_id
    player.display_name = new_name
    for actor in player.actors():
        actor.owner = new_id
    state.players[new_id] = player
    for chat in state.chats.values():
        if old_id in chat.members:
            chat.members[new_id] = chat.members.pop(old_id)
    for action in state.actions:
        if action.actor == old_id:
            action.actor = new_id
    for ballot in state.ballots.values():
        if old_id in ballot.votes:
            ballot.votes[new_id] = ballot.votes.pop(old_id)
    if state.mayor == old_id:
        state.mayor = new_id
    if state.mayor_successor == old_id:
        state.mayor_successor = new_id
    if new_id in state.backups:
        state.backups.remove(new_id)
    player.inactivity_level = 0
    player.last_active_at = None
    state.log("REAPER", f"{new_name} replaces {old_name} (role {player.role_name}).", actor=by,
              targets=[new_id], alert=True, old_user=old_id)
    return player
