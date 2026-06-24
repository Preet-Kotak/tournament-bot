import discord
from discord.ext import commands
from discord import app_commands
import logging
import io
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

import bot.db.connection as connection
from bot.utils.checks import is_admin
from bot.utils.embeds import success_embed, error_embed, upcoming_matches_embed
from bot.utils.discord_utils import get_username
from bot.utils.timezones import local_time_label, timezone_offset_to_minutes, utc_label
from bot.utils.constants import DISTRICT_NAMES
from bot.utils.autocomplete import (
    team_autocomplete,
    pending_or_scheduled_match_autocomplete,
    active_match_autocomplete,
)
from bot.config import (
    ADMIN_IDS,
    MATCH_CATEGORY_ID,
    MATCH_EMBED_CHANNEL_ID,
    ARCHIVE_CATEGORY_ID,
)

log = logging.getLogger(__name__)


async def build_match_embed(match_id: int) -> Optional[str]:
    async with connection.pool.acquire() as conn:
        match = await conn.fetchrow("SELECT * FROM matches WHERE id = $1", match_id)
        if not match:
            return None

        team1 = await conn.fetchrow("SELECT name FROM teams WHERE id = $1", match['team1_id'])
        team2 = await conn.fetchrow("SELECT name FROM teams WHERE id = $1", match['team2_id'])

        t1_name = team1['name'] if team1 else "Team 1"
        t2_name = team2['name'] if team2 else "Team 2"

        scores1 = {r['district']: r for r in await conn.fetch(
            "SELECT * FROM district_scores WHERE match_id = $1 AND team_id = $2",
            match_id, match['team1_id']
        )}
        scores2 = {r['district']: r for r in await conn.fetch(
            "SELECT * FROM district_scores WHERE match_id = $1 AND team_id = $2",
            match_id, match['team2_id']
        )}

    t1_col = t1_name[:12]
    t2_col = t2_name[:12]
    sep = "-" * 46
    header = f"{'District':<20} {t1_col:<13} {t2_col:<13}"
    rows = [header, sep]

    total1 = 0
    total2 = 0
    total_percent1 = 0
    total_percent2 = 0

    for d in range(9):
        name = DISTRICT_NAMES[d]
        r1 = scores1.get(d)
        r2 = scores2.get(d)

        if r1:
            s1 = r1['override_stars'] if r1['is_overridden'] else r1['current_stars']
            p1 = r1['override_percent'] if r1['is_overridden'] else r1['current_percent']
            col1 = f"{s1}⭐ {p1}%"
            total1 += s1
            total_percent1 += p1
        else:
            col1 = "--"

        if r2:
            s2 = r2['override_stars'] if r2['is_overridden'] else r2['current_stars']
            p2 = r2['override_percent'] if r2['is_overridden'] else r2['current_percent']
            col2 = f"{s2}⭐ {p2}%"
            total2 += s2
            total_percent2 += p2
        else:
            col2 = "--"

        rows.append(f"{name:<20} {col1:<13} {col2:<13}")

    rows.append(sep)
    rows.append(f"{'Total':<20} {str(total1) + '⭐ ' + str(total_percent1) + '%':<13} {str(total2) + '⭐ ' + str(total_percent2) + '%':<13}")

    content = "\n".join(rows)
    return f"**{t1_name} vs {t2_name}**\n```\n{content}\n```"


async def refresh_match_embed(bot: discord.Client, match_id: int):
    async with connection.pool.acquire() as conn:
        match = await conn.fetchrow(
            "SELECT embed_message_id FROM matches WHERE id = $1", match_id
        )
    if not match or not match['embed_message_id']:
        return

    message_content = await build_match_embed(match_id)
    if not message_content:
        return

    embed_channel = bot.get_channel(MATCH_EMBED_CHANNEL_ID)
    if not embed_channel:
        return

    try:
        msg = await embed_channel.fetch_message(match['embed_message_id'])
        await msg.edit(content=message_content, embed=None)
    except discord.NotFound:
        log.warning(f"Embed message not found for match {match_id}")
    except Exception as e:
        log.error(f"Failed to refresh match embed: {e}")


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\consolab.ttf" if bold else r"C:\Windows\Fonts\consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            if candidate and Path(candidate).exists():
                return ImageFont.truetype(candidate, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def render_match_timezone_image(match_title: str, teams: list[tuple[str, list[dict]]]) -> io.BytesIO:
    gmt_hours = list(range(9, 22))
    left = 36
    top = 128
    bottom = 38
    row_h = 48
    header_h = 42
    team_h = 34
    player_w = 270
    tz_w = 118
    hour_w = 78
    width = left * 2 + player_w + tz_w + hour_w * len(gmt_hours)

    total_rows = sum(len(players) + 1 for _, players in teams)
    height = top + header_h + (total_rows * row_h) + (len(teams) * team_h) + bottom

    image = Image.new("RGB", (width, height), "#f5f7fb")
    draw = ImageDraw.Draw(image)

    title_font = _load_font(34, bold=True)
    subtitle_font = _load_font(18)
    header_font = _load_font(18, bold=True)
    row_font = _load_font(18)
    small_font = _load_font(15)

    draw.rounded_rectangle((24, 20, width - 24, 104), radius=18, fill="#1f2937")
    draw.text((48, 38), match_title, font=title_font, fill="#ffffff")
    draw.text((48, 76), "GMT 09:00 to 21:00 - each row shows the stored UTC offset", font=subtitle_font, fill="#d1d5db")

    x0 = left
    y = top

    draw.rounded_rectangle((x0, y, width - left, y + header_h), radius=12, fill="#dde7f3")
    draw.text((x0 + 14, y + 10), "Player", font=header_font, fill="#111827")
    draw.text((x0 + player_w + 14, y + 10), "Timezone", font=header_font, fill="#111827")
    for idx, hour in enumerate(gmt_hours):
        cell_x = x0 + player_w + tz_w + (idx * hour_w)
        label = f"GMT {hour:02d}:00"
        tw, th = _text_size(draw, label, header_font)
        draw.text((cell_x + (hour_w - tw) / 2, y + (header_h - th) / 2 - 1), label, font=header_font, fill="#111827")

    y += header_h + 12
    section_index = 0

    for team_name, players in teams:
        section_fill = "#cfd8e3" if section_index % 2 == 0 else "#d9e4db"
        draw.rounded_rectangle((x0, y, width - left, y + team_h), radius=10, fill=section_fill)
        draw.text((x0 + 14, y + 8), f"{team_name} ({len(players)})", font=header_font, fill="#111827")
        y += team_h + 8
        section_index += 1

        for row_index, player in enumerate(players):
            fill = "#ffffff" if row_index % 2 == 0 else "#f0f4f8"
            draw.rounded_rectangle((x0, y, width - left, y + row_h), radius=10, fill=fill)

            name = player["display_name"]
            tz_text = player.get("timezone_display") or "Not set"
            offset_minutes = player.get("timezone_offset_minutes")

            draw.text((x0 + 14, y + 13), name, font=row_font, fill="#111827")
            draw.text((x0 + player_w + 14, y + 13), tz_text, font=row_font, fill="#111827")

            for idx, hour in enumerate(gmt_hours):
                cell_x = x0 + player_w + tz_w + (idx * hour_w)
                if offset_minutes is None:
                    label = "--"
                else:
                    label = local_time_label(hour, offset_minutes)
                tw, th = _text_size(draw, label, row_font)
                draw.text((cell_x + (hour_w - tw) / 2, y + (row_h - th) / 2 - 1), label, font=row_font, fill="#111827")

            y += row_h + 6

        y += 2

    draw.text((left, height - 24), "Players without a stored timezone are shown as UTC+00:00.", font=small_font, fill="#4b5563")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


class Matches(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="set-match", description="Schedule a match between two teams (Admin only).")
    @app_commands.autocomplete(team1=team_autocomplete, team2=team_autocomplete)
    @is_admin()
    async def set_match(self, interaction: discord.Interaction, team1: str, team2: str):
        await interaction.response.defer(ephemeral=True)

        if team1.lower() == team2.lower():
            await interaction.followup.send(embed=error_embed("Invalid", "A team cannot play against itself."))
            return

        async with connection.pool.acquire() as conn:
            t1 = await conn.fetchrow("SELECT * FROM teams WHERE name = $1 AND is_approved = TRUE", team1)
            t2 = await conn.fetchrow("SELECT * FROM teams WHERE name = $1 AND is_approved = TRUE", team2)

            if not t1:
                await interaction.followup.send(embed=error_embed("Not Found", f"Approved team '{team1}' not found."))
                return
            if not t2:
                await interaction.followup.send(embed=error_embed("Not Found", f"Approved team '{team2}' not found."))
                return

            existing_count = await conn.fetchval(
                """SELECT COUNT(*) FROM matches
                WHERE (team1_id = $1 AND team2_id = $2) OR (team1_id = $2 AND team2_id = $1)""",
                t1['id'], t2['id']
            )
            match_number = existing_count + 1

            match_id = await conn.fetchval(
                """INSERT INTO matches (team1_id, team2_id, status, match_number)
                VALUES ($1, $2, 'pending', $3) RETURNING id""",
                t1['id'], t2['id'], match_number
            )

            guild = interaction.guild
            category = guild.get_channel(MATCH_CATEGORY_ID)

            t1_role = guild.get_role(t1['team_role_id'])
            t2_role = guild.get_role(t2['team_role_id'])

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True),
            }
            if t1_role:
                overwrites[t1_role] = discord.PermissionOverwrite(read_messages=True)
            if t2_role:
                overwrites[t2_role] = discord.PermissionOverwrite(read_messages=True)
            for admin_id in ADMIN_IDS:
                member = guild.get_member(admin_id)
                if member:
                    overwrites[member] = discord.PermissionOverwrite(read_messages=True)

            base_name = f"{team1.lower().replace(' ', '_')}_vs_{team2.lower().replace(' ', '_')}"
            channel_name = base_name if match_number == 1 else f"{base_name}-{match_number}"

            try:
                channel = await guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites
                )
                await conn.execute(
                    "UPDATE matches SET channel_id = $1 WHERE id = $2",
                    channel.id, match_id
                )
                ping = " ".join(r.mention for r in [t1_role, t2_role] if r)
                await channel.send(f"{ping}\nUse this channel to decide the time for the match.")
            except Exception as e:
                log.error(f"Failed to create match channel: {e}")
                channel = None

            msg = f"Match #{match_id} created: **{team1}** vs **{team2}**"
            if channel:
                msg += f"\nChannel: {channel.mention}"
            await interaction.followup.send(embed=success_embed("Match Scheduled", msg))

    @app_commands.command(name="schedule-match", description="Set the time and mark a match as scheduled (Admin only).")
    @app_commands.autocomplete(match_id=pending_or_scheduled_match_autocomplete)
    @is_admin()
    async def schedule_match(self, interaction: discord.Interaction, match_id: int, unix_timestamp: int):
        await interaction.response.defer(ephemeral=True)

        async with connection.pool.acquire() as conn:
            match = await conn.fetchrow("SELECT id, status FROM matches WHERE id = $1", match_id)
            if not match:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match_id} does not exist."))
                return
            if match['status'] not in ('pending', 'scheduled'):
                await interaction.followup.send(embed=error_embed("Invalid", f"Match #{match_id} cannot be scheduled at this stage."))
                return

            dt = datetime.utcfromtimestamp(unix_timestamp)
            await conn.execute(
                "UPDATE matches SET scheduled_time = $1, status = 'scheduled' WHERE id = $2",
                dt, match_id
            )

        await interaction.followup.send(
            embed=success_embed(
                "Match Scheduled",
                f"Match #{match_id} is now scheduled for <t:{unix_timestamp}:F>"
            )
        )

    @app_commands.command(name="start-match", description="Start a match and post the live embed (Admin only).")
    @app_commands.autocomplete(match_id=pending_or_scheduled_match_autocomplete)
    @is_admin()
    async def start_match(self, interaction: discord.Interaction, match_id: int):
        await interaction.response.defer(ephemeral=True)

        async with connection.pool.acquire() as conn:
            match = await conn.fetchrow("SELECT * FROM matches WHERE id = $1", match_id)
            if not match:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match_id} does not exist."))
                return
            if match['status'] != 'scheduled':
                await interaction.followup.send(embed=error_embed("Invalid", f"Match #{match_id} is already {match['status']}."))
                return

            await conn.execute("UPDATE matches SET status = 'active' WHERE id = $1", match_id)

            for team_id in [match['team1_id'], match['team2_id']]:
                for district in range(9):
                    await conn.execute(
                        """INSERT INTO district_scores (match_id, team_id, district)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (match_id, team_id, district) DO NOTHING""",
                        match_id, team_id, district
                    )

        message_content = await build_match_embed(match_id)
        if not message_content:
            await interaction.followup.send(embed=error_embed("Error", "Could not build match scoreboard."))
            return

        embed_channel = self.bot.get_channel(MATCH_EMBED_CHANNEL_ID)
        if not embed_channel:
            await interaction.followup.send(embed=error_embed("Error", "Match embed channel not found."))
            return

        async with connection.pool.acquire() as conn:
            existing = await conn.fetchval("SELECT embed_message_id FROM matches WHERE id = $1", match_id)
            if existing:
                try:
                    msg = await embed_channel.fetch_message(existing)
                    await msg.edit(content=message_content, embed=None)
                    embed_msg = msg
                except discord.NotFound:
                    embed_msg = await embed_channel.send(content=message_content)
            else:
                embed_msg = await embed_channel.send(content=message_content)

            await conn.execute(
                "UPDATE matches SET embed_message_id = $1 WHERE id = $2",
                embed_msg.id, match_id
            )

        await interaction.followup.send(embed=success_embed("Match Started", f"Match #{match_id} is now active. Live embed posted in {embed_channel.mention}."))

    @app_commands.command(name="matches", description="View all matches.")
    async def matches(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        async with connection.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT m.id, m.status, m.scheduled_time,
                       t1.name AS team1_name, t2.name AS team2_name
                FROM matches m
                JOIN teams t1 ON m.team1_id = t1.id
                JOIN teams t2 ON m.team2_id = t2.id
                WHERE m.status IN ('pending', 'scheduled')
                ORDER BY m.id ASC
                """
            )

        if not rows:
            await interaction.followup.send(embed=error_embed("No Matches", "No upcoming matches found."))
            return

        await interaction.followup.send(embed=upcoming_matches_embed(rows))


    @app_commands.command(name="match-timezones", description="Render the timezone layout for a match.")
    @app_commands.autocomplete(match_id=pending_or_scheduled_match_autocomplete)
    async def match_timezones(self, interaction: discord.Interaction, match_id: int):
        await interaction.response.defer(ephemeral=False)

        async with connection.pool.acquire() as conn:
            match = await conn.fetchrow(
                """
                SELECT m.id, m.team1_id, m.team2_id, t1.name AS team1_name, t2.name AS team2_name
                FROM matches m
                JOIN teams t1 ON m.team1_id = t1.id
                JOIN teams t2 ON m.team2_id = t2.id
                WHERE m.id = $1
                """,
                match_id,
            )
            if not match:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match_id} does not exist."))
                return

            if interaction.user.id not in ADMIN_IDS:
                allowed = await conn.fetchval(
                    """
                    SELECT EXISTS(
                        SELECT 1
                        FROM team_members
                        WHERE user_id = $1 AND team_id IN ($2, $3)
                    )
                    """,
                    interaction.user.id,
                    match['team1_id'],
                    match['team2_id'],
                )
                if not allowed:
                    await interaction.followup.send(embed=error_embed("Not Allowed", "You are not on either team in this match."))
                    return

            member_rows = await conn.fetch(
                """
                SELECT tm.user_id, tm.role, tm.timezone_offset, t.id AS team_id, t.name AS team_name
                FROM team_members tm
                JOIN teams t ON tm.team_id = t.id
                WHERE tm.team_id IN ($1, $2)
                ORDER BY CASE tm.team_id WHEN $3 THEN 1 WHEN $4 THEN 2 ELSE 3 END,
                         CASE tm.role
                            WHEN 'leader' THEN 1
                            WHEN 'sudo' THEN 2
                            ELSE 3
                         END,
                         tm.user_id ASC
                """,
                match['team1_id'],
                match['team2_id'],
                match['team1_id'],
                match['team2_id'],
            )

        team_groups = []
        current_team_id = None
        current_team_name = None
        current_players = []

        for row in member_rows:
            if current_team_id != row['team_id']:
                if current_team_name is not None:
                    team_groups.append((current_team_name, current_players))
                current_team_id = row['team_id']
                current_team_name = row['team_name']
                current_players = []

            offset_text = row['timezone_offset'] or '+00:00'
            current_players.append(
                {
                    'display_name': await get_username(self.bot, row['user_id'], interaction.guild),
                    'timezone_display': utc_label(offset_text),
                    'timezone_offset_minutes': timezone_offset_to_minutes(offset_text),
                }
            )

        if current_team_name is not None:
            team_groups.append((current_team_name, current_players))

        image = render_match_timezone_image(
            f"Match #{match['id']}: {match['team1_name']} vs {match['team2_name']}",
            team_groups,
        )
        file = discord.File(image, filename="match_timezones.png")
        embed = success_embed(
            "Match Timezones",
            "GMT 09:00 to 21:00. Each row shows the converted local time for that player's UTC offset.",
        )
        embed.set_image(url="attachment://match_timezones.png")

        await interaction.followup.send(embed=embed, file=file)

    @app_commands.command(name="end-match", description="End a match and move it to archive (Admin only).")
    @app_commands.autocomplete(match_id=active_match_autocomplete)
    @is_admin()
    async def end_match(self, interaction: discord.Interaction, match_id: int):
        await interaction.response.defer(ephemeral=True)

        async with connection.pool.acquire() as conn:
            match = await conn.fetchrow("SELECT * FROM matches WHERE id = $1", match_id)
            if not match:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match_id} does not exist."))
                return

            if match['status'] == 'completed':
                await interaction.followup.send(embed=error_embed("Already Completed", f"Match #{match_id} is already completed."))
                return

            team1 = await conn.fetchrow("SELECT name FROM teams WHERE id = $1", match['team1_id'])
            team2 = await conn.fetchrow("SELECT name FROM teams WHERE id = $1", match['team2_id'])
            t1_name = team1['name'] if team1 else "Team 1"
            t2_name = team2['name'] if team2 else "Team 2"

            await conn.execute("UPDATE matches SET status = 'completed' WHERE id = $1", match_id)

        guild = interaction.guild

        # Move channel to archive
        if match['channel_id']:
            channel = guild.get_channel(match['channel_id'])
            if channel and ARCHIVE_CATEGORY_ID:
                archive_category = guild.get_channel(ARCHIVE_CATEGORY_ID)
                if archive_category:
                    try:
                        await channel.edit(category=archive_category)
                    except discord.HTTPException as e:
                        log.error(f"Failed to move channel to archive: {e}")

        await interaction.followup.send(
            embed=success_embed("Match Ended", f"Match #{match_id} ({t1_name} vs {t2_name}) has been marked as completed and archived.")
        )

    @app_commands.command(name="delete-match", description="Delete a match completely (Admin only).")
    @app_commands.autocomplete(match_id=pending_or_scheduled_match_autocomplete)
    @is_admin()
    async def delete_match(self, interaction: discord.Interaction, match_id: int):
        await interaction.response.defer(ephemeral=True)

        async with connection.pool.acquire() as conn:
            match = await conn.fetchrow(
                """SELECT m.*, t1.name AS team1_name, t2.name AS team2_name
                FROM matches m
                JOIN teams t1 ON m.team1_id = t1.id
                JOIN teams t2 ON m.team2_id = t2.id
                WHERE m.id = $1""",
                match_id
            )
            if not match:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match_id} does not exist."))
                return

            await conn.execute("DELETE FROM matches WHERE id = $1", match_id)

        await interaction.followup.send(
            embed=success_embed("Match Deleted", f"Match #{match_id} ({match['team1_name']} vs {match['team2_name']}) has been deleted.")
        )

    @app_commands.command(name="clear-data", description="Wipe all data from the database (Admin only — testing use).")
    @is_admin()
    async def clear_data(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with connection.pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE attacks, district_scores, bases, matches, qualifier_scores RESTART IDENTITY CASCADE"
            )
        await interaction.followup.send(embed=success_embed("Database Cleared", "All data has been wiped. Tables are empty and ready for testing."))


async def setup(bot: commands.Bot):
    await bot.add_cog(Matches(bot))
