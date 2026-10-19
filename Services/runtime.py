"""Process-wide service instances, set up once in bot.py's setup_hook.

Cogs and role commands reach the services through here instead of passing
them around."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discord.ext.commands import Bot

    from Services.audit import AuditPoster
    from Services.channels import ChannelManager
    from Services.effects import EffectDelivery
    from Services.game_service import GameService
    from Services.worker import GameWorker
    from Storage.db import Database


class Runtime:
    bot: "Bot"
    db: "Database"
    games: "GameService"
    audit: "AuditPoster"
    channels: "ChannelManager"
    delivery: "EffectDelivery"
    worker: "GameWorker"


runtime = Runtime()
