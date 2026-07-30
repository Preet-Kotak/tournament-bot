import discord
from discord.ext import commands
from discord import app_commands
import logging
import io
from typing import Optional

import aiohttp
import bot.db.connection as connection
from bot.utils.checks import is_admin, is_team_leader_or_admin, is_team_member_or_admin
from bot.utils.embeds import (
    success_embed, error_embed, admin_log_embed,
    base_card_embed, base_status_embed,
    send_bases_summary_embed, send_bases_card_embed,
    remind_bases_embed,
)
from bot.utils.constants import DISTRICT_NAMES, get_district_from_link
from bot.utils.autocomplete import team_autocomplete, pending_or_scheduled_match_autocomplete
from bot.utils.cloudinary_utils import init_cloudinary, upload_to_cloudinary
from bot.config import ADMIN_IDS, ADMIN_LOG_CHANNEL_ID, LOGO_STORAGE_CHANNEL_ID

log = logging.getLogger(__name__)


class ConfirmReplaceView(discord.ui.View):
    def __init__(self, cog: "Bases", match_id: int, team_id: int, district: int, link: str, screenshot_url: str, submitter_id: int):
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
        self.cloudinary_enabled = init_cloudinary()
        if self.cloudinary_enabled:
            log.info("Cloudinary integration enabled for base screenshots")
        else:
            log.info("Cloudinary not configured - using Discord storage channel fallback")

    async def _permanent_screenshot_url(self, guild: discord.Guild, attachment: discord.Attachment) -> str:
        """Upload screenshot to Cloudinary for permanent storage. Falls back to Discord storage if Cloudinary fails."""
        
        # Try Cloudinary first if configured
        if self.cloudinary_enabled:
            cloudinary_url = await upload_to_cloudinary(attachment.url, folder="tournament_bases")
            if cloudinary_url:
                log.info(f"Successfully uploaded screenshot to Cloudinary")
                return cloudinary_url
            else:
                log.warning("Cloudinary upload failed, falling back to Discord storage")
        
        # Fallback to Discord storage channel if Cloudinary not available or failed
        if not LOGO_STORAGE_CHANNEL_ID:
            log.warning("No storage channel configured, using original attachment URL")
            return attachment.url
            
        storage_channel = guild.get_channel(LOGO_STORAGE_CHANNEL_ID)
        if not storage_channel:
            log.warning("Storage channel not found, using original attachment URL")
            return attachment.url
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(attachment.url) as resp:
                    if resp.status != 200:
                        return attachment.url
                    image_bytes = await resp.read()
            ext = attachment.filename.rsplit(".", 1)[-1] if "." in attachment.filename else "png"
            filename = f"base_screenshot.{ext}"
            stored_msg = await storage_channel.send(
                file=discord.File(io.BytesIO(image_bytes), filename=filename)
            )
            log.info("Uploaded screenshot to Discord storage channel (fallback)")
            return stored_msg.attachments[0].url
        except Exception as e:
            log.warning(f"Failed to store base screenshot in storage channel: {e}")
            return attachment.url

    async def _render_all_bases_status(self) -> Optional[io.BytesIO]:
        """Render an image showing base submission status for all pending/scheduled matches."""
        from PIL import Image, ImageDraw
        from pathlib import Path
        from bot.cogs.matches import _load_font

        async with connection.pool.acquire() as conn:
            matches = await conn.fetch(
                """SELECT m.id, m.team1_id, m.team2_id,
                          t1.name AS team1_name, t2.name AS team2_name
                   FROM matches m
                   JOIN teams t1 ON m.team1_id = t1.id
                   JOIN teams t2 ON m.team2_id = t2.id
                   WHERE m.status IN ('pending', 'scheduled')
                   ORDER BY m.id"""
            )

            if not matches:
                return None

            # Collect all teams and their base status
            teams_data = []
            for match in matches:
                for team_id, team_name in [(match["team1_id"], match["team1_name"]), (match["team2_id"], match["team2_name"])]:
                    submitted = await conn.fetch(
                        "SELECT district FROM bases WHERE team_id = $1 AND match_id = $2",
                        team_id, match["id"]
                    )
                    submitted_districts = {row["district"] for row in submitted}
                    teams_data.append({
                        "match_id": match["id"],
                        "match_label": f"Match #{match['id']}: {match['team1_name']} vs {match['team2_name']}",
                        "team_name": team_name,
                        "submitted": submitted_districts
                    })

        # Image dimensions
        title_h = 60
        header_h = 50
        row_h = 40
        team_col_w = 400
        district_col_w = 70
        padding = 20
        
        width = padding * 2 + team_col_w + (district_col_w * 9)
        height = padding * 2 + title_h + header_h + (row_h * len(teams_data))

        # Create image
        image = Image.new("RGB", (width, height), "#ffffff")
        draw = ImageDraw.Draw(image)

        title_font = _load_font(28, bold=True)
        header_font = _load_font(18, bold=True)
        row_font = _load_font(16, bold=False)
        emoji_font = _load_font(28, bold=False)

        # Draw title
        title = "Base Submission Status - All Matches"
        draw.text((padding, padding), title, font=title_font, fill="#1e40af")

        # Draw header row
        y = padding + title_h
        draw.rectangle((padding, y, width - padding, y + header_h), fill="#dbeafe")
        draw.text((padding + 10, y + 15), "Team", font=header_font, fill="#1e293b")
        
        for i in range(9):
            x = padding + team_col_w + (i * district_col_w)
            district_abbr = DISTRICT_NAMES[i].split()[0][:3]  # "Builder" -> "Bui"
            bbox = draw.textbbox((0, 0), district_abbr, font=header_font)
            text_w = bbox[2] - bbox[0]
            draw.text((x + (district_col_w - text_w) // 2, y + 15), district_abbr, font=header_font, fill="#1e293b")

        # Draw rows
        y += header_h
        current_match_id = None
        
        for idx, team in enumerate(teams_data):
            # Add separator between matches
            if current_match_id is not None and current_match_id != team["match_id"]:
                draw.line((padding, y, width - padding, y), fill="#93c5fd", width=2)
            current_match_id = team["match_id"]
            
            # Alternate row colors
            fill = "#f8fafc" if idx % 2 == 0 else "#ffffff"
            draw.rectangle((padding, y, width - padding, y + row_h), fill=fill)
            
            # Draw team name
            team_text = f"{team['team_name'][:35]}"
            draw.text((padding + 10, y + 12), team_text, font=row_font, fill="#1e293b")
            
            # Draw status for each district
            for i in range(9):
                x = padding + team_col_w + (i * district_col_w)
                symbol = "●" if i in team["submitted"] else "○"
                color = "#16a34a" if i in team["submitted"] else "#dc2626"
                
                bbox = draw.textbbox((0, 0), symbol, font=emoji_font)
                text_w = bbox[2] - bbox[0]
                draw.text((x + (district_col_w - text_w) // 2, y + 6), symbol, font=emoji_font, fill=color)
            
            y += row_h

        # Convert to BytesIO
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    async def save_base(
        self,
        interaction: discord.Interaction,
        match_id: int,
        team_id: int,
        district: int,
        link: str,
        screenshot_url: str,
        replace: bool = False,
    ):
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
            log_channel = interaction.guild.get_channel(ADMIN_LOG_CHANNEL_ID)
            if log_channel:
                async with connection.pool.acquire() as conn:
                    team = await conn.fetchrow("SELECT name FROM teams WHERE id = $1", team_id)
                team_name = team["name"] if team else "Unknown"
                await log_channel.send(
                    embed=admin_log_embed(
                        "All Bases Submitted",
                        f"Team **{team_name}** has submitted all 9 district bases for Match #{match_id}."
                    )
                )

    # ── Commands ──────────────────────────────────────────────────────────────

    @app_commands.command(name="submit-base", description="Submit a base for your team (Team Leader only).")
    @app_commands.describe(
        match_id="The match ID to submit the base for",
        link="The base link (district will be auto-detected)",
        screenshot="Screenshot of your base",
        team="(Admin only) Select a specific team to submit for"
    )
    @app_commands.autocomplete(match_id=pending_or_scheduled_match_autocomplete, team=team_autocomplete)
    @is_team_leader_or_admin()
    async def submit_base(self, interaction: discord.Interaction, match_id: int, link: str, screenshot: discord.Attachment, team: Optional[str] = None):
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

        # Re-upload screenshot to storage channel for a permanent URL
        screenshot_url = await self._permanent_screenshot_url(interaction.guild, screenshot)

        is_admin_user = interaction.user.id in ADMIN_IDS

        async with connection.pool.acquire() as conn:
            match = await conn.fetchrow("SELECT * FROM matches WHERE id = $1", match_id)
            if not match:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match_id} does not exist."), ephemeral=True)
                return

            if match["status"] not in ("pending", "scheduled"):
                await interaction.followup.send(
                    embed=error_embed("Not Allowed", "Bases can only be submitted for matches that are pending or scheduled."),
                    ephemeral=True
                )
                return

            # Admin can specify team, otherwise find user's team
            if is_admin_user and team:
                team_record = await conn.fetchrow("SELECT id FROM teams WHERE name = $1", team)
                if not team_record:
                    await interaction.followup.send(embed=error_embed("Not Found", f"Team '{team}' not found."), ephemeral=True)
                    return
                if team_record["id"] not in (match["team1_id"], match["team2_id"]):
                    await interaction.followup.send(
                        embed=error_embed("Not Eligible", f"Team **{team}** is not part of Match #{match_id}."),
                        ephemeral=True
                    )
                    return
            else:
                team_record = await conn.fetchrow(
                    """SELECT t.id FROM teams t
                    JOIN team_members tm ON t.id = tm.team_id
                    WHERE tm.user_id = $1 AND tm.role IN ('leader', 'sudo')
                    AND t.id IN ($2, $3)""",
                    interaction.user.id, match["team1_id"], match["team2_id"]
                )
                if not team_record:
                    await interaction.followup.send(
                        embed=error_embed("Not Eligible", "You are not a leader of any team in this match."),
                        ephemeral=True
                    )
                    return
            team_id = team_record["id"]

            existing = await conn.fetchrow(
                "SELECT id FROM bases WHERE team_id = $1 AND match_id = $2 AND district = $3",
                team_id, match_id, district
            )

        district_name = DISTRICT_NAMES[district]

        if existing:
            view = ConfirmReplaceView(self, match_id, team_id, district, link, screenshot_url, interaction.user.id)
            await interaction.followup.send(
                embed=error_embed(
                    "Base Already Submitted",
                    f"A base for **{district_name}** is already submitted. Do you want to replace it?"
                ),
                view=view,
                ephemeral=True
            )
        else:
            await self.save_base(interaction, match_id, team_id, district, link, screenshot_url)

    @app_commands.command(name="view-bases", description="View submitted bases for a match (only you can see this).")
    @app_commands.describe(
        match_id="The match ID to view bases for",
        team="(Admin only) The team name to view bases for",
    )
    @app_commands.autocomplete(match_id=pending_or_scheduled_match_autocomplete, team=team_autocomplete)
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
                if team:
                    team_record = await conn.fetchrow("SELECT id, name FROM teams WHERE name = $1", team)
                    if not team_record:
                        await interaction.followup.send(embed=error_embed("Not Found", f"Team '{team}' not found."))
                        return
                else:
                    await interaction.followup.send(
                        embed=error_embed("Team Required", "Please specify a team name to view bases as an admin."),
                        ephemeral=True
                    )
                    return
            else:
                team_record = await conn.fetchrow(
                    """SELECT t.id, t.name FROM teams t
                    JOIN team_members tm ON t.id = tm.team_id
                    WHERE tm.user_id = $1 AND t.id IN ($2, $3)""",
                    interaction.user.id, match["team1_id"], match["team2_id"]
                )
                if not team_record:
                    await interaction.followup.send(embed=error_embed("Not Eligible", "HEHE! You cannot cheat"))
                    return

            bases = await conn.fetch(
                "SELECT district, link, screenshot_url FROM bases WHERE team_id = $1 AND match_id = $2 ORDER BY district",
                team_record["id"], match_id
            )

        if not bases:
            await interaction.followup.send(
                embed=error_embed("No Bases", f"No bases submitted for **{team_record['name']}** in Match #{match_id}."),
                ephemeral=True
            )
            return

        for b in bases:
            await interaction.followup.send(
                embed=base_card_embed(
                    team_record['name'], DISTRICT_NAMES[b['district']],
                    b['link'], b['screenshot_url'], is_admin=is_admin_user
                ),
                ephemeral=True,
            )

    @app_commands.command(name="base-status", description="Check which bases your team has submitted for a match.")
    @app_commands.autocomplete(match_id=pending_or_scheduled_match_autocomplete)
    @is_team_member_or_admin()
    async def base_status(self, interaction: discord.Interaction, match_id: Optional[int] = None):
        await interaction.response.defer(ephemeral=True)

        is_admin_user = interaction.user.id in ADMIN_IDS

        # Admin: always show all pending/scheduled matches (ignore match_id)
        if is_admin_user:
            image = await self._render_all_bases_status()
            if image:
                file = discord.File(image, filename="all_bases_status.png")
                await interaction.followup.send(file=file, ephemeral=True)
            else:
                await interaction.followup.send(
                    embed=error_embed("No Matches", "No pending or scheduled matches found."),
                    ephemeral=True
                )
            return

        # Regular user without match_id
        if match_id is None:
            await interaction.followup.send(
                embed=error_embed("Match Required", "Please specify a match ID."),
                ephemeral=True
            )
            return

        async with connection.pool.acquire() as conn:
            match = await conn.fetchrow("SELECT * FROM matches WHERE id = $1", match_id)
            if not match:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match_id} does not exist."))
                return

            team_record = await conn.fetchrow(
                """SELECT t.id, t.name FROM teams t
                JOIN team_members tm ON t.id = tm.team_id
                WHERE tm.user_id = $1 AND t.id IN ($2, $3)""",
                interaction.user.id, match["team1_id"], match["team2_id"]
            )
            if not team_record:
                await interaction.followup.send(embed=error_embed("Not Eligible", "You are not a member of either team in this match."))
                return

            submitted = await conn.fetch(
                "SELECT district FROM bases WHERE team_id = $1 AND match_id = $2 ORDER BY district",
                team_record["id"], match_id
            )

        submitted_districts = {row["district"] for row in submitted}
        status_lines = [
            f"{'✅' if d in submitted_districts else '❌'} {DISTRICT_NAMES[d]}"
            for d in range(9)
        ]
        count = len(submitted_districts)
        await interaction.followup.send(
            embed=base_status_embed(team_record['name'], match_id, status_lines, count),
            ephemeral=True,
        )

    @app_commands.command(name="send-bases", description="Publicly post a team's base screenshots for a match (Admin only).")
    @app_commands.autocomplete(match_id=pending_or_scheduled_match_autocomplete, team=team_autocomplete)
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

            if team_record["id"] not in (match["team1_id"], match["team2_id"]):
                await interaction.followup.send(embed=error_embed("Not Eligible", f"Team **{team}** is not part of Match #{match_id}."))
                return

            # Get both team names for the header
            team1 = await conn.fetchrow("SELECT name FROM teams WHERE id = $1", match["team1_id"])
            team2 = await conn.fetchrow("SELECT name FROM teams WHERE id = $1", match["team2_id"])
            
            bases = await conn.fetch(
                "SELECT district, screenshot_url FROM bases WHERE team_id = $1 AND match_id = $2 ORDER BY district",
                team_record["id"], match_id
            )

        if not bases:
            await interaction.followup.send(embed=error_embed("No Bases", f"No bases submitted for **{team_record['name']}** in Match #{match_id}."))
            return

        # Get storage channel (for Discord storage fallback)
        storage_channel = interaction.guild.get_channel(LOGO_STORAGE_CHANNEL_ID) if LOGO_STORAGE_CHANNEL_ID else None

        # Download all screenshots and prepare them as discord.File objects
        files = []
        buffers = []  # Keep references to BytesIO objects
        failed_districts = []
        
        for b in bases:
            try:
                screenshot_url = b["screenshot_url"]
                district_num = b["district"]
                
                # Cloudinary URLs don't expire, use directly
                is_cloudinary = "cloudinary.com" in screenshot_url
                
                # For old Discord storage URLs, try to refresh from channel
                if not is_cloudinary and storage_channel and f"attachments/{LOGO_STORAGE_CHANNEL_ID}/" in screenshot_url:
                    parts = screenshot_url.split("/")
                    if len(parts) >= 3:
                        try:
                            message_id = int(parts[-2])
                            storage_message = await storage_channel.fetch_message(message_id)
                            if storage_message.attachments:
                                screenshot_url = storage_message.attachments[0].url
                                log.info(f"Refreshed Discord storage URL for district {district_num}")
                        except discord.NotFound:
                            log.warning(f"Storage message not found for district {district_num}")
                        except (ValueError, discord.HTTPException) as e:
                            log.warning(f"Could not refresh storage URL for district {district_num}: {e}")
                
                # Download the screenshot
                async with aiohttp.ClientSession() as session:
                    async with session.get(screenshot_url) as resp:
                        if resp.status == 200:
                            image_bytes = await resp.read()
                            district_name = DISTRICT_NAMES[district_num].replace(" ", "_")
                            filename = f"{district_name}.png"
                            buffer = io.BytesIO(image_bytes)
                            buffers.append(buffer)  # Keep reference to prevent garbage collection
                            files.append(discord.File(buffer, filename=filename))
                            log.info(f"Downloaded screenshot for district {district_num} ({len(image_bytes)} bytes)")
                        else:
                            log.warning(f"Failed to download district {district_num}: HTTP {resp.status}")
                            failed_districts.append(district_num)
            except Exception as e:
                log.error(f"Error processing district {district_num}: {e}")
                failed_districts.append(district_num)

        if not files:
            await interaction.followup.send(
                embed=error_embed(
                    "Error", 
                    "Failed to download any base screenshots. The stored images may have expired or been deleted. "
                    "Please ask team leaders to re-submit bases."
                )
            )
            return

        # Send a single message with all images
        message_text = f"**{team1['name']} vs {team2['name']}\n{team_record['name']} Bases**"
        
        if failed_districts:
            district_names = [DISTRICT_NAMES[d] for d in failed_districts]
            message_text += f"\n⚠️ Some bases could not be loaded: {', '.join(district_names)}"
        
        await interaction.followup.send(content=message_text, files=files)
        log.info(f"Sent {len(files)}/9 bases for team {team_record['name']} in match #{match_id}")
        await interaction.followup.send(content=message_text, files=files)

    @app_commands.command(name="remind-bases", description="Check all pending/scheduled matches and remind teams with missing bases (Admin only).")
    @is_admin()
    async def remind_bases(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        async with connection.pool.acquire() as conn:
            # Get all matches that are pending or scheduled (not completed)
            matches = await conn.fetch(
                """SELECT m.id, m.team1_id, m.team2_id, 
                          t1.name AS team1_name, t2.name AS team2_name
                   FROM matches m
                   JOIN teams t1 ON m.team1_id = t1.id
                   JOIN teams t2 ON m.team2_id = t2.id
                   WHERE m.status IN ('pending', 'scheduled')
                   ORDER BY m.id"""
            )

            if not matches:
                await interaction.followup.send(embed=error_embed("No Matches", "No pending or scheduled matches found."))
                return

            reminders_sent = []
            all_complete = []

            for match in matches:
                match_id = match["id"]
                match_label = f"Match #{match_id} ({match['team1_name']} vs {match['team2_name']})"
                
                # Check both teams for this match
                for team_id in [match["team1_id"], match["team2_id"]]:
                    team_record = await conn.fetchrow(
                        "SELECT id, name, team_role_id, channel_id FROM teams WHERE id = $1",
                        team_id
                    )
                    
                    if not team_record:
                        continue

                    submitted = await conn.fetch(
                        "SELECT district FROM bases WHERE team_id = $1 AND match_id = $2",
                        team_id, match_id
                    )

                    submitted_districts = {row["district"] for row in submitted}
                    missing = [d for d in range(9) if d not in submitted_districts]

                    if not missing:
                        all_complete.append(f"{match_label}: **{team_record['name']}** ✅")
                        continue

                    # Team has missing bases, send reminder
                    missing_lines = [f"❌ {DISTRICT_NAMES[d]}" for d in missing]
                    team_role = interaction.guild.get_role(team_record["team_role_id"])
                    ping = team_role.mention if team_role else team_record["name"]
                    team_channel = interaction.guild.get_channel(team_record["channel_id"]) if team_record["channel_id"] else None

                    if not team_channel:
                        reminders_sent.append(f"{match_label}: **{team_record['name']}** - ⚠️ No team channel")
                        continue

                    try:
                        await team_channel.send(content=ping, embed=remind_bases_embed(match_id, missing_lines))
                        reminders_sent.append(f"{match_label}: **{team_record['name']}** - Reminded about {len(missing)} missing bases in {team_channel.mention}")
                    except Exception as e:
                        log.error(f"Failed to send reminder to {team_record['name']}: {e}")
                        reminders_sent.append(f"{match_label}: **{team_record['name']}** - ❌ Failed to send")

        # Build summary message
        summary_parts = []
        
        if reminders_sent:
            summary_parts.append("**Reminders Sent:**")
            summary_parts.extend(reminders_sent)
        
        if all_complete:
            summary_parts.append("\n**Teams with All Bases Submitted:**")
            summary_parts.extend(all_complete)
        
        if not reminders_sent and not all_complete:
            await interaction.followup.send(embed=error_embed("No Teams", "No teams found in pending/scheduled matches."))
            return

        summary = "\n".join(summary_parts)
        await interaction.followup.send(embed=success_embed("Base Reminders Complete", summary))


async def setup(bot: commands.Bot):
    await bot.add_cog(Bases(bot))
