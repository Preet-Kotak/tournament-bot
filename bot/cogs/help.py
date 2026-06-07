import discord
from discord.ext import commands
from discord import app_commands

from bot.config import ADMIN_IDS, PARTICIPANT_ROLE_ID


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
            embed = discord.Embed(
                title="🔧 Command Reference — Admin",
                description="Full access to all tournament commands",
                color=discord.Color.red()
            )

            embed.add_field(
                name="👥 Team Management",
                value=(
                    "`/create-team` — Register a new team with 3–5 members\n"
                    "`/approve-team` — Approve a team and create their private channel\n"
                    "`/announce-team` — Post a team announcement (requires logo)\n"
                    "`/edit-team` — Change a team's name or full roster\n"
                    "`/delete-team` — Delete a team and remove their role\n"
                    "`/set-coleader` — Give a team member co-leader permissions\n"
                    "`/teams-list` — View all approved teams\n"
                    "`/team-info` — View detailed information about a team"
                ),
                inline=False
            )

            embed.add_field(
                name="📅 Match Management",
                value=(
                    "`/set-match` — Create a new match between two teams\n"
                    "`/schedule-match` — Set the match time and mark as scheduled\n"
                    "`/start-match` — Start a match and post the live embed\n"
                    "`/end-match` — End a match and move to archive\n"
                    "`/delete-match` — Delete a match completely\n"
                    "`/matches` — View all upcoming matches"
                ),
                inline=False
            )

            embed.add_field(
                name="🗺️ Base Management",
                value=(
                    "`/view-bases` — View any team's submitted bases (specify team)\n"
                    "`/send-bases` — Publicly post a team's base screenshots\n"
                    "`/base-status` — Check base submission status for a match\n"
                    "`/remind-bases` — Ping a team about missing bases"
                ),
                inline=False
            )

            embed.add_field(
                name="🌐 Utility",
                value=(
                    "`/help` — Show this command reference\n"
                    "`/clear-data` — Wipe all match data (testing only)"
                ),
                inline=False
            )

        elif is_participant:
            embed = discord.Embed(
                title="⚔️ Command Reference — Participant",
                description="Commands available to tournament participants",
                color=discord.Color.green()
            )

            embed.add_field(
                name="👥 Team Commands (Leader/Co-Leader Only)",
                value=(
                    "`/add-logo` — Upload a logo for your team\n"
                    "`/submit-base` — Submit a district base for your team"
                ),
                inline=False
            )

            embed.add_field(
                name="🗺️ Base Commands (All Team Members)",
                value=(
                    "`/view-bases` — View your team's submitted bases\n"
                    "`/base-status` — Check which bases your team has submitted"
                ),
                inline=False
            )

            embed.add_field(
                name="🌐 General Commands (Everyone)",
                value=(
                    "`/create-team` — Register a new team (if not on one)\n"
                    "`/teams-list` — View all approved teams\n"
                    "`/team-info` — View detailed information about a team\n"
                    "`/matches` — View all upcoming matches\n"
                    "`/help` — Show this command reference"
                ),
                inline=False
            )

        else:
            embed = discord.Embed(
                title="� Command Reference",
                description="Commands available to everyone",
                color=discord.Color.blurple()
            )

            embed.add_field(
                name="� Team Commands",
                value=(
                    "`/create-team` — Register a new team with 3–5 members\n"
                    "`/teams-list` — View all approved teams\n"
                    "`/team-info` — View detailed information about a team"
                ),
                inline=False
            )

            embed.add_field(
                name="📅 Match Commands",
                value=(
                    "`/matches` — View all upcoming matches"
                ),
                inline=False
            )

            embed.add_field(
                name="🌐 Utility",
                value=(
                    "`/help` — Show this command reference"
                ),
                inline=False
            )

        embed.set_footer(text="AI-3 Tournament • Anshu's Invitational 3")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
