import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")          # dev guild, for instant sync
ENV = os.getenv("ENV", "development")

if TOKEN is None:
    raise RuntimeError("DISCORD_TOKEN not set in .env")