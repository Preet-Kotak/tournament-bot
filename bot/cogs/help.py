import discord
from discord.ext import commands
from discord import app_commands

from bot.config import ADMIN_IDS, PARTICIPANT_ROLE_ID
from bot.utils.embeds import help_admin_embed, help_participant_embed, help_public_embed


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all available commands.")
    async def help(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        user = interaction.user
        is_admin = user.id in ADMIN_IDS
        is_participant = any(r.id == PARTICIPANT_ROLE_ID for r in getattr(user, "roles", []))

        if is_admin:
            embed = help_admin_embed()
        elif is_participant:
            embed = help_participant_embed()
        else:
            embed = help_public_embed()

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
