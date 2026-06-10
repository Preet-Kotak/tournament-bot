"""
Shared Discord API helpers.
"""
import discord
import logging

log = logging.getLogger(__name__)


async def get_username(bot: discord.Client, user_id: int) -> str:
    """
    Fetch a user's global display name from Discord.
    Falls back to their username, then to the raw ID string if the fetch fails.
    """
    try:
        user = await bot.fetch_user(user_id)
        return user.display_name or user.name
    except Exception:
        log.warning(f"Could not fetch user {user_id}")
        return str(user_id)


def player_link(user_id: int, display_name: str) -> str:
    """Format a player as a clickable bold hyperlink."""
    return f"[**{display_name}**](https://discord.com/users/{user_id})"


async def fetch_player_link(bot: discord.Client, user_id: int) -> str:
    """Fetch username and return a formatted hyperlink in one call."""
    name = await get_username(bot, user_id)
    return player_link(user_id, name)
