"""
Shared autocomplete helpers used across multiple cogs.
Import these and register them with @app_commands.autocomplete().
"""
import discord
from discord import app_commands

import bot.db.connection as connection
from bot.utils.constants import DISTRICT_NAMES


async def district_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for district names (all 9 districts)."""
    choices = []
    for district_num, district_name in DISTRICT_NAMES.items():
        if current.lower() in district_name.lower():
            choices.append(app_commands.Choice(name=district_name, value=district_name))
    return choices[:25]


async def team_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for approved team names."""
    async with connection.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT name FROM teams WHERE is_approved = TRUE AND LOWER(name) LIKE $1 ORDER BY name LIMIT 25",
            f"%{current.lower()}%"
        )
    return [app_commands.Choice(name=r["name"], value=r["name"]) for r in rows]


async def active_match_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for active matches (status='active')."""
    async with connection.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT m.id, t1.name AS t1, t2.name AS t2
            FROM matches m
            JOIN teams t1 ON m.team1_id = t1.id
            JOIN teams t2 ON m.team2_id = t2.id
            WHERE m.status = 'active'
            ORDER BY m.id DESC LIMIT 25
            """
        )
    choices = []
    for r in rows:
        label = f"#{r['id']}: {r['t1']} vs {r['t2']}"
        if current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label[:100], value=r["id"]))
    return choices


async def pending_or_scheduled_match_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for pending/scheduled matches."""
    async with connection.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT m.id, t1.name AS t1, t2.name AS t2, m.status
            FROM matches m
            JOIN teams t1 ON m.team1_id = t1.id
            JOIN teams t2 ON m.team2_id = t2.id
            WHERE m.status IN ('pending', 'scheduled')
            ORDER BY m.id DESC LIMIT 25
            """
        )
    choices = []
    for r in rows:
        label = f"#{r['id']}: {r['t1']} vs {r['t2']} ({r['status']})"
        if current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label[:100], value=r["id"]))
    return choices


async def completed_match_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for completed matches only."""
    async with connection.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT m.id, t1.name AS t1, t2.name AS t2
            FROM matches m
            JOIN teams t1 ON m.team1_id = t1.id
            JOIN teams t2 ON m.team2_id = t2.id
            WHERE m.status = 'completed'
            ORDER BY m.id DESC LIMIT 25
            """
        )
    choices = []
    for r in rows:
        label = f"#{r['id']}: {r['t1']} vs {r['t2']}"
        if current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label[:100], value=r["id"]))
    return choices
