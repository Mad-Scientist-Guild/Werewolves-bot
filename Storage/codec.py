"""GameState <-> JSON text for the database."""
from __future__ import annotations

import json

from Core.serialize import dump, load
from Core.state import GameState


def encode(state: GameState) -> str:
    return json.dumps(dump(state), ensure_ascii=False, separators=(",", ":"))


def decode(text: str) -> GameState:
    return load(GameState, json.loads(text))
