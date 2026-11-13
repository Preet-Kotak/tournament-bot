"""
Tournament permission checks and decorators for multi-tournament system.

This module provides:
- Helper functions to check user permissions (super admin, tournament admin, participant)
- Functions to get active tournament and tournament by ID
- Decorators for command access control
- Custom exceptions for permission failures
"""

import discord
from discord import app_commands
from typing import Optional
import bot.db.connection as connection
import logging

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Tournament Retrieval Functions
# ═══════════════════════════════════════════════════════════════════════════

async def get_active_tournament() -> Optional[dict]:
    """
    Get the currently active tournament (only one allowed at a time).
    
    Returns:
        dict: Tournament record with all fields, or None if no active tournament
    """
    async with connection.pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM tournaments WHERE status = 'active' LIMIT 1"
        )


async def get_tournament_by_id(tournament_id: int) -> Optional[dict]:
    """
    Get tournament by ID.
    
    Args:
        tournament_id: The tournament ID to retrieve
        
    Returns:
        dict: Tournament record with all fields, or None if not found
    """
    async with connection.pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM tournaments WHERE id = $1", tournament_id
        )


async def get_tournament_by_initials(initials: str) -> Optional[dict]:
    """
    Get tournament by its initials (e.g., "AI4", "CC1").
    
    Args:
        initials: Tournament initials (case-insensitive)
        
    Returns:
        dict: Tournament record with all fields, or None if not found
    """
    async with connection.pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM tournaments WHERE LOWER(initials) = LOWER($1)", initials
        )


async def get_all_tournaments() -> list[dict]:
    """
    Get all tournaments ordered by creation date (newest first).
    
    Returns:
        list[dict]: List of tournament records
    """
    async with connection.pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM tournaments ORDER BY created_at DESC"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Permission Check Functions
# ═══════════════════════════════════════════════════════════════════════════

async def is_super_admin(user_id: int) -> bool:
    """
    Check if user is a super admin (can create/manage tournaments).
    
    Super admins can:
    - Create new tournaments
    - Assign/remove tournament admins
    - Change tournament settings
    - Delete tournaments
    
    Super admins CANNOT:
    - Perform match operations (that's for tournament admins)
    - Approve teams, create matches, etc. (tournament admin only)
    
    Args:
        user_id: Discord user ID to check
        
    Returns:
        bool: True if user is a super admin
    """
    if not connection.pool:
        log.warning("Database pool not initialized in is_super_admin check")
        return False
        
    async with connection.pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM super_admins WHERE user_id = $1)",
            user_id
        )
        return exists


async def is_tournament_admin(user_id: int, tournament_id: int) -> bool:
    """
    Check if user is admin for a specific tournament.
    
    Tournament admins can:
    - Approve teams
    - Create/manage matches
    - Schedule matches
    - Override attack scores
    - View admin logs
    
    Args:
        user_id: Discord user ID to check
        tournament_id: Tournament ID to check admin status for
        
    Returns:
        bool: True if user is admin of the specified tournament
    """
    if not connection.pool:
        log.warning("Database pool not initialized in is_tournament_admin check")
        return False
        
    async with connection.pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM tournament_admins WHERE user_id = $1 AND tournament_id = $2)",
            user_id, tournament_id
        )
        return exists


async def is_tournament_participant(user_id: int, tournament_id: int, guild: discord.Guild) -> bool:
    """
    Check if user has participant role for the tournament.
    
    Args:
        user_id: Discord user ID to check
        tournament_id: Tournament ID to check participation in
        guild: Discord guild to check roles in
        
    Returns:
        bool: True if user has the tournament's participant role
    """
    tournament = await get_tournament_by_id(tournament_id)
    if not tournament or not tournament['participant_role_id']:
        return False
    
    member = guild.get_member(user_id)
    if not member:
        return False
    
    return any(role.id == tournament['participant_role_id'] for role in member.roles)


async def has_admin_role(user_id: int, tournament_id: int, guild: discord.Guild) -> bool:
    """
    Check if user has the tournament's admin role.
    
    Args:
        user_id: Discord user ID to check
        tournament_id: Tournament ID to check admin role for
        guild: Discord guild to check roles in
        
    Returns:
        bool: True if user has the tournament's admin role
    """
    tournament = await get_tournament_by_id(tournament_id)
    if not tournament or not tournament['admin_role_id']:
        return False
    
    member = guild.get_member(user_id)
    if not member:
        return False
    
    return any(role.id == tournament['admin_role_id'] for role in member.roles)


# ═══════════════════════════════════════════════════════════════════════════
# Custom Exceptions
# ═══════════════════════════════════════════════════════════════════════════

class NotSuperAdmin(app_commands.CheckFailure):
    """Raised when a user tries to use a super admin command without permission."""
    def __init__(self, message: str = "❌ This command requires Super Admin privileges."):
        super().__init__(message)


class NotTournamentAdmin(app_commands.CheckFailure):
    """Raised when a user tries to use a tournament admin command without permission."""
    def __init__(self, message: str = "❌ You must be a Tournament Admin to use this command."):
        super().__init__(message)


class NoActiveTournament(app_commands.CheckFailure):
    """Raised when a command requires an active tournament but none exists."""
    def __init__(self, message: str = "❌ No active tournament. A tournament must be active to use this command."):
        super().__init__(message)


class TournamentNotInRegistration(app_commands.CheckFailure):
    """Raised when a command requires the tournament to be in registration phase."""
    def __init__(self, message: str = "❌ Tournament is not in registration phase."):
        super().__init__(message)


class TournamentNotFound(app_commands.CheckFailure):
    """Raised when a specified tournament cannot be found."""
    def __init__(self, message: str = "❌ Tournament not found."):
        super().__init__(message)


# ═══════════════════════════════════════════════════════════════════════════
# Permission Decorators
# ═══════════════════════════════════════════════════════════════════════════

def super_admin_only():
    """
    Decorator: Only super admins can use this command.
    
    Super admins are the tournament creators/managers who can:
    - Create and configure tournaments
    - Assign tournament admins
    - Manage tournament lifecycle
    
    Usage:
        @app_commands.command(name="tournament-create")
        @super_admin_only()
        async def tournament_create(self, interaction: discord.Interaction, ...):
            ...
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        if not await is_super_admin(interaction.user.id):
            raise NotSuperAdmin("❌ This command requires Super Admin privileges. Only tournament creators can use this.")
        return True
    return app_commands.check(predicate)


def tournament_admin_only():
    """
    Decorator: Must be admin of the active tournament.
    
    This checks that:
    1. There is an active tournament
    2. The user is assigned as admin for that tournament
    
    Usage:
        @app_commands.command(name="approve-team")
        @tournament_admin_only()
        async def approve_team(self, interaction: discord.Interaction, ...):
            ...
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        tournament = await get_active_tournament()
        if not tournament:
            raise NoActiveTournament("❌ No active tournament. Create and activate one first.")
        
        if not await is_tournament_admin(interaction.user.id, tournament['id']):
            raise NotTournamentAdmin(
                f"❌ You must be an admin of **{tournament['name']}** to use this command."
            )
        return True
    return app_commands.check(predicate)


def require_active_tournament():
    """
    Decorator: Requires an active tournament to exist (no permission check).
    
    This only checks that an active tournament exists, but doesn't verify
    the user's permission level. Use this for public commands that need
    a tournament context.
    
    Usage:
        @app_commands.command(name="teams-list")
        @require_active_tournament()
        async def teams_list(self, interaction: discord.Interaction):
            ...
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        tournament = await get_active_tournament()
        if not tournament:
            raise NoActiveTournament(
                "❌ No active tournament. Wait for an admin to create and activate one."
            )
        return True
    return app_commands.check(predicate)


def tournament_in_registration():
    """
    Decorator: Tournament must be in registration phase.
    
    This checks that:
    1. There is an active tournament
    2. The tournament status is 'registration'
    
    Used for commands like team creation that should only work during registration.
    
    Usage:
        @app_commands.command(name="create-team")
        @tournament_in_registration()
        async def create_team(self, interaction: discord.Interaction, ...):
            ...
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        tournament = await get_active_tournament()
        if not tournament:
            raise NoActiveTournament("❌ No active tournament.")
        if tournament['status'] != 'registration':
            raise TournamentNotInRegistration(
                f"❌ **{tournament['name']}** is not accepting registrations. Current status: {tournament['status'].title()}"
            )
        return True
    return app_commands.check(predicate)


def tournament_active_or_registration():
    """
    Decorator: Tournament must be active or in registration phase.
    
    This checks that:
    1. There is an active tournament
    2. The tournament status is either 'registration' or 'active'
    
    Used for commands that should work during both registration and active phases.
    
    Usage:
        @app_commands.command(name="team-info")
        @tournament_active_or_registration()
        async def team_info(self, interaction: discord.Interaction, ...):
            ...
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        tournament = await get_active_tournament()
        if not tournament:
            raise NoActiveTournament("❌ No active tournament.")
        if tournament['status'] not in ('registration', 'active'):
            raise app_commands.CheckFailure(
                f"❌ This command is not available during the {tournament['status']} phase."
            )
        return True
    return app_commands.check(predicate)


# ═══════════════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════════════

async def get_user_tournament_context(user_id: int, guild: discord.Guild) -> Optional[dict]:
    """
    Determine which tournament a user is operating in (for context-aware operations).
    
    Priority:
    1. If user is admin of active tournament, return active tournament
    2. If user is participant in active tournament, return active tournament
    3. Return None
    
    Args:
        user_id: Discord user ID
        guild: Discord guild
        
    Returns:
        dict: Tournament record or None
    """
    tournament = await get_active_tournament()
    if not tournament:
        return None
    
    # Check if admin
    if await is_tournament_admin(user_id, tournament['id']):
        return tournament
    
    # Check if participant
    if await is_tournament_participant(user_id, tournament['id'], guild):
        return tournament
    
    return None


async def add_super_admin(user_id: int, added_by: Optional[int] = None) -> bool:
    """
    Add a user as a super admin.
    
    Args:
        user_id: Discord user ID to add
        added_by: Discord user ID of the admin who added them (optional)
        
    Returns:
        bool: True if successfully added, False if already exists
    """
    async with connection.pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO super_admins (user_id, added_by) VALUES ($1, $2)",
                user_id, added_by
            )
            log.info(f"Added super admin: {user_id} (by: {added_by})")
            return True
        except Exception as e:
            log.warning(f"Failed to add super admin {user_id}: {e}")
            return False


async def remove_super_admin(user_id: int) -> bool:
    """
    Remove a user from super admins.
    
    Args:
        user_id: Discord user ID to remove
        
    Returns:
        bool: True if successfully removed
    """
    async with connection.pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM super_admins WHERE user_id = $1",
            user_id
        )
        removed = result.split()[-1] != "0"
        if removed:
            log.info(f"Removed super admin: {user_id}")
        return removed


async def add_tournament_admin(tournament_id: int, user_id: int, assigned_by: Optional[int] = None) -> bool:
    """
    Add a user as admin for a specific tournament.
    
    Args:
        tournament_id: Tournament ID
        user_id: Discord user ID to add as admin
        assigned_by: Discord user ID of the super admin who assigned them (optional)
        
    Returns:
        bool: True if successfully added, False if already exists
    """
    async with connection.pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO tournament_admins (tournament_id, user_id, assigned_by) VALUES ($1, $2, $3)",
                tournament_id, user_id, assigned_by
            )
            log.info(f"Added tournament admin: user={user_id}, tournament={tournament_id}, by={assigned_by}")
            return True
        except Exception as e:
            log.warning(f"Failed to add tournament admin {user_id} to tournament {tournament_id}: {e}")
            return False


async def remove_tournament_admin(tournament_id: int, user_id: int) -> bool:
    """
    Remove a user from tournament admins.
    
    Args:
        tournament_id: Tournament ID
        user_id: Discord user ID to remove
        
    Returns:
        bool: True if successfully removed
    """
    async with connection.pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM tournament_admins WHERE tournament_id = $1 AND user_id = $2",
            tournament_id, user_id
        )
        removed = result.split()[-1] != "0"
        if removed:
            log.info(f"Removed tournament admin: user={user_id}, tournament={tournament_id}")
        return removed


async def get_tournament_admins(tournament_id: int) -> list[int]:
    """
    Get all admin user IDs for a tournament.
    
    Args:
        tournament_id: Tournament ID
        
    Returns:
        list[int]: List of Discord user IDs who are admins
    """
    async with connection.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id FROM tournament_admins WHERE tournament_id = $1",
            tournament_id
        )
        return [row['user_id'] for row in rows]
