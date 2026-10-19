"""SQLite persistence.

Tables
  games      one row per game (one per server, kept after it ends until /game delete);
             the full GameState as JSON, rewritten atomically
  snapshots  the state before every phase transition (GM rollback)
  reports    resolution reports (night previews/finals, dusk...)
  events     append-only audit log; `posted` tracks delivery to the mod channel
  outbox     effects waiting to be delivered to Discord

A game's state, its new log entries, effects and reports are written in ONE
transaction, so a crash can never leave them out of step. Nothing is deleted
while a game exists - finished games, delivered effects and posted events are
kept until a GM deletes the game with /game delete.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import aiosqlite

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS games(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        phase TEXT,
        day INTEGER,
        state TEXT NOT NULL,
        state_version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS games_guild ON games(guild_id, status)",
    """CREATE TABLE IF NOT EXISTS snapshots(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        label TEXT NOT NULL,
        day INTEGER,
        phase TEXT,
        state TEXT NOT NULL,
        state_version INTEGER NOT NULL,
        created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS reports(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        guild_id INTEGER NOT NULL,
        day INTEGER,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        posted INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER,
        guild_id INTEGER NOT NULL,
        at TEXT NOT NULL,
        day INTEGER,
        phase TEXT,
        category TEXT NOT NULL,
        message TEXT NOT NULL,
        actor_id INTEGER,
        target_ids TEXT,
        data TEXT,
        alert INTEGER NOT NULL DEFAULT 0,
        posted INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS events_unposted ON events(posted, id)",
    "CREATE INDEX IF NOT EXISTS events_game ON events(game_id, id)",
    """CREATE TABLE IF NOT EXISTS outbox(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        guild_id INTEGER NOT NULL,
        effect TEXT NOT NULL,
        created_at TEXT NOT NULL,
        delivered_at TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT)""",
    "CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(game_id, delivered_at, id)",
]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GameRow:
    id: int
    guild_id: int
    status: str
    state: str
    state_version: int


@dataclass
class EventRow:
    id: int
    game_id: int | None
    guild_id: int
    at: str
    day: int | None
    phase: str | None
    category: str
    message: str
    actor_id: int | None
    target_ids: list[int]
    data: dict[str, Any]
    alert: bool


@dataclass
class ReportRow:
    id: int
    game_id: int
    guild_id: int
    day: int | None
    title: str
    body: str
    created_at: str


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        # One connection is shared by every coroutine: writes are serialised so a
        # standalone insert can never commit half of another write's transaction.
        self.write_lock = asyncio.Lock()

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        for statement in SCHEMA:
            await self.conn.execute(statement)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self.conn is None:
            raise RuntimeError("Database is not connected")
        return self.conn

    # --- games ---------------------------------------------------------------
    async def create_game(self, guild_id: int, state_json: str, version: int) -> int:
        async with self.write_lock:
            return await self._create_game(guild_id, state_json, version)

    async def _create_game(self, guild_id: int, state_json: str, version: int) -> int:
        now = utcnow()
        cursor = await self.db.execute(
            "INSERT INTO games(guild_id, status, phase, day, state, state_version, created_at, updated_at) "
            "VALUES (?, 'setup', 'setup', 0, ?, ?, ?, ?)",
            (guild_id, state_json, version, now, now),
        )
        await self.db.commit()
        return int(cursor.lastrowid)

    async def active_games(self) -> list[GameRow]:
        async with self.db.execute(
            "SELECT id, guild_id, status, state, state_version FROM games ORDER BY id"
        ) as cursor:
            rows = await cursor.fetchall()
        return [GameRow(r["id"], r["guild_id"], r["status"], r["state"], r["state_version"]) for r in rows]

    async def commit_game(self, **kwargs: Any) -> None:
        async with self.write_lock:
            return await self._commit_game(**kwargs)

    async def _commit_game(
        self, *, game_id: int, guild_id: int, status: str, phase: str, day: int, state_json: str, version: int,
        events: Iterable[dict[str, Any]] = (), effects: Iterable[str] = (), reports: Iterable[tuple[str, str]] = (),
        snapshot: tuple[str, str, str, int] | None = None,
    ) -> None:
        """Write the state plus everything it produced in one transaction.
        snapshot = (label, state_json, phase, day) of the state *before* the change."""
        now = utcnow()
        db = self.db
        try:
            await db.execute("BEGIN")
            if snapshot is not None:
                label, snap_json, snap_phase, snap_day = snapshot
                await db.execute(
                    "INSERT INTO snapshots(game_id, label, day, phase, state, state_version, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (game_id, label, snap_day, snap_phase, snap_json, version, now),
                )
            await db.execute(
                "UPDATE games SET status=?, phase=?, day=?, state=?, state_version=?, updated_at=? WHERE id=?",
                (status, phase, day, state_json, version, now, game_id),
            )
            for event in events:
                await db.execute(
                    "INSERT INTO events(game_id, guild_id, at, day, phase, category, message, actor_id, target_ids, data, alert) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (game_id, guild_id, now, day, phase, event["category"], event["message"], event.get("actor"),
                     json.dumps(event.get("targets") or []), json.dumps(event.get("data") or {}, default=str),
                     1 if event.get("alert") else 0),
                )
            for effect in effects:
                await db.execute(
                    "INSERT INTO outbox(game_id, guild_id, effect, created_at) VALUES (?, ?, ?, ?)",
                    (game_id, guild_id, effect, now),
                )
            for title, body in reports:
                await db.execute(
                    "INSERT INTO reports(game_id, guild_id, day, title, body, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (game_id, guild_id, day, title, body, now),
                )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise

    async def delete_game(self, game_id: int) -> None:
        async with self.write_lock:
            try:
                await self.db.execute("BEGIN")
                for table in ("snapshots", "reports", "events", "outbox"):
                    await self.db.execute(f"DELETE FROM {table} WHERE game_id = ?", (game_id,))
                await self.db.execute("DELETE FROM games WHERE id = ?", (game_id,))
                await self.db.commit()
            except BaseException:
                await self.db.rollback()
                raise

    # --- events ----------------------------------------------------------------
    async def add_event(self, **kwargs: Any) -> None:
        async with self.write_lock:
            return await self._add_event(**kwargs)

    async def _add_event(self, *, guild_id: int, game_id: int | None, category: str, message: str,
                        day: int | None = None, phase: str | None = None, actor: int | None = None,
                        alert: bool = False, data: dict[str, Any] | None = None) -> None:
        """Standalone log entry (errors, things outside a game mutation)."""
        await self.db.execute(
            "INSERT INTO events(game_id, guild_id, at, day, phase, category, message, actor_id, target_ids, data, alert) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)",
            (game_id, guild_id, utcnow(), day, phase, category, message, actor,
             json.dumps(data or {}, default=str), 1 if alert else 0),
        )
        await self.db.commit()

    async def unposted_events(self, limit: int = 200) -> list[EventRow]:
        async with self.db.execute(
            "SELECT * FROM events WHERE posted = 0 ORDER BY id LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._event(r) for r in rows]

    async def mark_events_posted(self, ids: list[int]) -> None:
        async with self.write_lock:
            return await self._mark_events_posted(ids)

    async def _mark_events_posted(self, ids: list[int]) -> None:
        if not ids:
            return
        await self.db.executemany("UPDATE events SET posted = 1 WHERE id = ?", [(i,) for i in ids])
        await self.db.commit()

    async def recent_events(self, game_id: int, *, limit: int = 30, category: str | None = None,
                            player: int | None = None) -> list[EventRow]:
        query = "SELECT * FROM events WHERE game_id = ?"
        args: list[Any] = [game_id]
        if category:
            query += " AND category = ?"
            args.append(category.upper())
        if player is not None:
            query += " AND (actor_id = ? OR target_ids LIKE ?)"
            args.extend([player, f"%{player}%"])
        query += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        async with self.db.execute(query, args) as cursor:
            rows = await cursor.fetchall()
        return [self._event(r) for r in reversed(rows)]

    @staticmethod
    def _event(r: aiosqlite.Row) -> EventRow:
        return EventRow(
            id=r["id"], game_id=r["game_id"], guild_id=r["guild_id"], at=r["at"], day=r["day"], phase=r["phase"],
            category=r["category"], message=r["message"], actor_id=r["actor_id"],
            target_ids=json.loads(r["target_ids"] or "[]"), data=json.loads(r["data"] or "{}"), alert=bool(r["alert"]),
        )

    # --- reports ---------------------------------------------------------------
    async def unposted_reports(self) -> list[ReportRow]:
        async with self.db.execute("SELECT * FROM reports WHERE posted = 0 ORDER BY id") as cursor:
            rows = await cursor.fetchall()
        return [ReportRow(r["id"], r["game_id"], r["guild_id"], r["day"], r["title"], r["body"], r["created_at"])
                for r in rows]

    async def mark_report_posted(self, report_id: int) -> None:
        async with self.write_lock:
            return await self._mark_report_posted(report_id)

    async def _mark_report_posted(self, report_id: int) -> None:
        await self.db.execute("UPDATE reports SET posted = 1 WHERE id = ?", (report_id,))
        await self.db.commit()

    async def latest_report(self, game_id: int, title_prefix: str) -> ReportRow | None:
        async with self.db.execute(
            "SELECT * FROM reports WHERE game_id = ? AND title LIKE ? ORDER BY id DESC LIMIT 1",
            (game_id, f"{title_prefix}%"),
        ) as cursor:
            r = await cursor.fetchone()
        if r is None:
            return None
        return ReportRow(r["id"], r["game_id"], r["guild_id"], r["day"], r["title"], r["body"], r["created_at"])

    # --- outbox ----------------------------------------------------------------
    async def pending_effects(self, game_id: int, max_attempts: int = 5) -> list[tuple[int, str, int]]:
        async with self.db.execute(
            "SELECT id, effect, attempts FROM outbox WHERE game_id = ? AND delivered_at IS NULL AND attempts < ? ORDER BY id",
            (game_id, max_attempts),
        ) as cursor:
            rows = await cursor.fetchall()
        return [(r["id"], r["effect"], r["attempts"]) for r in rows]

    async def mark_effect_delivered(self, effect_id: int) -> None:
        async with self.write_lock:
            return await self._mark_effect_delivered(effect_id)

    async def _mark_effect_delivered(self, effect_id: int) -> None:
        await self.db.execute("UPDATE outbox SET delivered_at = ? WHERE id = ?", (utcnow(), effect_id))
        await self.db.commit()

    async def mark_effect_failed(self, effect_id: int, error: str) -> int:
        async with self.write_lock:
            return await self._mark_effect_failed(effect_id, error)

    async def _mark_effect_failed(self, effect_id: int, error: str) -> int:
        await self.db.execute(
            "UPDATE outbox SET attempts = attempts + 1, error = ? WHERE id = ?", (error[:1000], effect_id)
        )
        await self.db.commit()
        async with self.db.execute("SELECT attempts FROM outbox WHERE id = ?", (effect_id,)) as cursor:
            row = await cursor.fetchone()
        return int(row["attempts"]) if row else 0

    # --- snapshots -------------------------------------------------------------
    async def snapshots(self, game_id: int, limit: int = 15) -> list[tuple[int, str, str]]:
        async with self.db.execute(
            "SELECT id, label, created_at FROM snapshots WHERE game_id = ? ORDER BY id DESC LIMIT ?", (game_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
        return [(r["id"], r["label"], r["created_at"]) for r in rows]

    async def snapshot(self, game_id: int, snapshot_id: int) -> tuple[str, int] | None:
        async with self.db.execute(
            "SELECT state, state_version FROM snapshots WHERE game_id = ? AND id = ?", (game_id, snapshot_id)
        ) as cursor:
            row = await cursor.fetchone()
        return (row["state"], row["state_version"]) if row else None
