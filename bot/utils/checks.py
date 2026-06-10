import discord
from discord import app_commands
from bot.config import ADMIN_IDS
import bot.db.connection as connection


class NotAdmin(app_commands.CheckFailure):
    def __init__(self):
        super().__init__("You do not have permission to use this command.")


class NotTeamLeader(app_commands.CheckFailure):
    def __init__(self):
        super().__init__("You must be a team leader or co-leader to use this command.")


class NotTeamMember(app_commands.CheckFailure):
    def __init__(self):
        super().__init__("You must be a team member to use this command.")


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id in ADMIN_IDS:
            return True
        raise NotAdmin()
    return app_commands.check(predicate)


def is_team_leader_or_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id in ADMIN_IDS:
            return True
        async with connection.pool.acquire() as conn:
            record = await conn.fetchrow(
                "SELECT role FROM team_members WHERE user_id = $1 AND role IN ('leader', 'sudo')",
                interaction.user.id
            )
            if record:
                return True
        raise NotTeamLeader()
    return app_commands.check(predicate)


def is_team_member_or_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id in ADMIN_IDS:
            return True
        async with connection.pool.acquire() as conn:
            record = await conn.fetchrow(
                "SELECT role FROM team_members WHERE user_id = $1",
                interaction.user.id
            )
            if record:
                return True
        raise NotTeamMember()
    return app_commands.check(predicate)
