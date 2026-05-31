import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord
from discord.ext import commands
import logging
from bot.config import DISCORD_TOKEN
from bot.db.connection import init_db, close_db
from bot.db.models import setup_schema
import os

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

class TournamentManagerBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        # Initialize Database
        await init_db()
        await setup_schema()
        
        # Load Cogs
        for filename in os.listdir("bot/cogs"):
            if filename.endswith(".py"):
                await self.load_extension(f"bot.cogs.{filename[:-3]}")
                
        # Sync slash commands
        from bot.config import GUILD_ID
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info(f"Slash commands synced to guild {GUILD_ID}.")
        else:
            await self.tree.sync()
            log.info("Slash commands synced globally.")

    async def close(self):
        await close_db()
        await super().close()

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        log.info("------")

def start_http_server_sync(port: int):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive!")
        def log_message(self, *args):
            pass
    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[HTTP] Server started on port {port}")

async def self_ping():
    if not getattr(__import__('bot.config'), 'RENDER_URL', None):
        print("[Keepalive] RENDER_URL not set — self-ping disabled.")
        return
    await asyncio.sleep(30)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(
                    f"{getattr(__import__('bot.config'), 'RENDER_URL')}/health",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    print(f"[Keepalive] Ping → {resp.status}")
            except Exception as exc:
                print(f"[Keepalive] Ping failed: {exc}")
            await asyncio.sleep(getattr(__import__('bot.config'), 'KEEPALIVE_INTERVAL', 300))

async def main():
    asyncio.create_task(self_ping())
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    start_http_server_sync(PORT)
    asyncio.run(main())
