import discord
from discord.ext import commands
from discord import app_commands
import logging
import io
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiohttp
from PIL import Image, ImageDraw, ImageFont
from PIL import ImageFilter

import bot.db.connection as connection
from bot.utils.checks import is_admin
from bot.utils.embeds import success_embed, error_embed, upcoming_matches_embed
from bot.utils.discord_utils import get_username
from bot.utils.timezones import display_timezone_offset, local_time_label, timezone_offset_to_minutes
from bot.utils.text_formatting import to_sans_serif_bold
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


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font,
    fill: str,
    *,
    stroke_fill: str | None = None,
    stroke_width: int = 0,
) -> None:
    tw, th = _text_size(draw, text, font)
    x = box[0] + ((box[2] - box[0] - tw) / 2)
    y = box[1] + ((box[3] - box[1] - th) / 2) - 2
    draw.text((x, y), text, font=font, fill=fill, stroke_fill=stroke_fill, stroke_width=stroke_width)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, size: int, *, bold: bool = True, min_size: int = 18):
    font = _load_font(size, bold=bold)
    while size > min_size and _text_size(draw, text, font)[0] > max_width:
        size -= 2
        font = _load_font(size, bold=bold)
    return font


def _score_text(stars: int, percent: int) -> str:
    return f"{stars}.{percent}"


async def _download_image(url: Optional[str]) -> Optional[bytes]:
    if not url:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception as e:
        log.warning(f"Failed to download result background image: {e}")

    return None


def render_match_result_image(
    team1_name: str,
    team2_name: str,
    rows: list[dict],
    totals: dict[int, tuple[int, int]],
    team1_id: int,
    team2_id: int,
    *,
    subtitle: Optional[str] = None,
    note: Optional[str] = None,
    background_bytes: Optional[bytes] = None,
) -> io.BytesIO:
    width = 900
    height = 900

    image = Image.new("RGBA", (width, height), "#ffffff")
    if background_bytes:
        try:
            logo = Image.open(io.BytesIO(background_bytes)).convert("RGBA")
            logo_ratio = logo.width / logo.height
            canvas_ratio = width / height
            if logo_ratio > canvas_ratio:
                new_w = width
                new_h = int(width / logo_ratio)
            else:
                new_h = height
                new_w = int(height * logo_ratio)
            logo = logo.resize((new_w, new_h), Image.Resampling.LANCZOS)
            logo_layer = Image.new("RGBA", (width, height), (255, 255, 255, 0))
            logo_x = (width - logo.width) // 2
            logo_y = (height - logo.height) // 2
            logo_layer.alpha_composite(logo, (logo_x, logo_y))
            image.alpha_composite(logo_layer)
        except Exception as e:
            log.warning(f"Failed to render result background image: {e}")

    draw = ImageDraw.Draw(image)

    title_font = _load_font(56, bold=True)
    subtitle_font = _load_font(34, bold=True)
    header_font = _load_font(32, bold=True)
    district_font = _load_font(25, bold=True)
    score_font = _load_font(31, bold=True)
    total_font = _load_font(34, bold=True)
    note_font = _load_font(23, bold=True)

    title = "Anshu Invitational 3"
    title_w, title_h = _text_size(draw, title, title_font)
    draw.text(
        ((width - title_w) / 2, 18),
        title,
        font=title_font,
        fill="#7df6d0",
        stroke_fill="#05070b",
        stroke_width=4,
    )
    draw.rectangle((90, 83, width - 90, 91), fill="#7df6d0")

    y = 99
    if subtitle:
        subtitle_font = _fit_font(draw, subtitle, width - 120, 34, bold=True, min_size=22)
        sub_w, sub_h = _text_size(draw, subtitle, subtitle_font)
        draw.text(
            ((width - sub_w) / 2, y),
            subtitle,
            font=subtitle_font,
            fill="#f6f7fb",
            stroke_fill="#05070b",
            stroke_width=4,
        )
        y += sub_h + 20
    else:
        y += 16

    table_left = 42
    table_right = width - 42
    table_top = y
    table_bottom = 810 if note else 850
    table_w = table_right - table_left
    header_h = 88
    total_h = 62
    row_h = (table_bottom - table_top - header_h - total_h) / len(rows)
    col1_w = 322
    col_w = (table_w - col1_w) / 2
    x1 = table_left + col1_w
    x2 = x1 + col_w

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rectangle((table_left, table_top, table_right, table_bottom), fill=(4, 6, 10, 178))
    image.alpha_composite(overlay)
    draw = ImageDraw.Draw(image)

    line_color = "#030303"
    for x in (table_left, x1, x2, table_right):
        draw.line((x, table_top, x, table_bottom), fill=line_color, width=8)
    draw.line((table_left, table_top, table_right, table_top), fill=line_color, width=8)
    draw.line((table_left, table_top + header_h, table_right, table_top + header_h), fill=line_color, width=8)
    draw.line((table_left, table_bottom - total_h, table_right, table_bottom - total_h), fill=line_color, width=8)
    draw.line((table_left, table_bottom, table_right, table_bottom), fill=line_color, width=8)

    _draw_centered_text(
        draw,
        (table_left, table_top, x1, table_top + header_h),
        "District",
        header_font,
        "#cf4056",
        stroke_fill="#f4f4f4",
        stroke_width=2,
    )
    team1_font = _fit_font(draw, team1_name, int(col_w) - 26, 28, bold=True, min_size=18)
    team2_font = _fit_font(draw, team2_name, int(col_w) - 26, 28, bold=True, min_size=18)
    _draw_centered_text(draw, (x1, table_top, x2, table_top + header_h), team1_name, team1_font, "#7df6d0", stroke_fill="#05070b", stroke_width=3)
    _draw_centered_text(draw, (x2, table_top, table_right, table_top + header_h), team2_name, team2_font, "#7df6d0", stroke_fill="#05070b", stroke_width=3)

    row_y = table_top + header_h
    for row in rows:
        district_name = DISTRICT_NAMES[row["district"]]
        district_fit = _fit_font(draw, district_name, col1_w - 26, 25, bold=True, min_size=16)
        _draw_centered_text(draw, (table_left, int(row_y), x1, int(row_y + row_h)), district_name, district_fit, "#f7f7f7", stroke_fill="#05070b", stroke_width=3)
        _draw_centered_text(draw, (x1, int(row_y), x2, int(row_y + row_h)), _score_text(row[team1_id][0], row[team1_id][1]), score_font, "#f7f7f7", stroke_fill="#05070b", stroke_width=3)
        _draw_centered_text(draw, (x2, int(row_y), table_right, int(row_y + row_h)), _score_text(row[team2_id][0], row[team2_id][1]), score_font, "#f7f7f7", stroke_fill="#05070b", stroke_width=3)
        row_y += row_h

    
    _draw_centered_text(draw, (x1, table_bottom - total_h, x2, table_bottom), _score_text(*totals[team1_id]), total_font, "#f4f052", stroke_fill="#05070b", stroke_width=2)
    _draw_centered_text(draw, (x2, table_bottom - total_h, table_right, table_bottom), _score_text(*totals[team2_id]), total_font, "#f4f052", stroke_fill="#05070b", stroke_width=2)

    if note:
        note_font = _fit_font(draw, note, width - 90, 23, bold=True, min_size=15)
        note_w, _ = _text_size(draw, note, note_font)
        note_x = (width - note_w) / 2
        note_y = table_bottom + 18
        draw.text((note_x, note_y), note, font=note_font, fill="#f7f7f7", stroke_fill="#05070b", stroke_width=2)

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

def render_match_timezone_image(match_title: str, teams: list[tuple[str, list[dict]]]) -> io.BytesIO:
    gmt_hours = list(range(9, 22))
    left = 40
    top = 24
    title_h = 72
    header_h = 42
    row_h = 46
    row_gap = 6
    team_gap = 16
    separator_h = 12
    player_w = 260
    tz_w = 110
    hour_w = 70
    width = left * 2 + player_w + tz_w + hour_w * len(gmt_hours)

    player_rows = sum(len(players) for _, players in teams)
    height = top + title_h + 18 + header_h + (player_rows * (row_h + row_gap)) + max(0, len(teams) - 1) * (separator_h + team_gap) + 24

    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)

    title_font = _load_font(42, bold=True)
    header_font = _load_font(22, bold=True)
    row_font = _load_font(22)
    small_font = _load_font(18)

    title_y = top
    title_w, title_h_px = _text_size(draw, match_title, title_font)
    draw.text(((width - title_w) / 2, title_y), match_title, font=title_font, fill="#000000")
    underline_y = title_y + title_h_px + 10
    draw.line((left, underline_y, width - left, underline_y), fill="#000000", width=2)

    x0 = left
    y = underline_y + 18

    draw.rounded_rectangle((x0, y, width - left, y + header_h), radius=10, fill="#e5e7eb")
    draw.text((x0 + 14, y + 11), "Player", font=header_font, fill="#111827")
    draw.text((x0 + player_w + 14, y + 11), "Timezone", font=header_font, fill="#111827")
    for idx, hour in enumerate(gmt_hours):
        cell_x = x0 + player_w + tz_w + (idx * hour_w)
        label = f"{hour}:00"
        tw, th = _text_size(draw, label, header_font)
        draw.text((cell_x + (hour_w - tw) / 2, y + (header_h - th) / 2 - 1), label, font=header_font, fill="#111827")

    y += header_h + 10
    row_index = 0

    for team_index, (_, players) in enumerate(teams):
        for player in players:
            fill = "#ffffff" if row_index % 2 == 0 else "#f3f4f6"
            draw.rounded_rectangle((x0, y, width - left, y + row_h), radius=10, fill=fill)

            name = player["display_name"]
            tz_text = player.get("timezone_display") or "+0:00"
            offset_minutes = player.get("timezone_offset_minutes")

            draw.text((x0 + 14, y + 13), name, font=row_font, fill="#111827")
            draw.text((x0 + player_w + 14, y + 13), tz_text, font=row_font, fill="#111827")

            for idx, hour in enumerate(gmt_hours):
                cell_x = x0 + player_w + tz_w + (idx * hour_w)
                label = "--" if offset_minutes is None else local_time_label(hour, offset_minutes)
                tw, th = _text_size(draw, label, row_font)
                draw.text((cell_x + (hour_w - tw) / 2, y + (row_h - th) / 2 - 1), label, font=row_font, fill="#111827")

            y += row_h + row_gap
            row_index += 1

        if team_index < len(teams) - 1:
            y += team_gap
            draw.line((x0, y - (team_gap // 2), width - left, y - (team_gap // 2)), fill="#000000", width=2)


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
            team_permissions = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                read_message_history=True,
                add_reactions=True,
                attach_files=True,
                use_application_commands=True,
                embed_links=True,
                external_emojis=True,
                external_stickers=True
            )
            if t1_role:
                overwrites[t1_role] = team_permissions
            if t2_role:
                overwrites[t2_role] = team_permissions
            for admin_id in ADMIN_IDS:
                member = guild.get_member(admin_id)
                if member:
                    overwrites[member] = discord.PermissionOverwrite(read_messages=True)

            # Use sans-serif bold Unicode with VS emoji
            base_name = f"{to_sans_serif_bold(team1.replace(' ', '-'))}-🆚-{to_sans_serif_bold(team2.replace(' ', '-'))}"
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
                    'timezone_display': display_timezone_offset(offset_text),
                    'timezone_offset_minutes': timezone_offset_to_minutes(offset_text),
                }
            )

        if current_team_name is not None:
            team_groups.append((current_team_name, current_players))

        image = render_match_timezone_image(
            f"{match['team1_name']} vs {match['team2_name']}",
            team_groups,
        )
        file = discord.File(image, filename="match_timezones.png")

        await interaction.followup.send(file=file)

    @app_commands.command(name="end-match", description="End a match, post the final result image, and move it to archive (Admin only).")
    @app_commands.autocomplete(match_id=active_match_autocomplete)
    @app_commands.describe(
        subtitle="Optional result subtitle, like Lower Bracket Final",
        note="Optional note shown at the bottom of the result image",
    )
    @is_admin()
    async def end_match(self, interaction: discord.Interaction, match_id: int, subtitle: Optional[str] = None, note: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        async with connection.pool.acquire() as conn:
            match = await conn.fetchrow(
                """SELECT m.*, t1.name AS team1_name, t1.logo_url AS team1_logo_url,
                          t2.name AS team2_name, t2.logo_url AS team2_logo_url
                   FROM matches m
                   JOIN teams t1 ON m.team1_id = t1.id
                   JOIN teams t2 ON m.team2_id = t2.id
                   WHERE m.id = $1""",
                match_id,
            )
            if not match:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match_id} does not exist."))
                return

            if match['status'] == 'completed':
                await interaction.followup.send(embed=error_embed("Already Completed", f"Match #{match_id} is already completed."))
                return

            score_rows = await conn.fetch(
                """SELECT district, team_id,
                          CASE WHEN is_overridden THEN override_stars ELSE current_stars END AS stars,
                          CASE WHEN is_overridden THEN override_percent ELSE current_percent END AS percent
                   FROM district_scores
                   WHERE match_id = $1 AND team_id IN ($2, $3)
                   ORDER BY district ASC""",
                match_id,
                match['team1_id'],
                match['team2_id'],
            )

            await conn.execute("UPDATE matches SET status = 'completed' WHERE id = $1", match_id)

        t1_name = match['team1_name']
        t2_name = match['team2_name']
        team1_id = match['team1_id']
        team2_id = match['team2_id']
        score_map = {(row['district'], row['team_id']): (row['stars'] or 0, row['percent'] or 0) for row in score_rows}
        result_rows = []
        totals = {team1_id: [0, 0], team2_id: [0, 0]}

        for district in range(9):
            t1_score = score_map.get((district, team1_id), (0, 0))
            t2_score = score_map.get((district, team2_id), (0, 0))
            result_rows.append({"district": district, team1_id: t1_score, team2_id: t2_score})
            totals[team1_id][0] += t1_score[0]
            totals[team1_id][1] += t1_score[1]
            totals[team2_id][0] += t2_score[0]
            totals[team2_id][1] += t2_score[1]

        final_totals = {team1_id: tuple(totals[team1_id]), team2_id: tuple(totals[team2_id])}
        if final_totals[team1_id] > final_totals[team2_id]:
            winner_name = t1_name
            winner_logo_url = match['team1_logo_url']
        elif final_totals[team2_id] > final_totals[team1_id]:
            winner_name = t2_name
            winner_logo_url = match['team2_logo_url']
        else:
            winner_name = "Tie"
            winner_logo_url = None

        background_bytes = await _download_image(winner_logo_url)
        result_image = render_match_result_image(
            t1_name,
            t2_name,
            result_rows,
            final_totals,
            team1_id,
            team2_id,
            subtitle=subtitle,
            note=note,
            background_bytes=background_bytes,
        )

        result_file = discord.File(result_image, filename=f"match_{match_id}_result.png")
        result_embed = discord.Embed(color=discord.Color.teal())
        result_embed.set_image(url=f"attachment://match_{match_id}_result.png")
        result_embed.set_footer(text="Anshu's Invitational 3")

        result_message_updated = False
        if MATCH_EMBED_CHANNEL_ID and match['embed_message_id']:
            embed_channel = self.bot.get_channel(MATCH_EMBED_CHANNEL_ID)
            if embed_channel:
                try:
                    msg = await embed_channel.fetch_message(match['embed_message_id'])
                    await msg.edit(content=None, embed=result_embed, attachments=[result_file])
                    result_message_updated = True
                except discord.NotFound:
                    log.warning(f"Result message not found for match {match_id}")
                except discord.HTTPException as e:
                    log.error(f"Failed to edit result message for match {match_id}: {e}")

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

        status_line = "Final result image updated on the match message." if result_message_updated else "Match completed, but I could not update the stored match message."
        await interaction.followup.send(
            embed=success_embed("Match Ended", f"Match #{match_id} ({t1_name} vs {t2_name}) has been marked as completed and archived.\n{status_line}")
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
