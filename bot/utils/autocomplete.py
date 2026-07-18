"""
Shared autocomplete helpers used across multiple cogs.
Import these and register them with @app_commands.autocomplete().
"""
import discord
from discord import app_commands
from datetime import datetime, timedelta
import asyncio

import bot.db.connection as connection
from bot.utils.constants import DISTRICT_NAMES

# ── Autocomplete Cache ────────────────────────────────────────────────────────
_team_cache = None
_team_cache_expiry = None
_team_cache_lock = asyncio.Lock()

_match_cache = None
_match_cache_expiry = None
_match_cache_lock = asyncio.Lock()

CACHE_TTL = 300  # 5 minutes


async def district_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for district names (all 9 districts)."""
    choices = []
    for district_num, district_name in DISTRICT_NAMES.items():
        if current.lower() in district_name.lower():
            choices.append(app_commands.Choice(name=district_name, value=district_name))
    return choices[:25]


async def team_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for approved team names with caching to prevent rate limits."""
    global _team_cache, _team_cache_expiry
    
    async with _team_cache_lock:
        now = datetime.now()
        if _team_cache is None or _team_cache_expiry is None or now > _team_cache_expiry:
            async with connection.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT name FROM teams WHERE is_approved = TRUE ORDER BY name"
                )
            _team_cache = [r["name"] for r in rows]
            _team_cache_expiry = now + timedelta(seconds=CACHE_TTL)
    
    # Filter in memory instead of database
    current_lower = current.lower()
    matches = [name for name in _team_cache if current_lower in name.lower()]
    return [app_commands.Choice(name=name, value=name) for name in matches[:25]]


async def active_match_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for active matches with caching."""
    global _match_cache, _match_cache_expiry
    
    async with _match_cache_lock:
        now = datetime.now()
        if _match_cache is None or _match_cache_expiry is None or now > _match_cache_expiry:
            async with connection.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT m.id, m.status, t1.name AS t1, t2.name AS t2
                    FROM matches m
                    JOIN teams t1 ON m.team1_id = t1.id
                    JOIN teams t2 ON m.team2_id = t2.id
                    ORDER BY m.id DESC
                    """
                )
            _match_cache = rows
            _match_cache_expiry = now + timedelta(seconds=CACHE_TTL)
    
    # Filter in memory
    choices = []
    current_lower = current.lower()
    for r in _match_cache:
        if r["status"] == "active":
            label = f"#{r['id']}: {r['t1']} vs {r['t2']}"
            if current_lower in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=r["id"]))
    return choices[:25]


async def pending_or_scheduled_match_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for pending/scheduled matches with caching."""
    global _match_cache, _match_cache_expiry
    
    async with _match_cache_lock:
        now = datetime.now()
        if _match_cache is None or _match_cache_expiry is None or now > _match_cache_expiry:
            async with connection.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT m.id, m.status, t1.name AS t1, t2.name AS t2
                    FROM matches m
                    JOIN teams t1 ON m.team1_id = t1.id
                    JOIN teams t2 ON m.team2_id = t2.id
                    ORDER BY m.id DESC
                    """
                )
            _match_cache = rows
            _match_cache_expiry = now + timedelta(seconds=CACHE_TTL)
    
    # Filter in memory
    choices = []
    current_lower = current.lower()
    for r in _match_cache:
        if r["status"] in ("pending", "scheduled"):
            label = f"#{r['id']}: {r['t1']} vs {r['t2']} ({r['status']})"
            if current_lower in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=r["id"]))
    return choices[:25]


async def completed_match_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for completed matches with caching."""
    global _match_cache, _match_cache_expiry
    
    async with _match_cache_lock:
        now = datetime.now()
        if _match_cache is None or _match_cache_expiry is None or now > _match_cache_expiry:
            async with connection.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT m.id, m.status, t1.name AS t1, t2.name AS t2
                    FROM matches m
                    JOIN teams t1 ON m.team1_id = t1.id
                    JOIN teams t2 ON m.team2_id = t2.id
                    ORDER BY m.id DESC
                    """
                )
            _match_cache = rows
            _match_cache_expiry = now + timedelta(seconds=CACHE_TTL)
    
    # Filter in memory
    choices = []
    current_lower = current.lower()
    for r in _match_cache:
        if r["status"] == "completed":
            label = f"#{r['id']}: {r['t1']} vs {r['t2']}"
            if current_lower in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=r["id"]))
    return choices[:25]
