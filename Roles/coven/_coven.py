"""Shared Coven mechanics.

Discovery: each night every Coven member can guess one other member (the Hag
Mother three). A correct guess links the two. Coven chats follow the linked
groups: finding ONE member of an established group joins you to that whole
group. Groups merge as they connect - a new chat is created for the merged
group and the old chats become read-only (nothing is ever deleted).

The kill list (default 15 roles in the game + 3 that aren't) is generated at
the start and shown to a member once they've found someone.
"""
from __future__ import annotations

import random

from Core.effects import GroupMessage
from Core.factions import COVEN
from Core.flow import seed
from Roles.role import *
from Services.discord_utils import reply
from Services.runtime import runtime

KILL_LIST_IN_GAME = 15
KILL_LIST_ABSENT = 3

FIND = Ability(
    "find", Timing.NIGHT, "Guess a fellow Coven member - if you're right, you join forces",
    params=(P.living("target", "Who you think is in the Coven"),), priority=Priority.INFO,
)


# --- the discovery graph -----------------------------------------------------------

def links(state: GameState) -> list[list[int]]:
    return state.data.setdefault("coven_links", [])


def group_of(state: GameState, member: int) -> set[int]:
    """Everyone connected to this member (themselves included)."""
    seen, todo = {member}, [member]
    pairs = links(state)
    while todo:
        current = todo.pop()
        for a, b in pairs:
            for x, y in ((a, b), (b, a)):
                if x == current and y not in seen:
                    seen.add(y)
                    todo.append(y)
    return seen


def known_members(state: GameState, member: int) -> set[int]:
    """Coven members this member knows (excluding themselves)."""
    return group_of(state, member) - {member}


def chat_of(state: GameState, member: int) -> str | None:
    return state.data.get("coven_chat_of", {}).get(str(member))


def connect(ctx: Resolution, a: int, b: int) -> None:
    """Link two Coven members (commit pass) and merge their chats."""
    state = ctx.state
    group_a, group_b = group_of(state, a), group_of(state, b)
    if b in group_a:
        return
    links(state).append(sorted([a, b]))
    merged = group_a | group_b
    chat_a = chat_of(state, a) if len(group_a) > 1 else None
    chat_b = chat_of(state, b) if len(group_b) > 1 else None
    # members who had found nobody before: they get to see the kill list now
    newcomers = [m for group in (group_a, group_b) if len(group) == 1 for m in group]

    if chat_a and not chat_b:
        key, joining = chat_a, group_b
    elif chat_b and not chat_a:
        key, joining = chat_b, group_a
    else:
        number = state.next_id("coven_chat")
        key = f"coven:{number}"
        state.ensure_group(key, GroupKind.COVEN, f"coven-{number}")
        joining = merged
        for old in (chat_a, chat_b):
            if old:   # superseded: stays readable for everyone who was in it
                state.groups[old].archived = True
    group = state.groups[key]
    for member in sorted(joining):
        group.add(member)
    mapping = state.data.setdefault("coven_chat_of", {})
    for member in merged:
        mapping[str(member)] = key

    names = ", ".join(state.name(m) for m in sorted(merged))
    state.emit(GroupMessage(group=key, text=f"🕯️ The Coven grows: {names}"))
    ctx.note("Conversions", f"Coven members {state.name(a)} and {state.name(b)} found each other → {group.name}: {names}")
    for member in newcomers:
        ctx.inform(member, "You now know the Coven's kill list:\n" + kill_list_text(state))


def full_coven(state: GameState) -> bool:
    """Every living Coven member has found the others."""
    members = [p.user_id for p in state.alive_players() if p.true_faction() == COVEN]
    return len(members) > 1 and set(members) <= group_of(state, members[0])


# --- the kill list --------------------------------------------------------------------

def ensure_kill_list(state: GameState) -> list[str]:
    existing = state.data.get("coven_kill_list")
    if existing:
        return existing
    in_game = sorted({p.original_role or p.role_name for p in state.players.values()
                      if p.role is not None and p.role.faction != COVEN})
    absent = sorted(name for name, cls in ROLE_REGISTRY.items()
                    if cls.assignable and cls.faction != COVEN and name not in in_game and name != "villager")
    rng = random.Random(seed(state, "coven_kill_list"))
    picked = rng.sample(in_game, min(KILL_LIST_IN_GAME, len(in_game)))
    picked += rng.sample(absent, min(KILL_LIST_ABSENT, len(absent)))
    rng.shuffle(picked)
    state.data["coven_kill_list"] = picked
    state.log("COVEN", "Coven kill list: " + ", ".join(picked) + " (change it with `/gm kill_list`)", alert=True)
    return picked


def kill_list_text(state: GameState) -> str:
    roles = state.data.get("coven_kill_list", [])
    return "\n".join(f"• {ROLE_REGISTRY[r].title() if r in ROLE_REGISTRY else r}" for r in roles) or "(empty)"


# --- shared role base & commands -----------------------------------------------------------

class CovenRole(Role):
    """Base for the Coven roles (not a role itself)."""
    faction = COVEN

    def on_game_start(self, state: GameState) -> None:
        ensure_kill_list(state)

    def validate_find(self, state: GameState, action: SubmittedAction) -> None:
        if len(set(action.targets)) != len(action.targets):
            raise GameError("Pick different players.")
        for target in action.targets:
            if target in known_members(state, self.owner):
                raise GameError(f"You already know {state.name(target)} is in the Coven.")

    def validate(self, state: GameState, action: SubmittedAction) -> None:
        if action.ability == "find":
            self.validate_find(state, action)

    def resolve_find(self, ctx: Resolution, action: SubmittedAction) -> None:
        for target in action.targets:
            player = ctx.state.player(target)
            if player.true_faction() == COVEN:
                ctx.inform(self.owner, f"You found a fellow Coven member: **{player.display_name}**!")
                ctx.inform(target, f"**{ctx.state.name(self.owner)}** found you - they're part of the Coven too.")
                ctx.commit(lambda t=target: connect(ctx, self.owner, t))
            else:
                ctx.inform(self.owner, f"**{player.display_name}** is not part of the Coven.")


class CovenCommands(RoleCommands, abstract=True):
    """/find and /kill_list for every Coven role's command group."""

    @app_commands.command(name="find", description="Guess a fellow Coven member tonight")
    @app_commands.describe(target="Who you think is in the Coven")
    async def find(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self.use(interaction, "find", target=target)

    @app_commands.command(name="kill_list", description="See the Coven's kill list (once you've found a member)")
    async def kill_list(self, interaction: discord.Interaction) -> None:
        state = runtime.games.get(interaction.guild_id).state
        player = state.player(interaction.user.id)
        if player.true_faction() != COVEN or not known_members(state, player.user_id):
            raise GameError("You'll see the kill list once you've found a fellow Coven member.")
        await reply(interaction, "**The Coven's kill list** (original roles):\n" + kill_list_text(state))
