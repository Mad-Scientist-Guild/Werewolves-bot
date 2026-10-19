import re
from pathlib import Path

import discord
import pytest
from discord import app_commands
from discord.ext import commands

import Roles  # noqa: F401
from Core import flow
from Core.clock import TransitionKind
from Core.effects import Announcement
from Core.errors import GameError
from Core.state import Phase
from Services.game_service import GameService
from Services.role_commands import COMMAND_COGS
from Storage.codec import encode
from Storage.db import Database
from tests.builder import TZ

NAME_RE = re.compile(r"^[-_\w]{1,32}$")


async def load_bot() -> commands.Bot:
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    for cog_cls in COMMAND_COGS:
        await bot.add_cog(cog_cls(bot))
    for file in sorted(Path("Cogs").glob("*.py")):
        if not file.name.startswith("_"):
            await bot.load_extension(f"Cogs.{file.stem}")
    return bot


async def test_command_tree_respects_discord_limits():
    bot = await load_bot()
    try:
        top = bot.tree.get_commands()
        assert len(top) <= 100

        def check(command, depth=0):
            assert NAME_RE.match(command.name) and command.name == command.name.lower(), command.name
            assert 1 <= len(command.description) <= 100, f"{command.qualified_name}: description length"
            if isinstance(command, app_commands.Group):
                assert len(command.commands) <= 25, f"{command.qualified_name} has {len(command.commands)} subcommands"
                assert depth < 2
                for child in command.commands:
                    check(child, depth + 1)
            else:
                assert len(command.parameters) <= 25
                for param in command.parameters:
                    assert NAME_RE.match(param.name), param.name
                    assert len(param.description) <= 100

        for command in top:
            check(command)
        names = {c.name for c in top}
        assert {"game", "setup", "gm", "lynch", "mayor", "me", "silver_angel", "wolves"} <= names
    finally:
        for name in list(bot.cogs):
            await bot.remove_cog(name)


@pytest.fixture
async def service(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    yield GameService(db)
    await db.close()


async def test_state_survives_a_restart(service, tmp_path):
    handle = await service.create(1)
    async with service.mutate(1) as state:
        for i, role in enumerate(["silver_angel", "ancient_wolf", "villager"]):
            p = flow.add_player(state, 10 + i, f"p{i}")
            flow.set_role(state, p, role)
        state.emit(Announcement(text="hello"))
        state.report("Test report", "body")
    before = encode(handle.state)

    fresh = GameService(service.db)
    await fresh.load_all()
    assert encode(fresh.get(1).state) == before

    events = await service.db.recent_events(handle.game_id, limit=50)
    assert any("p0 joined" in e.message for e in events)
    assert len(await service.db.pending_effects(handle.game_id)) == 1
    assert (await service.db.unposted_reports())[0].title == "Test report"


async def test_failed_mutation_rolls_back(service):
    await service.create(1)
    with pytest.raises(GameError):
        async with service.mutate(1) as state:
            flow.add_player(state, 10, "p0")
            raise GameError("nope")
    assert service.get(1).state.players == {}
    events = await service.db.recent_events(service.get(1).game_id)
    assert not any("p0" in e.message for e in events)   # the log entry was rolled back too


async def test_snapshot_and_restore(service):
    handle = await service.create(1)
    async with service.mutate(1) as state:
        flow.add_player(state, 10, "p0")
    async with service.mutate(1, snapshot="before second player") as state:
        flow.add_player(state, 11, "p1")
    snaps = await service.db.snapshots(handle.game_id)
    assert snaps[0][1] == "before second player"
    restored = await service.restore(1, snaps[0][0], by=99)
    assert set(restored.players) == {10}
    assert (await service.db.snapshots(handle.game_id))[0][1].startswith("before rollback")


async def test_full_day_cycle_through_the_service(service):
    from datetime import datetime
    await service.create(1)
    async with service.mutate(1) as state:
        for i, role in enumerate(["ancient_wolf", "ancient_wolf", "villager", "villager", "silver_angel"]):
            flow.set_role(state, flow.add_player(state, 10 + i, f"p{i}"), role)
        flow.start_game(state, datetime(2026, 10, 5, 10, 0, tzinfo=TZ))
    for kind, hour in ((TransitionKind.NEWSPAPER, 12), (TransitionKind.DUSK, 19)):
        async with service.mutate(1, snapshot=kind.value) as state:
            flow.run_transition(state, kind, datetime(2026, 10, 5, hour, tzinfo=TZ))
    assert service.get(1).state.phase is Phase.NIGHT
    fresh = GameService(service.db)
    await fresh.load_all()
    assert fresh.get(1).state.phase is Phase.NIGHT
    assert fresh.get(1).state.ballots["wolves"].is_open


async def test_new_game_starts_with_the_default_role_pool(service):
    from Core.actor import ROLE_REGISTRY
    handle = await service.create(1)
    pool = handle.state.role_pool
    assert pool["brother"] == 3 and pool["seer"] == 1 and pool["rabid_wolf"] == 1
    assert "villager" not in pool and "werewolf" not in pool       # filler / not assignable
    assert set(pool) == {n for n, c in ROLE_REGISTRY.items() if c.assignable and n != "villager"}


def test_v1_state_migrates_categories():
    import json
    from Storage.codec import decode
    from Core.state import GameState
    from Core.serialize import dump
    raw = dump(GameState(guild_id=1))
    raw["categories"] = [111, 222]
    state = decode(json.dumps(raw), version=1)
    assert state.categories == {"legacy": [111, 222]}


def test_channels_go_into_the_right_categories():
    from Core.state import GroupKind
    from Services.channels import FIXED_CHANNEL_CATEGORY, category_key
    assert category_key(GroupKind.VILLAGE) == category_key(GroupKind.DEAD) == "general"
    assert category_key(GroupKind.FAMILY) == "families"
    assert category_key(GroupKind.PRIVATE) == "roles"
    assert {category_key(k) for k in (GroupKind.WOLVES, GroupKind.COVEN, GroupKind.LOVERS)} == {"factions"}
    assert FIXED_CHANNEL_CATEGORY == {"announcements": "important", "mod_log": "gm"}


async def test_end_before_start_keeps_everything_until_deleted(service):
    from datetime import datetime
    from Core.errors import GameAlreadyActive, NoActiveGame
    handle = await service.create(1)
    async with service.mutate(1) as state:
        flow.add_player(state, 10, "p0")
        flow.end_game(state, None, datetime(2026, 10, 5, 10, 0, tzinfo=TZ))      # never started
    with pytest.raises(GameAlreadyActive, match="delete"):
        await service.create(1)
    fresh = GameService(service.db)
    await fresh.load_all()                                                    # survives a restart
    assert fresh.get(1).state.phase is Phase.ENDED and 10 in fresh.get(1).state.players
    assert await service.db.recent_events(handle.game_id)
    await fresh.delete(1, by=99)
    with pytest.raises(NoActiveGame):
        fresh.get(1)
    assert await service.db.recent_events(handle.game_id) == []
    assert await service.db.active_games() == []
    await fresh.create(1)                                                     # a new game is possible again
