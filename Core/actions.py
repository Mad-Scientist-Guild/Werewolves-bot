"""Submitting, replacing and cancelling actions.

All generic validation lives here (phase, sleep time, uses, target
validity) so role code only adds what is special about it.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from Core.abilities import Ability, ParamKind, Timing
from Core.actor import ROLE_REGISTRY, Actor
from Core.errors import GameError
from Core.resolution import describe_action, run_resolution
from Core.state import ActionStatus, GameState, GroupKind, Phase, Player, SubmittedAction

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def find_ability(state: GameState, player: Player, key: str, source: str | None = None) -> tuple[Actor, Ability]:
    for actor in player.actors():
        if source is not None and not actor.provides(source):
            continue
        for ability in actor.available_abilities(state):
            if ability.key == key:
                return actor, ability
    for actor in player.actors():
        ability = actor.ability(key)
        if ability is not None and (source is None or actor.provides(source)) and actor.uses_left(state, ability) == 0:
            raise GameError("You have no uses of this ability left.")
    raise GameError("You can't use that ability right now.")


def available(state: GameState, player: Player) -> list[tuple[Actor, Ability]]:
    return [(actor, ability) for actor in player.actors() for ability in actor.available_abilities(state)]


def slot_for(state: GameState, ability: Ability, *, lenient: bool = False) -> str:
    """Which resolution moment this ability, used now, belongs to. Raises if
    it can't be used in the current phase. `lenient` (GM entries) allows
    night actions during sleep time and ignores the first-day rule."""
    phase = state.phase
    if not state.active:
        raise GameError("The game isn't running.")
    if (state.day == 1 and phase is Phase.DAY and ability.timing is not Timing.NIGHT and not ability.first_day
            and not lenient):
        raise GameError("Nothing happens on the first day - wait for the first night.")

    if ability.timing is Timing.NIGHT:
        if phase is Phase.SLEEP and lenient:
            return state.slot("night")
        if phase is Phase.SLEEP:
            raise GameError("It's sleep time (00:00-08:00) - night actions are locked in until morning.")
        if phase is not Phase.NIGHT:
            raise GameError("This can only be done at night (19:00-00:00).")
        return state.slot("night")
    if ability.timing is Timing.DAY:
        if phase is not Phase.DAY:
            raise GameError("This can only be done during the day (08:00-19:00).")
        return state.slot("dusk")
    if ability.timing is Timing.ANYTIME:
        return state.slot("dusk") if phase is Phase.DAY else state.slot("night")
    # INSTANT
    allowed = ability.phases or (Phase.DAY.value, Phase.NIGHT.value, Phase.SLEEP.value)
    if phase.value not in allowed:
        raise GameError(f"This can't be done right now (allowed: {', '.join(allowed)}).")
    return "instant"


def normalise_role(name: str) -> str:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    if key not in ROLE_REGISTRY:
        raise GameError(f"'{name}' isn't a known role.")
    return key


def validate_params(state: GameState, player: Player, ability: Ability, params: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    unknown = set(params) - {p.name for p in ability.params}
    if unknown:
        raise GameError(f"Unexpected option(s): {', '.join(sorted(unknown))}")
    for param in ability.params:
        value = params.get(param.name)
        if value is None or value == "":
            if param.required:
                raise GameError(f"Missing `{param.name}`.")
            continue
        kind = param.kind
        if kind in (ParamKind.LIVING_PLAYER, ParamKind.DEAD_PLAYER, ParamKind.ANY_PLAYER):
            target = state.player(int(value))
            if target is player and not param.allow_self:
                raise GameError("You can't target yourself with this.")
            if kind is ParamKind.LIVING_PLAYER and not target.alive:
                raise GameError(f"{target.display_name} isn't alive.")
            if kind is ParamKind.DEAD_PLAYER and not target.dead:
                raise GameError(f"{target.display_name} isn't dead.")
            clean[param.name] = target.user_id
        elif kind is ParamKind.ROLE:
            clean[param.name] = normalise_role(str(value))
        elif kind is ParamKind.CHOICE:
            choice = str(value).strip().lower()
            if choice not in param.choices:
                raise GameError(f"`{param.name}` must be one of: {', '.join(param.choices)}")
            clean[param.name] = choice
        elif kind is ParamKind.TEXT:
            text = str(value).strip()
            if param.max_words is not None and len(text.split()) > param.max_words:
                raise GameError(f"That's {len(text.split())} words - the limit is {param.max_words}.")
            clean[param.name] = text
        elif kind is ParamKind.TIME:
            if not TIME_RE.match(str(value).strip()):
                raise GameError(f"'{value}' isn't a valid time - use HH:MM (24-hour), e.g. 21:00.")
            hours, minutes = str(value).strip().split(":")
            clean[param.name] = f"{int(hours):02d}:{minutes}"
        elif kind is ParamKind.FAMILY:
            group = state.groups.get(str(value))
            if group is None or group.kind is not GroupKind.FAMILY:
                raise GameError(f"'{value}' isn't a family.")
            clean[param.name] = group.key
        elif kind is ParamKind.NUMBER:
            clean[param.name] = int(value)
        else:
            clean[param.name] = value
    return clean


def pending_action(state: GameState, player_id: int, ability_key: str, source: str | None = None,
                   slot: str | None = None) -> SubmittedAction | None:
    player = state.find_player(player_id)
    providers = {a.name for a in player.actors() if source is None or a.provides(source)} if player else set()
    for action in reversed(state.actions):
        if (action.actor == player_id and action.ability == ability_key
                and (source is None or action.source == source or action.source in providers)
                and (slot is None or action.slot == slot)
                and action.status is ActionStatus.PENDING):
            return action
    return None


def submit(state: GameState, player_id: int, ability_key: str, params: dict[str, Any], *,
           now: datetime, source: str | None = None, by_gm: bool = False) -> SubmittedAction:
    player = state.player(player_id)
    actor, ability = find_ability(state, player, ability_key, source)
    source = actor.name

    if not player.alive and not ability.usable_while_dead:
        raise GameError("You can't do that while dead.")
    slot = slot_for(state, ability, lenient=by_gm)

    left = actor.uses_left(state, ability)
    if left is not None:
        pending_elsewhere = sum(
            1 for a in state.actions
            if a.actor == player_id and a.source == actor.name and a.ability == ability_key
            and a.status is ActionStatus.PENDING and a.slot != slot
        )
        if left - pending_elsewhere <= 0:
            raise GameError("You have no uses of this ability left.")
    if ability.timing is Timing.INSTANT and ability.once_per_cycle and actor.last_used.get(ability.key) == state.day:
        raise GameError("You've already used this today.")

    clean = validate_params(state, player, ability, params)
    targets = [v for p in ability.params
               if p.kind in (ParamKind.LIVING_PLAYER, ParamKind.DEAD_PLAYER, ParamKind.ANY_PLAYER)
               and (v := clean.get(p.name)) is not None]
    action = SubmittedAction(
        id=state.next_id("action"), actor=player_id, source=actor.name, ability=ability.key, slot=slot,
        targets=targets, params=clean, submitted_at=now.isoformat(), submitted_phase=state.phase.value,
        by_gm=by_gm,
    )
    actor.validate(state, action)

    previous = None
    if slot != "instant":
        previous = pending_action(state, player_id, ability.key, actor.name, slot)
        if previous is not None:
            previous.status = ActionStatus.REPLACED
            previous.note = f"replaced by #{action.id}"
    state.actions.append(action)

    verb = "changed their action" if previous else "submitted"
    sleeping = state.phase is Phase.SLEEP and slot != "instant"
    suffix = " — submitted during sleep time, resolves at 08:00" if sleeping else ""
    gm = " (entered by a GM)" if by_gm else ""
    state.log(
        "ACTION", f"{player.display_name} {verb}: {describe_action(state, action)}{gm}{suffix}",
        actor=player_id, targets=targets, alert=sleeping, action_id=action.id, slot=slot,
    )

    if slot == "instant":
        outcome = run_resolution(
            state, kind="instant", slot="instant", seed=state.next_id("instant_seed") * 7919 + action.id,
            title=f"{player.display_name}: {actor.name}.{ability.key}", actions=[action],
        )
        state.log("RESOLVED", outcome.report, actor=player_id, action_id=action.id)
    return action


def cancel(state: GameState, player_id: int, ability_key: str, *, source: str | None = None,
           by_gm: bool = False) -> SubmittedAction:
    action = pending_action(state, player_id, ability_key, source)
    if action is None:
        raise GameError("There's no pending action of that kind to cancel.")
    if state.phase is Phase.SLEEP and action.slot == state.slot("night") and not by_gm:
        raise GameError("It's sleep time - your night action is locked in.")
    action.status = ActionStatus.CANCELLED
    action.note = "cancelled by a GM" if by_gm else "cancelled by the player"
    state.log("ACTION", f"{state.name(player_id)} cancelled: {describe_action(state, action)}"
              + (" (by a GM)" if by_gm else ""), actor=player_id, action_id=action.id)
    return action
