import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Load Admin IDs as a list of integers
_admin_ids_str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in _admin_ids_str.split(",") if x.strip().isdigit()]

# Guild & Role IDs
GUILD_ID = int(os.getenv("GUILD_ID") or 0)
PARTICIPANT_ROLE_ID = int(os.getenv("PARTICIPANT_ROLE_ID") or 0)

# Channel & Category IDs
ADMIN_LOG_CHANNEL_ID = int(os.getenv("ADMIN_LOG_CHANNEL_ID") or 0)
APPROVE_ANNOUNCE_CHANNEL_ID = int(os.getenv("APPROVE_ANNOUNCE_CHANNEL_ID") or 0)
TEAM_CHANNEL_CATEGORY_ID = int(os.getenv("TEAM_CHANNEL_CATEGORY_ID") or 0)
MATCH_CATEGORY_ID = int(os.getenv("MATCH_CATEGORY_ID") or 0)
ARCHIVE_CATEGORY_ID = int(os.getenv("ARCHIVE_CATEGORY_ID") or 0)
MATCH_EMBED_CHANNEL_ID = int(os.getenv("MATCH_EMBED_CHANNEL_ID") or 0)
# Keepalive and server configuration
RENDER_URL = os.getenv("RENDER_URL", "")
PORT = int(os.getenv("PORT", "8080"))
KEEPALIVE_INTERVAL = int(os.getenv("KEEPALIVE_INTERVAL", "300"))
