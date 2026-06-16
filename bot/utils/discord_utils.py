"""
Shared Discord API helpers.
"""
import discord
import logging
from typing import Optional

log = logging.getLogger(__name__)


async def get_username(bot: discord.Client, user_id: int, guild: Optional[discord.Guild] = None) -> str:
    """
    Return the best available display name for a user.
    If a guild is provided, tries the server nickname first (guild.get_member),
    then falls back to fetching the global user. Falls back to raw ID on failure.
    """
    if guild:
        member = guild.get_member(user_id)
        if member:
            return member.display_name
    try:
        user = await bot.fetch_user(user_id)
        return user.display_name or user.name
    except Exception:
        log.warning(f"Could not fetch user {user_id}")
        return str(user_id)


def player_link(user_id: int, display_name: str) -> str:
    """Format a player as a clickable bold hyperlink."""
    return f"[**{display_name}**](https://discord.com/users/{user_id})"


async def fetch_player_link(bot: discord.Client, user_id: int, guild: Optional[discord.Guild] = None) -> str:
    """Fetch display name and return a formatted hyperlink in one call.
    Pass guild to prefer the server nickname over the global username."""
    name = await get_username(bot, user_id, guild=guild)
    return player_link(user_id, name)
