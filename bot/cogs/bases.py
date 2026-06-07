import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional

import bot.db.connection as connection
from bot.utils.checks import is_admin, is_team_leader_or_admin, is_team_member_or_admin
from bot.utils.embeds import success_embed, error_embed, admin_log_embed
from bot.utils.constants import DISTRICT_NAMES, get_district_from_link
from bot.config import ADMIN_IDS, ADMIN_LOG_CHANNEL_ID

log = logging.getLogger(__name__)


class ConfirmReplaceView(discord.ui.View):
    def __init__(self, cog: 'Bases', match_id: int, team_id: int, district: int, link: str, screenshot_url: str, submitter_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.match_id = match_id
        self.team_id = team_id
        self.district = district
        self.link = link
        self.screenshot_url = screenshot_url
        self.submitter_id = submitter_id

    @discord.ui.button(label="Yes, Replace", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.submitter_id:
            await interaction.response.send_message("Only the original submitter can confirm.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        self.stop()
        await self.cog.save_base(interaction, self.match_id, self.team_id, self.district, self.link, self.screenshot_url, replace=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.submitter_id:
            await interaction.response.send_message("Only the original submitter can cancel.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="Base submission cancelled.", embed=None, view=None)


class Bases(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def match_autocomplete(self, interaction: discord.Interaction, current: str):
        async with connection.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT m.id, t1.name AS t1, t2.name AS t2
                FROM matches m
                JOIN teams t1 ON m.team1_id = t1.id
                JOIN teams t2 ON m.team2_id = t2.id
                WHERE m.status IN ('pending', 'scheduled')
                ORDER BY m.id DESC LIMIT 25
                """
            )
        choices = []
        for r in rows:
            label = f"#{r['id']}: {r['t1']} vs {r['t2']}"
            if current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=r['id']))
        return choices

    async def team_autocomplete(self, interaction: discord.Interaction, current: str):
        async with connection.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name FROM teams WHERE is_approved = TRUE AND LOWER(name) LIKE $1 LIMIT 25",
                f"%{current.lower()}%"
            )
        return [app_commands.Choice(name=r['name'], value=r['name']) for r in rows]

    async def save_base(self, interaction: discord.Interaction, match_id: int, team_id: int, district: int, link: str, screenshot_url: str, replace: bool = False):
        async with connection.pool.acquire() as conn:
            if replace:
                await conn.execute(
                    """UPDATE bases SET link = $1, screenshot_url = $2, submitted_by = $3
                    WHERE team_id = $4 AND match_id = $5 AND district = $6""",
                    link, screenshot_url, interaction.user.id, team_id, match_id, district
                )
            else:
                await conn.execute(
                    """INSERT INTO bases (team_id, match_id, district, link, screenshot_url, submitted_by)
                    VALUES ($1, $2, $3, $4, $5, $6)""",
                    team_id, match_id, district, link, screenshot_url, interaction.user.id
                )

            submitted_count = await conn.fetchval(
                "SELECT COUNT(*) FROM bases WHERE team_id = $1 AND match_id = $2",
                team_id, match_id
            )

        district_name = DISTRICT_NAMES[district]
        action = "replaced" if replace else "submitted"
        await interaction.followup.send(
            embed=success_embed("Base Submitted", f"Base for **{district_name}** has been {action} successfully."),
            ephemeral=True
        )

        if submitted_count == 9 and ADMIN_LOG_CHANNEL_ID:
            guild = interaction.guild
            log_channel = guild.get_channel(ADMIN_LOG_CHANNEL_ID)
            if log_channel:
                async with connection.pool.acquire() as conn:
                    team = await conn.fetchrow("SELECT name FROM teams WHERE id = $1", team_id)
                team_name = team['name'] if team else "Unknown"
                await log_channel.send(
                    embed=admin_log_embed(
                        "All Bases Submitted",
                        f"Team **{team_name}** has submitted all 9 district bases for Match #{match_id}."
                    )
                )

    @app_commands.command(name="submit-base", description="Submit a base for your team (Team Leader only).")
    @app_commands.autocomplete(match_id=match_autocomplete)
    @is_team_leader_or_admin()
    async def submit_base(self, interaction: discord.Interaction, match_id: int, link: str, screenshot: discord.Attachment):
        await interaction.response.defer(ephemeral=True)

        if not screenshot.content_type or not screenshot.content_type.startswith("image/"):
            await interaction.followup.send(embed=error_embed("Invalid File", "Screenshot must be an image file."), ephemeral=True)
            return
        link = link.strip().strip("<>")
        district = get_district_from_link(link)
        if district is None:
            await interaction.followup.send(
                    embed=error_embed("Invalid Link", "Could not detect a district from that link. Please check the link and submit again."),
                    ephemeral=True
            )
            return

        async with connection.pool.acquire() as conn:
            match = await conn.fetchrow("SELECT * FROM matches WHERE id = $1", match_id)
            if not match:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match_id} does not exist."), ephemeral=True)
                return

            if match['status'] not in ('pending', 'scheduled'):
                await interaction.followup.send(embed=error_embed("Not Allowed", "Bases can only be submitted for matches that are pending or scheduled."), ephemeral=True)
                return

            team_record = await conn.fetchrow(
                """SELECT t.id FROM teams t
                JOIN team_members tm ON t.id = tm.team_id
                WHERE tm.user_id = $1 AND tm.role IN ('leader', 'sudo')
                AND t.id IN ($2, $3)""",
                interaction.user.id, match['team1_id'], match['team2_id']
            )
            if not team_record:
                await interaction.followup.send(
                    embed=error_embed("Not Eligible", "You are not a leader of any team in this match."),
                    ephemeral=True
                )
                return
            team_id = team_record['id']

            existing = await conn.fetchrow(
                "SELECT id FROM bases WHERE team_id = $1 AND match_id = $2 AND district = $3",
                team_id, match_id, district
            )

        district_name = DISTRICT_NAMES[district]

        if existing:
            view = ConfirmReplaceView(self, match_id, team_id, district, link, screenshot.url, interaction.user.id)
            await interaction.followup.send(
                embed=error_embed(
                    "Base Already Submitted",
                    f"A base for **{district_name}** is already submitted. Do you want to replace it?"
                ),
                view=view,
                ephemeral=True
            )
        else:
            await self.save_base(interaction, match_id, team_id, district, link, screenshot.url)

    @app_commands.command(name="view-bases", description="View submitted bases for a match (only you can see this).")
    @app_commands.autocomplete(match_id=match_autocomplete, team=team_autocomplete)
    @is_team_member_or_admin()
    async def view_bases(self, interaction: discord.Interaction, match_id: int, team: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        is_admin_user = interaction.user.id in ADMIN_IDS

        async with connection.pool.acquire() as conn:
            match = await conn.fetchrow("SELECT * FROM matches WHERE id = $1", match_id)
            if not match:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match_id} does not exist."))
                return

            if is_admin_user:
                # Admins can specify any team, 
                if team:
                    team_record = await conn.fetchrow("SELECT id, name FROM teams WHERE name = $1", team)
                    if not team_record:
                        await interaction.followup.send(embed=error_embed("Not Found", f"Team '{team}' not found."))
                        return
                else:
                    # No team specified — prompt admin to provide one
                    await interaction.followup.send(
                        embed=error_embed("Team Required", "Please specify a team name to view bases as an admin."),
                        ephemeral=True
                    )
                    return
            else:
                # Non-admins: always their own team in this match, ignore `team` param
                team_record = await conn.fetchrow(
                    """SELECT t.id, t.name FROM teams t
                    JOIN team_members tm ON t.id = tm.team_id
                    WHERE tm.user_id = $1 AND t.id IN ($2, $3)""",
                    interaction.user.id, match['team1_id'], match['team2_id']
                )
                if not team_record:
                    await interaction.followup.send(embed=error_embed("Not Eligible", "HEHE! You cannot cheat"))
                    return

            bases = await conn.fetch(
                "SELECT district, link, screenshot_url FROM bases WHERE team_id = $1 AND match_id = $2 ORDER BY district",
                team_record['id'], match_id
            )

        if not bases:
            await interaction.followup.send(embed=error_embed("No Bases", f"No bases submitted for **{team_record['name']}** in Match #{match_id}."), ephemeral=True)
            return

        for b in bases:
            embed = discord.Embed(
                title=f"{team_record['name']} — {DISTRICT_NAMES[b['district']]}",
                description=f"[Base Link](<{b['link']}>)",
                color=discord.Color.gold() if is_admin_user else discord.Color.blue()
            )
            embed.set_image(url=b['screenshot_url'])
            embed.set_footer(text="AI-3 tournament")
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        return

    @app_commands.command(name="send-bases", description="Publicly post a team's base screenshots for a match (Admin only).")
    @app_commands.autocomplete(match_id=match_autocomplete, team=team_autocomplete)
    @is_admin()
    async def send_bases(self, interaction: discord.Interaction, match_id: int, team: str):
        await interaction.response.defer()

        async with connection.pool.acquire() as conn:
            match = await conn.fetchrow("SELECT * FROM matches WHERE id = $1", match_id)
            if not match:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match_id} does not exist."))
                return

            team_record = await conn.fetchrow("SELECT id, name FROM teams WHERE name = $1", team)
            if not team_record:
                await interaction.followup.send(embed=error_embed("Not Found", f"Team '{team}' not found."))
                return

            if team_record['id'] not in (match['team1_id'], match['team2_id']):
                await interaction.followup.send(embed=error_embed("Not Eligible", f"Team **{team}** is not part of Match #{match_id}."))
                return

            bases = await conn.fetch(
                "SELECT district, screenshot_url FROM bases WHERE team_id = $1 AND match_id = $2 ORDER BY district",
                team_record['id'], match_id
            )

        if not bases:
            await interaction.followup.send(embed=error_embed("No Bases", f"No bases submitted for **{team_record['name']}** in Match #{match_id}."))
            return

        summary_embed = discord.Embed(
            title=f"🗺️ {team_record['name']} — Base Screenshots (Match #{match_id})",
            description="Here are the submitted base screenshots:",
            color=discord.Color.orange()
        )
        summary_embed.set_footer(text="AI-3 tournament")
        await interaction.followup.send(embed=summary_embed)

        for b in bases:
            embed = discord.Embed(
                title=DISTRICT_NAMES[b['district']],
                description=f"[View Base]({b['screenshot_url']})",
                color=discord.Color.blue()
            )
            embed.set_image(url=b['screenshot_url'])
            embed.set_footer(text="AI-3 tournament")
            await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Bases(bot))