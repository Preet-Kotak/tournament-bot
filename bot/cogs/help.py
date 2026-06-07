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
                title="Command Reference — Admin",
                color=discord.Color.red()
            )

            embed.add_field(
                name="Team Management",
                value=(
                    "`/create-team` — Register a new team with 3–5 members\n"
                    "`/approve-team` — Approve a team and create their private channel\n"
                    "`/announce-team` — Post a team announcement (requires logo)\n"
                    "`/edit-team` — Change a team's name or full roster\n"
                    "`/delete-team` — Delete a team and remove their role\n"
                    "`/set-coleader` — Give a team member co-leader permissions\n"
                    "`/add-logo` — Upload a logo for a team *(leader can also use)*"
                ),
                inline=False
            )

            embed.add_field(
                name="📅 Match Management",
                value=(
                    "`/set-match` — Create a new match between two teams\n"
                    "`/schedule-match` — Set the match time and mark it as scheduled\n"
                    "`/start-match` — Start a match and post the live embed\n"
                    "`/end-match` — End an active match\n"
                    "`/delete-match` — Delete a match completely\n"
                ),
                inline=False
            )

            embed.add_field(
                name="🏚️ Bases",
                value=(
                    "`/view-bases` — View any team's submitted bases for a match\n"
                    "`/view-bases` — View your own team's submitted bases for a match(this is for players)\n"
                    "`/send-bases` — Publicly post a team's base screenshots in channel\n"
                    "`/submit-base` — Submit a district base for your team *(leader only)*\n"
                ),
                inline=False
            )

            embed.add_field(
                name="🌐 Everyone",
                value=(
                    "`/matches` — View all upcoming matches\n"
                    "`/help` — Show this message"
                ),
                inline=False
            )

        elif is_participant:
            embed = discord.Embed(
                title="Command Reference — Participant",
                color=discord.Color.green()
            )

            embed.add_field(
                name="👥 Your Team",
                value=(
                    "`/add-logo` — Upload a logo for your team *(leader & co-leader only)*\n"
                ),
                inline=False
            )

            embed.add_field(
                name="🏚️ Bases",
                value=(
                    "`/submit-base` — Submit a district base for your team *(leader only)*\n"
                    "`/view-bases` — View your own team's submitted bases for a match"
                ),
                inline=False
            )

            embed.add_field(
                name="🌐 Everyone",
                value=(
                    "`/matches` — View all upcoming matches\n"
                    "`/help` — Show this message"
                ),
                inline=False
            )

        else:
            embed = discord.Embed(
                title="Command Reference",
                color=discord.Color.blurple()
            )

            embed.add_field(
                name="🌐 Available Commands",
                value=(
                    "`/matches` — View all upcoming matches\n"
                    "`/help` — Show this message"
                ),
                inline=False
            )

        embed.set_footer(text="AI-3 tournament • Anshu's Invitational 3")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))