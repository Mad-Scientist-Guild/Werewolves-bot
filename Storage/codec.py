"""GameState <-> JSON text, with versioned migrations.

Bump STATE_VERSION and add a migration whenever stored data needs more than
"missing fields get their default" (which the serializer already handles).
"""
from __future__ import annotations

import json
from typing import Any, Callable

from Core.serialize import dump, load
from Core.state import GameState

STATE_VERSION = 1

# version -> function upgrading a raw state dict from that version to version + 1
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def encode(state: GameState) -> str:
    return json.dumps(dump(state), ensure_ascii=False, separators=(",", ":"))


def decode(text: str, version: int = STATE_VERSION) -> GameState:
    data = json.loads(text)
    while version < STATE_VERSION:
        migrate = MIGRATIONS.get(version)
        if migrate is None:
            raise RuntimeError(f"No migration from state version {version}")
        data = migrate(data)
        version += 1
    return load(GameState, data)
