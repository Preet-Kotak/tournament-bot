import discord
from discord import app_commands
from bot.config import ADMIN_IDS
import bot.db.connection as connection

def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id in ADMIN_IDS:
            return True
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_team_leader_or_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id in ADMIN_IDS:
            return True
            
        # Check database if user is leader or sudo
        async with connection.pool.acquire() as conn:
            record = await conn.fetchrow(
                "SELECT role FROM team_members WHERE user_id = $1 AND role IN ('leader', 'sudo')",
                interaction.user.id
            )
            if record:
                return True
                
        await interaction.response.send_message("You must be a team leader to use this command.", ephemeral=True)
        return False
    return app_commands.check(predicate)
