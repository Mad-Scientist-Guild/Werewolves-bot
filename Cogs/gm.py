"""/gm - Game Master tools while a game runs: inspect everything, adjust the
night before it is applied, override roles and deaths, control the clock,
roll back, and end the game. Every use is logged."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from Core import actions, flow, voting
from Core.abilities import PLAYER_KINDS, ParamKind
from Core.actor import MODIFIER_REGISTRY, ROLE_REGISTRY
from Core.clock import TransitionKind, next_transition, now_in, transition_time
from Core.effects import Announcement
from Core.errors import GameError
from Core.factions import FACTIONS, faction_display
from Core.resolution import describe_action
from Core.state import ActionStatus, GameState, GroupKind, Phase, Player
from Services.discord_utils import is_gm, reply, reply_long
from Services.role_commands import refresh_preview, role_autocomplete
from Services.runtime import runtime


async def ability_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    handle = runtime.games.find(interaction.guild_id)
    member_id = getattr(interaction.namespace, "player", None)
    if handle is None or member_id is None:
        return []
    player = handle.state.find_player(member_id.id if hasattr(member_id, "id") else int(member_id))
    if player is None:
        return []
    keys = sorted({f"{a.name}:{ab.key}" for a in player.actors() for ab in a.abilities})
    return [app_commands.Choice(name=k, value=k) for k in keys if current.lower() in k][:25]


async def modifier_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=n, value=n) for n in sorted(MODIFIER_REGISTRY) if current.lower() in n][:25]


async def group_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    handle = runtime.games.find(interaction.guild_id)
    if handle is None:
        return []
    groups = [g for g in handle.state.groups.values()
              if g.kind not in (GroupKind.PRIVATE, GroupKind.VILLAGE, GroupKind.DEAD)]
    return [app_commands.Choice(name=f"{g.name} ({g.key})", value=g.key)
            for g in groups if current.lower() in g.key.lower() or current.lower() in g.name.lower()][:25]


def player_line(state: GameState, player: Player) -> str:
    life = player.life.value
    mods = f" +{', '.join(m.name for m in player.modifiers)}" if player.modifiers else ""
    mayor = " 🎩" if state.mayor == player.user_id else ""
    family = state.groups[player.family].name if player.family in state.groups else "-"
    return (f"**{player.display_name}** — {player.role_name}{mods} [{faction_display(player.true_faction())}] "
            f"· {life} · {family}{mayor}")


class GM(commands.GroupCog, group_name="gm", group_description="(GM) Game Master tools"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        handle = runtime.games.find(interaction.guild_id)
        if is_gm(interaction.user, handle.state if handle else None):
            return True
        await reply(interaction, "❌ Only Game Masters can use `/gm`.")
        return False

    # --- inspection ---------------------------------------------------------------
    @app_commands.command(name="status", description="Everything about the game at a glance")
    async def status(self, interaction: discord.Interaction) -> None:
        state = runtime.games.get(interaction.guild_id).state
        lines = [f"**Game #{state.game_id}** — {state.phase.value}, day {state.day}"
                 + (" ⏸️ PAUSED" if state.paused else "") + (" 🔒 LOCKDOWN" if state.lockdown else "")]
        if state.next_transition:
            at = transition_time(state.next_transition).astimezone(now_in(state).tzinfo)
            lines.append(f"Next: **{state.next_transition.kind}** at {at:%a %d %b %H:%M}")
        open_ballots = [b.kind for b in state.ballots.values() if b.is_open]
        if open_ballots:
            lines.append("Open ballots: " + ", ".join(open_ballots))
        for decision in flow.open_decisions(state):
            lines.append(f"⚖️ Decision #{decision.id} waiting for {state.name(decision.chooser)}: {decision.prompt}")
        for override in state.night_overrides:
            lines.append(f"🛠️ Night override: {override.kind} {state.name(override.player)} ({override.cause})")
        lines.append("")
        for player in sorted(state.players.values(), key=lambda p: (p.life.value, p.display_name.lower())):
            lines.append(player_line(state, player))
        await reply_long(interaction, "Game status", "\n".join(lines))

    @app_commands.command(name="player", description="Full details of one player")
    async def player(self, interaction: discord.Interaction, player: discord.Member) -> None:
        state = runtime.games.get(interaction.guild_id).state
        p = state.player(player.id)
        lines = [player_line(state, p), f"Original role: {p.original_role}", f"Base faction: {p.faction}"]
        for actor in p.actors():
            data = {k: v for k, v in vars(actor).items() if k != "owner" and v not in ({}, [], None)}
            lines.append(f"`{actor.name}` state: {data}")
        if p.statuses:
            lines.append("Statuses: " + ", ".join(f"{s.key}(until {s.expires or 'removed'})" for s in p.statuses))
        for record in p.deaths:
            lines.append(f"Death: day {record.day} {record.phase}, {record.cause} by {record.killer_role}"
                         + (" (revived)" if record.revived else ""))
        groups = [f"{g.name}={m.value}" for g in state.groups.values() for uid, m in g.members.items() if uid == p.user_id]
        lines.append("Groups: " + ", ".join(groups))
        lines.append(f"Public status: {p.public_status.value} · last active: {p.last_active_at or 'never'}")
        recent = [a for a in state.actions if a.actor == p.user_id][-10:]
        if recent:
            lines.append("Recent actions:")
            lines.extend(f"  #{a.id} {a.slot} {describe_action(state, a)} → {a.status.value} {a.note}" for a in recent)
        await reply_long(interaction, f"Player: {p.display_name}", "\n".join(lines))

    @app_commands.command(name="actions", description="Pending actions for the current day/night")
    async def pending_actions(self, interaction: discord.Interaction) -> None:
        state = runtime.games.get(interaction.guild_id).state
        pending = [a for a in state.actions if a.status is ActionStatus.PENDING]
        lines = [f"#{a.id} [{a.slot}] {state.name(a.actor)}: {describe_action(state, a)}" for a in pending]
        wolves = state.ballots.get(voting.WOLVES)
        if wolves is not None:
            lines.append(f"Wolf vote: {voting.describe_counts(state, voting.tally_wolves(state, wolves))}")
        await reply_long(interaction, "Pending actions", "\n".join(lines) or "Nothing pending.")

    @app_commands.command(name="preview", description="Resolve tonight right now as a preview (changes nothing)")
    async def preview(self, interaction: discord.Interaction) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            if state.phase not in (Phase.NIGHT, Phase.SLEEP):
                raise GameError("There's no night to preview right now.")
            outcome = flow.preview_night(state)
            state.log("GM", f"{interaction.user.display_name} requested a night preview.", actor=interaction.user.id)
        await reply_long(interaction, f"Night {state.day} — preview (on request)", outcome.report)

    @app_commands.command(name="log", description="Recent audit log entries")
    async def log(self, interaction: discord.Interaction, player: discord.Member | None = None,
                  category: str | None = None, count: app_commands.Range[int, 1, 100] = 25) -> None:
        handle = runtime.games.get(interaction.guild_id)
        events = await runtime.db.recent_events(handle.game_id, limit=count, category=category,
                                                player=player.id if player else None)
        text = "\n".join(f"`#{e.id} D{e.day or 0} {e.at[11:16]}` **{e.category}** {e.message}" for e in events)
        await reply_long(interaction, "Audit log", text or "No entries.")

    # --- actions on behalf of players --------------------------------------------
    @app_commands.command(name="act", description="Enter an action for a player (also allowed during sleep time)")
    @app_commands.autocomplete(ability=ability_autocomplete)
    @app_commands.describe(ability="role:ability", target="First player target", target2="Second player target",
                           option="Role / choice / family option", text="Text or HH:MM time")
    async def act(self, interaction: discord.Interaction, player: discord.Member, ability: str,
                  target: discord.Member | None = None, target2: discord.Member | None = None,
                  option: str | None = None, text: str | None = None) -> None:
        source, _, key = ability.partition(":")
        if not key:
            source, key = None, source
        async with runtime.games.mutate(interaction.guild_id) as state:
            p = state.player(player.id)
            actor, ab = actions.find_ability(state, p, key, source or None)
            players = [t.id for t in (target, target2) if t is not None]
            params: dict = {}
            for param in ab.params:
                if param.kind in PLAYER_KINDS:
                    if players:
                        params[param.name] = players.pop(0)
                elif param.kind in (ParamKind.TEXT, ParamKind.TIME):
                    if text is not None:
                        params[param.name], text = text, None
                elif option is not None:
                    params[param.name], option = option, None
            action = actions.submit(state, p.user_id, key, params, now=now_in(state), source=actor.name, by_gm=True)
            if state.phase is Phase.SLEEP:
                refresh_preview(state, f"GM entered an action for {p.display_name}")
            summary = describe_action(state, action)
        await reply(interaction, f"Entered for {player.display_name}: {summary}")

    @app_commands.command(name="cancel_action", description="Cancel a player's pending action")
    @app_commands.autocomplete(ability=ability_autocomplete)
    async def cancel_action(self, interaction: discord.Interaction, player: discord.Member, ability: str) -> None:
        source, _, key = ability.partition(":")
        if not key:
            source, key = None, source
        async with runtime.games.mutate(interaction.guild_id) as state:
            actions.cancel(state, player.id, key, source=source or None, by_gm=True)
            if state.phase is Phase.SLEEP:
                refresh_preview(state, f"GM cancelled an action of {player.display_name}")
        await reply(interaction, "Cancelled.")

    @app_commands.command(name="override", description="Tonight: force a death, or spare someone from every death")
    @app_commands.choices(kind=[app_commands.Choice(name="kill", value="kill"),
                                app_commands.Choice(name="spare", value="spare"),
                                app_commands.Choice(name="remove override", value="remove")])
    async def override(self, interaction: discord.Interaction, kind: app_commands.Choice[str], player: discord.Member,
                       cause: str = "gm") -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            if kind.value == "remove":
                flow.remove_night_override(state, player.id, by=interaction.user.id)
            else:
                flow.add_night_override(state, kind.value, player.id, cause=cause, by=interaction.user.id)
            if state.phase is Phase.SLEEP:
                refresh_preview(state, f"GM override ({kind.value} {player.display_name})")
        await reply(interaction, f"Override saved: {kind.value} {player.display_name}.")

    # --- life & death ---------------------------------------------------------------
    @app_commands.command(name="kill", description="Kill a player right now (death hooks like heartbreak still run)")
    async def kill(self, interaction: discord.Interaction, player: discord.Member, cause: str = "gm",
                   public: bool = False) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            report = flow.gm_kill(state, player.id, cause=cause, public=public, by=interaction.user.id)
            state.report(f"GM kill: {player.display_name}", report)
        await reply(interaction, f"{player.display_name} is dead" + (" (public)." if public else
                                 " (quiet - the Dead role follows at the newspaper)."))

    @app_commands.command(name="revive", description="Revive a dead player")
    async def revive(self, interaction: discord.Interaction, player: discord.Member) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            report = flow.gm_revive(state, player.id, by=interaction.user.id)
            state.report(f"GM revive: {player.display_name}", report)
        await reply(interaction, f"{player.display_name} is alive again.")

    @app_commands.command(name="replace", description="The Reaper: put a backup player into someone's body")
    async def replace(self, interaction: discord.Interaction, player: discord.Member, replacement: discord.Member) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            p = flow.replace_player(state, player.id, replacement.id, replacement.display_name, by=interaction.user.id)
            from Core.effects import RoleCard
            state.emit(RoleCard(player=p.user_id, role=p.role_name,
                                note=f"You have taken over from {player.display_name}. Read back through this "
                                     "channel to catch up."))
        await reply(interaction, f"{replacement.display_name} has taken over from {player.display_name}.")

    # --- roles, modifiers, factions, groups ----------------------------------------
    @app_commands.command(name="set_role", description="Change a player's role during the game")
    @app_commands.autocomplete(role=role_autocomplete)
    async def set_role(self, interaction: discord.Interaction, player: discord.Member, role: str,
                       keep_faction: bool = False, notify: bool = True) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            flow.set_role(state, state.player(player.id), actions.normalise_role(role), keep_faction=keep_faction,
                          notify=notify, reason=f"GM {interaction.user.display_name}")
        await reply(interaction, f"{player.display_name} is now {ROLE_REGISTRY[actions.normalise_role(role)].title()}.")

    @app_commands.command(name="modifier", description="Add or remove a modifier (lover, turned_wolf, ...)")
    @app_commands.autocomplete(modifier=modifier_autocomplete)
    @app_commands.choices(action=[app_commands.Choice(name="add", value="add"),
                                  app_commands.Choice(name="remove", value="remove")])
    async def modifier(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                       player: discord.Member, modifier: str) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            p = state.player(player.id)
            if action.value == "add":
                flow.add_modifier(state, p, modifier, reason=f"GM {interaction.user.display_name}")
            else:
                flow.remove_modifier(state, p, modifier, reason=f"GM {interaction.user.display_name}")
        await reply(interaction, f"{action.value} {modifier}: {player.display_name}")

    @app_commands.command(name="set_faction", description="Change a player's base faction")
    @app_commands.choices(faction=[app_commands.Choice(name=f.display, value=f.name) for f in FACTIONS.values()])
    async def set_faction(self, interaction: discord.Interaction, player: discord.Member,
                          faction: app_commands.Choice[str]) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            p = state.player(player.id)
            old = p.faction
            p.faction = faction.value
            state.log("GM", f"{p.display_name}: faction {old} → {faction.value}", actor=interaction.user.id,
                      targets=[p.user_id], alert=True)
        await reply(interaction, f"{player.display_name} now belongs to the {faction.name}.")

    @app_commands.command(name="group", description="Add someone to a shared chat, or move them out (read-only)")
    @app_commands.autocomplete(group=group_autocomplete)
    @app_commands.choices(action=[app_commands.Choice(name="add", value="add"),
                                  app_commands.Choice(name="remove (keeps read-only access)", value="remove")])
    async def group(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                    player: discord.Member, group: str) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            g = state.group(group)
            p = state.player(player.id)
            if action.value == "add":
                g.add(p.user_id)
            else:
                g.leave(p.user_id)
            state.log("GM", f"{p.display_name}: {action.value} {g.name}", actor=interaction.user.id, targets=[p.user_id])
        await reply(interaction, f"{player.display_name}: {action.value} {group}.")

    @app_commands.command(name="decide", description="Make a pending decision on someone's behalf")
    async def decide(self, interaction: discord.Interaction, decision_id: int, choice: discord.Member) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            result = flow.resolve_decision(state, decision_id, choice.id, by=interaction.user.id, by_gm=True)
            for title, text in result.reports:
                state.report(title, text)
        await reply(interaction, f"Decision #{decision_id}: {choice.display_name}.")

    @app_commands.command(name="kill_list", description="Show the Coven kill list, or replace it (comma-separated roles)")
    async def kill_list(self, interaction: discord.Interaction, roles: str | None = None) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            if roles:
                names = [actions.normalise_role(r) for r in roles.split(",") if r.strip()]
                state.data["coven_kill_list"] = names
                state.log("GM", f"Coven kill list set by {interaction.user.display_name}: {', '.join(names)}",
                          actor=interaction.user.id, alert=True)
            current = state.data.get("coven_kill_list", [])
        text = ", ".join(ROLE_REGISTRY[r].title() if r in ROLE_REGISTRY else r for r in current)
        await reply(interaction, f"**Coven kill list ({len(current)}):** {text or 'not generated yet'}")

    # --- mayor & public ----------------------------------------------------------------
    @app_commands.command(name="mayor", description="Set the Mayor, or open/close a (re-)election")
    @app_commands.choices(action=[app_commands.Choice(name="set", value="set"),
                                  app_commands.Choice(name="open election", value="open"),
                                  app_commands.Choice(name="close election", value="close")])
    async def mayor(self, interaction: discord.Interaction, action: app_commands.Choice[str],
                    player: discord.Member | None = None) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            if action.value == "set":
                if player is None:
                    raise GameError("Who should be Mayor?")
                state.mayor = state.player(player.id).user_id
                state.mayor_successor = None
                state.emit(Announcement(title="A NEW MAYOR", text=f"**{player.display_name}** is the Mayor."))
                state.log("MAYOR", f"GM set {player.display_name} as Mayor.", actor=interaction.user.id)
            elif action.value == "open":
                voting.open_ballot(state, voting.MAYOR, allow_abstain=False)
                state.emit(Announcement(title="MAYOR ELECTION", text="Vote for a Mayor with `/mayor vote`!"))
            else:
                ballot = voting.close_ballot(state, voting.MAYOR)
                if ballot is None:
                    raise GameError("No mayor election is open.")
                flow._finish_mayor_election(state, ballot)
        await reply(interaction, "Done.")

    @app_commands.command(name="announce", description="Post an announcement as the bot")
    async def announce(self, interaction: discord.Interaction, title: str, text: str) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            state.emit(Announcement(title=title, text=text))
            state.log("GM", f"Announcement by {interaction.user.display_name}: {title}", actor=interaction.user.id)
        await reply(interaction, "Announcement queued.")

    @app_commands.command(name="newspaper", description="Set the image for the next newspaper (posted at 12:00)")
    async def newspaper(self, interaction: discord.Interaction, image_url: str) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            state.settings.newspaper_url = image_url
            state.log("NEWSPAPER", f"Newspaper image set by {interaction.user.display_name}: {image_url}",
                      actor=interaction.user.id)
        await reply(interaction, "Newspaper image set.")

    @app_commands.command(name="lockdown", description="Turn the discussion lockdown on or off by hand")
    async def lockdown(self, interaction: discord.Interaction, on: bool) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            state.lockdown = on
            state.log("GM", f"Lockdown {'on' if on else 'off'} by {interaction.user.display_name}",
                      actor=interaction.user.id, alert=True)
        await reply(interaction, f"Lockdown {'on' if on else 'off'}.")

    # --- clock -------------------------------------------------------------------------
    clock = app_commands.Group(name="clock", description="Pause, step and roll back the game clock")

    @clock.command(name="pause", description="Pause the game clock (no automatic transitions)")
    async def pause(self, interaction: discord.Interaction) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            state.paused = True
            state.log("GM", f"Clock paused by {interaction.user.display_name}.", actor=interaction.user.id, alert=True)
        await reply(interaction, "⏸️ Paused. `/gm clock resume` to continue, `/gm clock advance` to step manually.")

    @clock.command(name="resume", description="Resume the clock; missed transitions run in order")
    async def resume(self, interaction: discord.Interaction) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            state.paused = False
            state.data["catch_up_approved"] = True
            state.log("GM", f"Clock resumed by {interaction.user.display_name}.", actor=interaction.user.id, alert=True)
        await reply(interaction, "▶️ Resumed. Any missed transitions will run in order within a minute.")

    @clock.command(name="advance", description="Run the next transition right now (for testing / fixing)")
    async def advance(self, interaction: discord.Interaction) -> None:
        scheduler = self.bot.get_cog("Scheduler")
        handle = runtime.games.get(interaction.guild_id)
        if handle.state.next_transition is None:
            raise GameError("There is no next transition.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        kind = TransitionKind(handle.state.next_transition.kind)
        await scheduler.run_transition(handle, kind, now_in(handle.state), manual_by=interaction.user)
        await reply(interaction, f"Ran **{kind.value}**. Next: {handle.state.next_transition.kind if handle.state.next_transition else 'none'}.")

    @clock.command(name="reschedule", description="Recompute the next transition from now")
    async def reschedule(self, interaction: discord.Interaction) -> None:
        async with runtime.games.mutate(interaction.guild_id) as state:
            state.next_transition = next_transition(state, now_in(state))
            state.log("GM", f"Next transition recomputed: {state.next_transition}", actor=interaction.user.id)
            text = f"{state.next_transition.kind} at {state.next_transition.at}" if state.next_transition else "none"
        await reply(interaction, f"Next: {text}")

    @clock.command(name="snapshots", description="List snapshots (taken before every transition)")
    async def snapshots(self, interaction: discord.Interaction) -> None:
        handle = runtime.games.get(interaction.guild_id)
        rows = await runtime.db.snapshots(handle.game_id)
        await reply(interaction, "\n".join(f"#{i} — {label} ({at[:16]})" for i, label, at in rows) or "No snapshots.")

    @clock.command(name="rollback", description="Restore a snapshot (messages already sent stay)")
    async def rollback(self, interaction: discord.Interaction, snapshot_id: int) -> None:
        await runtime.games.restore(interaction.guild_id, snapshot_id, by=interaction.user.id)
        await reply(interaction, f"Rolled back to snapshot #{snapshot_id}. The current state was snapshotted first. "
                                 "Check `/gm status` - Discord messages already sent can't be undone.")

    @app_commands.command(name="end_game", description="End the game and announce the winner")
    @app_commands.choices(winner=[app_commands.Choice(name=f.display, value=f.name) for f in FACTIONS.values()]
                          + [app_commands.Choice(name="nobody / other", value="none")])
    async def end_game(self, interaction: discord.Interaction, winner: app_commands.Choice[str]) -> None:
        async with runtime.games.mutate(interaction.guild_id, snapshot="before game end") as state:
            flow.end_game(state, None if winner.value == "none" else winner.value, now_in(state))
        await reply(interaction, "The game has ended.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GM(bot))
