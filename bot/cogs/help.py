import discord
from discord.ext import commands
from discord import app_commands

from bot.config import ADMIN_IDS, PARTICIPANT_ROLE_ID
from bot.utils.embeds import (
    get_overview_embed,
    get_team_management_embed,
    get_match_management_embed,
    get_base_management_embed,
    get_attack_management_embed,
    get_statistics_embed,
    get_qualifier_embed,
    get_utility_embed,
    get_general_commands_embed,
    get_match_commands_embed,
)


# ── Category Select View ──────────────────────────────────────────────────────

class HelpCategorySelect(discord.ui.Select):
    def __init__(self, is_admin: bool, is_participant: bool):
        self.is_admin = is_admin
        self.is_participant = is_participant
        
        # Build options based on user role
        options = []
        
        if is_admin:
            options = [
                discord.SelectOption(label="Overview", description="See all available categories", emoji="📚", value="overview"),
                discord.SelectOption(label="Team Management", description="Create, edit, and manage teams", emoji="👥", value="team"),
                discord.SelectOption(label="Match Management", description="Set up and control matches", emoji="⚔️", value="match"),
                discord.SelectOption(label="Base Management", description="Submit and view bases", emoji="🗺️", value="base"),
                discord.SelectOption(label="Attack Management", description="Log and edit attacks", emoji="⚔️", value="attack"),
                discord.SelectOption(label="Statistics", description="View stats and leaderboards", emoji="📊", value="stats"),
                discord.SelectOption(label="Qualifier", description="Qualifier round commands", emoji="🎯", value="qualifier"),
                discord.SelectOption(label="Utility", description="Misc utility commands", emoji="🔧", value="utility"),
            ]
        elif is_participant:
            options = [
                discord.SelectOption(label="Overview", description="See all available categories", emoji="📚", value="overview"),
                discord.SelectOption(label="Team Commands", description="Manage your team", emoji="👥", value="team"),
                discord.SelectOption(label="Base Commands", description="Submit and view bases", emoji="🗺️", value="base"),
                discord.SelectOption(label="General Commands", description="General tournament commands", emoji="🌐", value="general"),
                discord.SelectOption(label="Statistics", description="View stats and leaderboards", emoji="📊", value="stats"),
                discord.SelectOption(label="Qualifier", description="Qualifier round commands", emoji="🎯", value="qualifier"),
            ]
        else:
            options = [
                discord.SelectOption(label="Overview", description="See all available categories", emoji="📚", value="overview"),
                discord.SelectOption(label="Team Commands", description="Create and view teams", emoji="👥", value="team"),
                discord.SelectOption(label="Match Commands", description="View matches", emoji="📅", value="match_public"),
                discord.SelectOption(label="Statistics", description="View stats and leaderboards", emoji="📊", value="stats"),
                discord.SelectOption(label="Qualifier", description="Qualifier round commands", emoji="🎯", value="qualifier"),
                discord.SelectOption(label="Utility", description="Misc utility commands", emoji="🌐", value="utility"),
            ]
        
        super().__init__(
            placeholder="Select a command category...",
            options=options,
            min_values=1,
            max_values=1,
        )
    
    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        
        # Generate appropriate embed based on selection
        if selected == "overview":
            embed = get_overview_embed(self.is_admin, self.is_participant)
        elif selected == "team":
            embed = get_team_management_embed(self.is_admin)
        elif selected == "match":
            embed = get_match_management_embed()
        elif selected == "match_public":
            embed = get_match_commands_embed()
        elif selected == "base":
            embed = get_base_management_embed(self.is_admin)
        elif selected == "attack":
            embed = get_attack_management_embed()
        elif selected == "stats":
            embed = get_statistics_embed()
        elif selected == "qualifier":
            embed = get_qualifier_embed(self.is_admin)
        elif selected == "utility":
            embed = get_utility_embed(self.is_admin)
        elif selected == "general":
            embed = get_general_commands_embed()
        else:
            embed = get_overview_embed(self.is_admin, self.is_participant)
        
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, is_admin: bool, is_participant: bool):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.add_item(HelpCategorySelect(is_admin, is_participant))
    
    async def on_timeout(self):
        # Disable the dropdown when the view times out
        for item in self.children:
            item.disabled = True


# ── Help Cog ──────────────────────────────────────────────────────────────────

class Help(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all available commands.")
    async def help(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        user = interaction.user
        is_admin = user.id in ADMIN_IDS
        is_participant = any(r.id == PARTICIPANT_ROLE_ID for r in getattr(user, "roles", []))

        # Show overview embed with category selector
        embed = get_overview_embed(is_admin, is_participant)
        view = HelpView(is_admin, is_participant)
        
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
