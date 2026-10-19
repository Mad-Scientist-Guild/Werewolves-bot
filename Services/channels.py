"""Creates the game's channels and keeps their permissions in line with the
game state.

The reconciler is idempotent: game state says who should see/write where
(Core.access), and `sync()` changes only the permission overwrites that
differ. It runs after every committed change and on startup, so a crash or
a manual edit in Discord is corrected automatically.

Channels are never renamed or deleted; names are fixed at creation.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from Core.access import Access, player_access
from Core.state import GameState, Group, GroupKind, PublicStatus
from Services.discord_utils import slug
from Services.game_service import GameHandle, GameService
from Storage.db import Database

log = logging.getLogger("werewolves.channels")

CATEGORY_NAME = "XP Werewolves"
CATEGORY_LIMIT = 50

ACCESS_OVERWRITES: dict[Access, discord.PermissionOverwrite] = {
    Access.WRITE: discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=True, add_reactions=True,
        attach_files=True, embed_links=True, send_messages_in_threads=True,
    ),
    Access.READ: discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=False, add_reactions=False,
        send_messages_in_threads=False, create_public_threads=False, create_private_threads=False,
    ),
    Access.REACT: discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=False, add_reactions=True,
        use_external_emojis=False, send_messages_in_threads=False, create_public_threads=False,
        create_private_threads=False,
    ),
    Access.NONE: discord.PermissionOverwrite(view_channel=False),
}

STAFF = discord.PermissionOverwrite(
    view_channel=True, read_message_history=True, send_messages=True, add_reactions=True,
    attach_files=True, embed_links=True, manage_messages=True,
)
BOT = discord.PermissionOverwrite(
    view_channel=True, read_message_history=True, send_messages=True, embed_links=True, attach_files=True,
    manage_channels=True, manage_permissions=True,
)

PUBLIC_ROLE_NAMES = {
    PublicStatus.DEAD: "Dead",
    PublicStatus.VENGEFUL_SPIRIT: "Vengeful Spirit",
    PublicStatus.SKELETON: "Skeleton",
}

# creation order inside the category
KIND_ORDER = [
    GroupKind.VILLAGE, GroupKind.DEAD, GroupKind.FAMILY, GroupKind.WOLVES, GroupKind.UNDEAD,
    GroupKind.SKELETONS, GroupKind.LOVERS, GroupKind.BROTHERS, GroupKind.COVEN, GroupKind.SPIRIT_LINE,
    GroupKind.CUSTOM, GroupKind.PRIVATE,
]


class ChannelManager:
    def __init__(self, bot: commands.Bot, games: GameService, db: Database):
        self.bot = bot
        self.games = games
        self.db = db

    # --- helpers ---------------------------------------------------------------
    def _gm_role(self, guild: discord.Guild, state: GameState) -> discord.Role | None:
        import config
        role_id = state.settings.gm_role_id or config.GM_ROLE_ID
        return guild.get_role(role_id) if role_id else None

    def _base_overwrites(self, guild: discord.Guild, state: GameState, *, public: bool = False) -> dict:
        everyone = (discord.PermissionOverwrite(view_channel=True, send_messages=False) if public
                    else discord.PermissionOverwrite(view_channel=False))
        overwrites: dict = {guild.default_role: everyone, guild.me: BOT}
        gm_role = self._gm_role(guild, state)
        if gm_role is not None:
            overwrites[gm_role] = STAFF
        return overwrites

    def _group_overwrites(self, guild: discord.Guild, state: GameState, group: Group) -> dict:
        overwrites = self._base_overwrites(guild, state)
        for player in state.players.values():
            access = player_access(state, group, player)
            member = guild.get_member(player.user_id)
            if member is not None and access is not Access.NONE:
                overwrites[member] = ACCESS_OVERWRITES[access]
        return overwrites

    async def _category(self, guild: discord.Guild, handle: GameHandle) -> discord.CategoryChannel:
        state = handle.state
        for category_id in state.categories:
            category = guild.get_channel(category_id)
            if isinstance(category, discord.CategoryChannel) and len(category.channels) < CATEGORY_LIMIT:
                return category
        number = len(state.categories) + 1
        name = CATEGORY_NAME if number == 1 else f"{CATEGORY_NAME} {number}"
        category = await guild.create_category(name, overwrites=self._base_overwrites(guild, state),
                                               reason="Werewolves game channels")
        async with self.games.mutate(guild.id) as mutable:
            mutable.categories.append(category.id)
            mutable.log("CHANNEL", f"Created category {name}.")
        return category

    # --- setup -----------------------------------------------------------------
    async def setup_base(self, guild: discord.Guild, handle: GameHandle, *,
                         announcements: discord.TextChannel | None = None,
                         votes: discord.TextChannel | None = None,
                         mod_log: discord.TextChannel | None = None) -> list[str]:
        """Category, the fixed public channels, the mod log and the public
        Discord roles. Existing channels can be passed in instead."""
        done: list[str] = []
        state = handle.state
        category = await self._category(guild, handle)
        found: dict[str, int] = {}
        for key, given, public in (("mod_log", mod_log, False), ("announcements", announcements, True),
                                   ("votes", votes, True)):
            if given is not None:
                found[key] = given.id
                continue
            existing = guild.get_channel(state.channels.get(key, 0))
            if existing is not None:
                continue
            overwrites = self._base_overwrites(guild, state, public=public)
            channel = await guild.create_text_channel(
                key.replace("_", "-"), category=category, overwrites=overwrites, reason="Werewolves game setup")
            found[key] = channel.id
            done.append(f"created #{channel.name}")

        roles: dict[str, int] = {}
        for status, name in PUBLIC_ROLE_NAMES.items():
            if guild.get_role(state.discord_roles.get(status.value, 0)) is not None:
                continue
            role = discord.utils.get(guild.roles, name=name)
            if role is None:
                role = await guild.create_role(name=name, mentionable=False, reason="Werewolves public status")
                done.append(f"created role @{name}")
            roles[status.value] = role.id

        async with self.games.mutate(guild.id) as mutable:
            mutable.channels.update(found)
            mutable.discord_roles.update(roles)
            if done or found:
                mutable.log("CHANNEL", "Base setup: " + (", ".join(done) or "linked existing channels"))
        return done

    async def ensure_group_channels(self, guild: discord.Guild, handle: GameHandle) -> int:
        """Create a channel for every group that doesn't have one yet."""
        state = handle.state
        missing = [g for g in state.groups.values()
                   if g.channel_id is None or guild.get_channel(g.channel_id) is None]
        if not missing:
            return 0
        missing.sort(key=lambda g: (KIND_ORDER.index(g.kind) if g.kind in KIND_ORDER else 99, g.key))
        created: dict[str, int] = {}
        recreated: list[str] = []
        for group in missing:
            category = await self._category(guild, handle)
            channel = await guild.create_text_channel(
                slug(group.name) or group.key, category=category, topic=group.topic or None,
                overwrites=self._group_overwrites(guild, state, group), reason="Werewolves game channel",
            )
            if group.channel_id is not None:
                recreated.append(group.name)
            created[group.key] = channel.id
        async with self.games.mutate(guild.id) as mutable:
            for key, channel_id in created.items():
                mutable.groups[key].channel_id = channel_id
            mutable.log("CHANNEL", f"Created {len(created)} channel(s): "
                        + ", ".join(mutable.groups[k].name for k in created))
            if recreated:
                mutable.log("CHANNEL", "These channels had disappeared and were recreated (old messages are in the "
                            "deleted channel's audit trail only): " + ", ".join(recreated), alert=True)
        return len(created)

    # --- reconciliation --------------------------------------------------------
    async def sync(self, guild: discord.Guild, handle: GameHandle) -> int:
        """Bring permission overwrites and public roles in line with state.
        Returns the number of changes made."""
        async with handle.lock:
            state = handle.state
            perm_plan: list[tuple[discord.TextChannel, discord.Member, discord.PermissionOverwrite, str]] = []
            for group in state.groups.values():
                channel = guild.get_channel(group.channel_id) if group.channel_id else None
                if not isinstance(channel, discord.TextChannel):
                    continue
                for player in state.players.values():
                    member = guild.get_member(player.user_id)
                    if member is None:
                        continue
                    access = player_access(state, group, player)
                    current = channel.overwrites_for(member)
                    if access is Access.NONE and current.is_empty():
                        continue
                    desired = ACCESS_OVERWRITES[access]
                    if current.pair() != desired.pair():
                        perm_plan.append((channel, member, desired, f"{player.display_name}: {group.name} → {access.value}"))
                # replaced players (the Reaper) lose access to the game's chats
                for player in state.players.values():
                    for old_id in player.previous_user_ids:
                        member = guild.get_member(old_id)
                        if member is not None and channel.overwrites_for(member).view_channel:
                            perm_plan.append((channel, member, ACCESS_OVERWRITES[Access.NONE],
                                              f"{member.display_name} (replaced): {group.name} → none"))

            role_plan: list[tuple[discord.Member, discord.Role, bool, str]] = []
            roles = {s: guild.get_role(state.discord_roles.get(s.value, 0)) for s in PUBLIC_ROLE_NAMES}
            for player in state.players.values():
                member = guild.get_member(player.user_id)
                if member is None:
                    continue
                for status, role in roles.items():
                    if role is None:
                        continue
                    want = player.public_status is status
                    has = role in member.roles
                    if want != has:
                        role_plan.append((member, role, want, f"{player.display_name}: {'+' if want else '-'}{role.name}"))

        changes: list[str] = []
        for channel, member, overwrite, label in perm_plan:
            try:
                await channel.set_permissions(member, overwrite=overwrite, reason="Werewolves state sync")
                changes.append(label)
            except discord.HTTPException as exc:
                log.warning("Could not set permissions (%s): %s", label, exc)
                changes.append(f"FAILED {label}: {exc}")
        for member, role, add, label in role_plan:
            try:
                if add:
                    await member.add_roles(role, reason="Werewolves public status")
                else:
                    await member.remove_roles(role, reason="Werewolves public status")
                changes.append(label)
            except discord.HTTPException as exc:
                log.warning("Could not change role (%s): %s", label, exc)
                changes.append(f"FAILED {label}: {exc}")

        if changes:
            failed = any(c.startswith("FAILED") for c in changes)
            text = "\n".join(changes)
            if len(text) > 3500:
                text = text[:3500] + f"\n… ({len(changes)} changes in total)"
            await self.db.add_event(guild_id=guild.id, game_id=handle.game_id, category="CHANNEL",
                                    message=f"Permissions synced ({len(changes)} change(s)):\n{text}",
                                    day=handle.state.day, phase=handle.state.phase.value, alert=failed)
        return len(changes)
