import discord
from discord.ext import commands
import logging

from bot.config import WELCOME_CHANNEL_ID, ANNOUNCEMENT_CHANNEL_ID, SELF_ROLES_CHANNEL_ID

log = logging.getLogger(__name__)


class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not WELCOME_CHANNEL_ID:
            return

        channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
        if not channel:
            log.warning(f"Welcome channel {WELCOME_CHANNEL_ID} not found.")
            return

        announcement_mention = f"<#{ANNOUNCEMENT_CHANNEL_ID}>" if ANNOUNCEMENT_CHANNEL_ID else "#announcements"
        self_roles_mention = f"<#{SELF_ROLES_CHANNEL_ID}>" if SELF_ROLES_CHANNEL_ID else "#self-roles"

        message = (
            f"Hey {member.mention}, welcome to **Anshu's Invitational**! "
            f"Have a look at {announcement_mention} for news about tournaments. "
            f"Grab some self roles in {self_roles_mention}!"
        )

        try:
            await channel.send(message)
        except discord.HTTPException as e:
            log.error(f"Failed to send welcome message: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))
