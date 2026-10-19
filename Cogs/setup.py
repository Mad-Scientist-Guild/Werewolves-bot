"""/setup - GM configuration before (and partly during) a game."""
from __future__ import annotations

import random
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands

from Core import flow
from Core.actions import TIME_RE, normalise_role
from Core.actor import MODIFIER_REGISTRY, ROLE_REGISTRY
from Core.errors import GameError
from Core.flow import family_members
from Core.state import GroupKind, Phase
from Services.discord_utils import is_gm, reply, reply_long
from Services.role_commands import role_autocomplete
from Services.runtime import runtime


async def actor_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Roles and modifiers (e.g. vengeful_spirit), for settings."""
    current = current.lower().replace(" ", "_")
    names = sorted(n for n in [*ROLE_REGISTRY, *MODIFIER_REGISTRY] if current in n)
    return [app_commands.Choice(name=n, value=n) for n in names[:25]]


def _setup_only(phase: Phase) -> None:
    if phase is not Phase.SETUP:
        raise GameError("This can only be changed before the game starts.")


class Setup(commands.GroupCog, group_name="setup", group_description="(GM) Configure the game",
            group_extras={}):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        handle = runtime.games.find(interaction.guild_id)
        if is_gm(interaction.user, handle.state if handle else None):
            return True
        await reply(interaction, "❌ Only Game Masters can use `/setup`.")
        return False

    # --- players ----------------------------------------------------------------
    @app_commands.command(name="add_player", description="Add someone to the game")
    async def add_player(self, interaction: discord.Interaction, member: discord.Member) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            flow.add_player(state, member.id, member.display_name)
            state.log("SETUP", f"{interaction.user.display_name} added {member.display_name}.", actor=interaction.user.id)
        await reply(interaction, f"Added {member.display_name}.")

    @app_commands.command(name="remove_player", description="Remove someone from the game (before it starts)")
    async def remove_player(self, interaction: discord.Interaction, member: discord.Member) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            flow.remove_player(state, member.id)
        await reply(interaction, f"Removed {member.display_name}.")

    @app_commands.command(name="backup", description="Add or remove someone on the backup (reaper) list")
    @app_commands.choices(action=[app_commands.Choice(name="add", value="add"),
                                  app_commands.Choice(name="remove", value="remove")])
    async def backup(self, interaction: discord.Interaction, action: app_commands.Choice[str], member: discord.Member) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            if action.value == "add":
                if member.id in state.players:
                    raise GameError("That person is already playing.")
                if member.id not in state.backups:
                    state.backups.append(member.id)
            elif member.id in state.backups:
                state.backups.remove(member.id)
            state.log("SETUP", f"Backup list {action.value}: {member.display_name}", actor=interaction.user.id)
            names = [interaction.guild.get_member(u).display_name if interaction.guild.get_member(u) else str(u)
                     for u in state.backups]
        await reply(interaction, f"Backup list: {', '.join(names) or 'empty'}")

    # --- role pool --------------------------------------------------------------
    @app_commands.command(name="roles_add", description="Add a role to the role pool")
    @app_commands.autocomplete(role=role_autocomplete)
    async def roles_add(self, interaction: discord.Interaction, role: str, count: app_commands.Range[int, 1, 50] = 1) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            _setup_only(state.phase)
            key = normalise_role(role)
            if not ROLE_REGISTRY[key].assignable:
                raise GameError(f"Nobody can start as {ROLE_REGISTRY[key].title()}.")
            state.role_pool[key] = state.role_pool.get(key, 0) + count
            state.log("SETUP", f"Role pool: +{count} {key}", actor=interaction.user.id)
            summary = _pool_summary(state)
        await reply(interaction, summary)

    @app_commands.command(name="roles_remove", description="Remove a role from the role pool")
    @app_commands.autocomplete(role=role_autocomplete)
    async def roles_remove(self, interaction: discord.Interaction, role: str, count: app_commands.Range[int, 1, 50] = 1) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            _setup_only(state.phase)
            key = normalise_role(role)
            left = state.role_pool.get(key, 0) - count
            if left > 0:
                state.role_pool[key] = left
            else:
                state.role_pool.pop(key, None)
            state.log("SETUP", f"Role pool: -{count} {key}", actor=interaction.user.id)
            summary = _pool_summary(state)
        await reply(interaction, summary)

    @app_commands.command(name="roles_default", description="Reset the role pool to the default setup")
    async def roles_default(self, interaction: discord.Interaction) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            _setup_only(state.phase)
            state.role_pool = flow.default_role_pool()
            state.log("SETUP", "Role pool reset to the default setup.", actor=interaction.user.id)
            summary = _pool_summary(state)
        await reply_long(interaction, "Role pool", summary)

    @app_commands.command(name="roles", description="Show the role pool")
    async def roles(self, interaction: discord.Interaction) -> None:
        await reply(interaction, _pool_summary(runtime.games.get(interaction.guild_id).state))

    @app_commands.command(name="assign", description="Randomly assign the role pool - shows a preview first")
    @app_commands.choices(confirm=[app_commands.Choice(name="preview", value="preview"),
                                   app_commands.Choice(name="apply the last preview", value="apply")])
    async def assign(self, interaction: discord.Interaction, confirm: app_commands.Choice[str]) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            _setup_only(state.phase)
            if confirm.value == "preview":
                rng_seed = random.SystemRandom().randrange(1, 2**31)
                plan = flow.plan_assignment(state, rng_seed)
                state.data["assignment_preview"] = {str(k): v for k, v in plan.items()}
                state.log("SETUP", "Role assignment preview made.", actor=interaction.user.id)
                text = "\n".join(f"{state.name(uid)} → {ROLE_REGISTRY[role].title()}"
                                 for uid, role in sorted(plan.items(), key=lambda kv: kv[1]))
                title = "Assignment preview — run `/setup assign apply` to use it"
            else:
                preview = state.data.get("assignment_preview")
                if not preview:
                    raise GameError("Make a preview first with `/setup assign preview`.")
                plan = {int(k): v for k, v in preview.items()}
                if set(plan) != set(state.players):
                    raise GameError("The players changed since the preview - make a new one.")
                flow.apply_assignment(state, plan)
                state.data["assignment_preview"] = None
                state.log("SETUP", "Roles assigned: " + ", ".join(f"{state.name(u)}={r}" for u, r in plan.items()),
                          actor=interaction.user.id)
                text = "Roles assigned. Check them with `/gm status`."
                title = "Roles assigned"
        await reply_long(interaction, title, text)

    @app_commands.command(name="set_role", description="Give a player a specific role (before the game)")
    @app_commands.autocomplete(role=role_autocomplete)
    async def set_role(self, interaction: discord.Interaction, member: discord.Member, role: str) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            _setup_only(state.phase)
            flow.set_role(state, state.player(member.id), normalise_role(role), reason=f"set by {interaction.user.display_name}")
        await reply(interaction, f"{member.display_name} is now {ROLE_REGISTRY[normalise_role(role)].title()}.")

    # --- families ---------------------------------------------------------------
    @app_commands.command(name="families", description="Randomly split the players into families")
    async def families(self, interaction: discord.Interaction, size: app_commands.Range[int, 2, 20] | None = None) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            if size is not None:
                state.settings.family_size = size
            groups = flow.split_families(state, size=state.settings.family_size,
                                         rng_seed=random.SystemRandom().randrange(1, 2**31))
            text = "\n".join(f"**{g.name}**: {', '.join(p.display_name for p in family_members(state, g.key))}"
                             for g in groups)
        await reply_long(interaction, "Families", text)

    @app_commands.command(name="family_move", description="Move a player to another family (family number)")
    async def family_move(self, interaction: discord.Interaction, member: discord.Member,
                          family: app_commands.Range[int, 1, 50]) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            key = f"family:{family}"
            if key not in state.groups:
                state.ensure_group(key, GroupKind.FAMILY, f"family-{family}")
            flow.set_family(state, state.player(member.id), key)
        await reply(interaction, f"{member.display_name} is now in family {family}.")

    # --- channels & settings ----------------------------------------------------
    @app_commands.command(name="channels", description="Create the game channels now (otherwise done at /game start)")
    async def channels(self, interaction: discord.Interaction) -> None:
        handle = runtime.games.get(interaction.guild_id)
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with runtime.games.mutate(interaction.guild_id) as state:
            missing = [p.display_name for p in state.players.values() if p.role is None]
            if missing:
                raise GameError("Assign roles first - private channels are named after them. Missing: "
                                + ", ".join(missing))
            flow.ensure_base_groups(state)
        await runtime.channels.setup_base(interaction.guild, handle)
        created = await runtime.channels.ensure_group_channels(interaction.guild, handle)
        await runtime.channels.sync(interaction.guild, handle)
        await reply(interaction, f"Created {created} channel(s); permissions synced.")

    @app_commands.command(name="times", description="Set the daily schedule (HH:MM, 24-hour)")
    async def times(self, interaction: discord.Interaction, morning: str | None = None, newspaper: str | None = None,
                    dusk: str | None = None, night_lock: str | None = None,
                    second_lynch_end: str | None = None) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            schedule = state.settings.schedule
            for name, value in (("morning", morning), ("newspaper", newspaper), ("dusk", dusk),
                                ("night_lock", night_lock), ("second_lynch_end", second_lynch_end)):
                if value is None:
                    continue
                if not TIME_RE.match(value):
                    raise GameError(f"'{value}' isn't a valid time - use HH:MM.")
                hours, minutes = value.split(":")
                setattr(schedule, name, f"{int(hours):02d}:{minutes}")
            if state.active and state.next_transition is not None:
                from Core.clock import next_transition, now_in
                state.next_transition = next_transition(state, now_in(state))
            text = (f"Morning {schedule.morning} · newspaper {schedule.newspaper} · dusk {schedule.dusk} · "
                    f"second lynch until {schedule.second_lynch_end} · night lock {schedule.night_lock}")
            state.log("SETUP", f"Schedule: {text}", actor=interaction.user.id)
        await reply(interaction, text)

    @app_commands.command(name="timezone", description="Set the game's timezone (e.g. Europe/Amsterdam)")
    async def timezone(self, interaction: discord.Interaction, tz: str) -> None:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise GameError(f"Unknown timezone '{tz}'.")
        async with runtime.games.mutate(interaction.guild_id) as state:
            state.settings.schedule.timezone = tz
            state.log("SETUP", f"Timezone: {tz}", actor=interaction.user.id)
        await reply(interaction, f"Timezone set to {tz}.")

    @app_commands.command(name="gm_role", description="Set the Discord role of the Game Masters")
    async def gm_role(self, interaction: discord.Interaction, role: discord.Role) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            state.settings.gm_role_id = role.id
            state.log("SETUP", f"GM role: {role.name}", actor=interaction.user.id)
        await reply(interaction, f"GM role set to {role.mention}. Run `/setup channels` again to give it access.")

    @app_commands.command(name="role_setting", description="Override a role number, e.g. role=feral_wolf key=uses.eat value=4")
    @app_commands.autocomplete(role=actor_autocomplete)
    async def role_setting(self, interaction: discord.Interaction, role: str, key: str, value: str) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            name = role.strip().lower().replace(" ", "_")
            if name not in MODIFIER_REGISTRY:
                name = normalise_role(role)
            parsed: object = value
            if value.lower() in ("none", "null", "unlimited"):
                parsed = None
            elif value.lstrip("-").isdigit():
                parsed = int(value)
            elif value.lower() in ("true", "false"):
                parsed = value.lower() == "true"
            state.settings.role_overrides.setdefault(name, {})[key] = parsed
            state.log("SETUP", f"Role setting {name}.{key} = {parsed!r}", actor=interaction.user.id, alert=state.active)
        await reply(interaction, f"{name}: `{key}` = `{parsed!r}`")


def _pool_summary(state) -> str:
    total = sum(state.role_pool.values())
    lines = [f"{count}× {ROLE_REGISTRY[name].title() if name in ROLE_REGISTRY else name}"
             for name, count in sorted(state.role_pool.items())]
    return (f"**Role pool: {total} roles for {len(state.players)} players**\n" + ("\n".join(lines) or "empty"))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Setup(bot))
