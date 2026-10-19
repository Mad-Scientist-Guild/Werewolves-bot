import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")                  # dev guild, for instant command sync
ENV = os.getenv("ENV", "development")
DB_PATH = os.getenv("DB_PATH", "werewolves.db")
LOG_DIR = os.getenv("LOG_DIR", "logs")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Amsterdam")
GM_ROLE_ID = int(os.environ["GM_ROLE_ID"]) if os.getenv("GM_ROLE_ID") else None
