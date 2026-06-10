import sys
import os
import asyncio
import aiohttp
import http.server
import threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord
from discord.ext import commands
from discord import app_commands
import logging
from bot.config import DISCORD_TOKEN, PORT, RENDER_URL, KEEPALIVE_INTERVAL
from bot.db.connection import init_db, close_db
from bot.db.models import setup_schema
from bot.utils.checks import NotAdmin, NotTeamLeader, NotTeamMember
from bot.utils.embeds import error_embed

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

    async def on_app_command_error(self, interaction: discord.Interaction, error: Exception):
        """Central handler for slash command errors, including permission check failures."""
        if isinstance(error, (NotAdmin, NotTeamLeader, NotTeamMember)):
            embed = error_embed("Permission Denied", str(error))
        elif isinstance(error, app_commands.CommandNotFound):
            return  # ignore silently
        else:
            log.error(f"Unhandled app command error: {error}", exc_info=error)
            embed = error_embed("Unexpected Error", "Something went wrong. Please try again.")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            pass  # interaction may have already expired

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
    if not RENDER_URL:
        print("[Keepalive] RENDER_URL not set — self-ping disabled.")
        return
    await asyncio.sleep(30)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(
                    f"{RENDER_URL}/health",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    print(f"[Keepalive] Ping → {resp.status}")
            except Exception as exc:
                print(f"[Keepalive] Ping failed: {exc}")
            await asyncio.sleep(KEEPALIVE_INTERVAL)

async def main():
    bot = TournamentManagerBot()
    asyncio.create_task(self_ping())
    try:
        async with bot:
            await bot.start(DISCORD_TOKEN)
    except discord.LoginFailure as exc:
        log.error("Discord login failed. Check that DISCORD_TOKEN is set and valid.")
        raise
    except aiohttp.ClientConnectorError as exc:
        log.error(
            "Discord connection failed. Verify internet access and that discord.com can be resolved from this machine."
        )
        raise

if __name__ == "__main__":
    start_http_server_sync(PORT)
    asyncio.run(main())
