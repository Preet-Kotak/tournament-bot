import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional

import bot.db.connection as connection
from bot.utils.checks import is_admin
from bot.utils.embeds import success_embed, error_embed, FOOTER
from bot.utils.constants import QUALIFIER_DISTRICTS
from bot.utils.discord_utils import fetch_player_link

log = logging.getLogger(__name__)


# ── Dynamic Admin Check ───────────────────────────────────────────────────────

async def is_qualifier_public_enabled() -> bool:
    """Check if qualifier public commands are enabled."""
    async with connection.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM settings WHERE key = 'qualifier_public_commands'"
        )
        return row["value"].lower() == "true" if row else False


def qualifier_access_check():
    """Decorator that checks if command should be admin-only or public."""
    async def predicate(interaction: discord.Interaction) -> bool:
        # Check if public commands are enabled
        public_enabled = await is_qualifier_public_enabled()
        
        if public_enabled:
            # Public mode - allow everyone
            return True
        else:
            # Admin-only mode - check admin status
            return await is_admin().predicate(interaction)
    
    return app_commands.check(predicate)

RANK_EMOJIS = ["🥇", "🥈", "🥉"]


# ── Autocomplete for Toggle Command ───────────────────────────────────────────

async def bool_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for true/false values."""
    options = [
        app_commands.Choice(name="true", value="true"),
        app_commands.Choice(name="false", value="false"),
    ]
    if not current:
        return options
    return [opt for opt in options if current.lower() in opt.name.lower()]


def _rank(pos: int) -> str:
    return RANK_EMOJIS[pos - 1] if pos <= 3 else f"#{pos}"


def _parse_score(raw: str) -> tuple[int, int] | None:
    """
    Parse 'x.xxx' format into (stars, percent).
    Examples: '2.075' → (2, 75)   '3.100' → (3, 100)   '0.000' → (0, 0)
    Returns None if the format is invalid.
    """
    raw = raw.strip()
    if "." not in raw:
        return None
    left, right = raw.split(".", 1)
    if not left.isdigit() or not right.isdigit():
        return None
    stars = int(left)
    percent = int(right)
    if not (0 <= stars <= 3):
        return None
    if not (0 <= percent <= 100):
        return None
    return stars, percent


def _total_score(rows: list) -> tuple[int, int]:
    """Sum stars and percent across a team's qualifier rows."""
    return sum(r["stars"] for r in rows), sum(r["percent"] for r in rows)


# ── Autocomplete ──────────────────────────────────────────────────────────────

async def qualifier_team_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for approved team names (reused from team_autocomplete pattern)."""
    async with connection.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT name FROM teams WHERE is_approved = TRUE AND LOWER(name) LIKE $1 ORDER BY name LIMIT 25",
            f"%{current.lower()}%",
        )
    return [app_commands.Choice(name=r["name"], value=r["name"]) for r in rows]


async def qualifier_district_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for the 6 qualifier districts."""
    return [
        app_commands.Choice(name=d, value=d)
        for d in QUALIFIER_DISTRICTS
        if current.lower() in d.lower()
    ][:25]


# ── Modal ─────────────────────────────────────────────────────────────────────

class QualifierSubmitModal(discord.ui.Modal, title="Qualifier Score Submission"):
    def __init__(self, cog: "Qualifier", team_name: str, team_id: int, existing: dict):
        super().__init__()
        self.cog = cog
        self.team_name = team_name
        self.team_id = team_id

        default_lines = []
        for district in QUALIFIER_DISTRICTS:
            existing_row = existing.get(district)
            default_value = (
                f"{existing_row['stars']}.{existing_row['percent']:03d}"
                if existing_row
                else ""
            )
            default_lines.append(f"{district}: {default_value}")

        self.scores = discord.ui.TextInput(
            label="Qualifier scores",
            style=discord.TextStyle.long,
            placeholder=(
                "One score per line: `District: stars.percent`.\n"
                "Example: Capital Peak: 2.075"
            ),
            default="\n".join(default_lines),
            required=True,
            min_length=20,
            max_length=1000,
        )
        self.add_item(self.scores)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        parsed: dict[str, tuple[int, int]] = {}
        lines = [line.strip() for line in self.scores.value.splitlines() if line.strip()]
        if len(lines) != len(QUALIFIER_DISTRICTS):
            await interaction.followup.send(
                embed=error_embed(
                    "Invalid Submission",
                    "Please submit exactly one score line for each qualifier district."
                ),
                ephemeral=True,
            )
            return

        for line in lines:
            if ":" not in line:
                await interaction.followup.send(
                    embed=error_embed(
                        "Invalid Format",
                        "Each line must use `District: stars.percent`."
                    ),
                    ephemeral=True,
                )
                return

            district, raw_score = [part.strip() for part in line.split(":", 1)]
            if district not in QUALIFIER_DISTRICTS:
                await interaction.followup.send(
                    embed=error_embed(
                        "Invalid District",
                        f"**{district}** is not a valid qualifier district."
                    ),
                    ephemeral=True,
                )
                return

            if district in parsed:
                await interaction.followup.send(
                    embed=error_embed(
                        "Duplicate District",
                        f"Multiple scores were provided for **{district}**."
                    ),
                    ephemeral=True,
                )
                return

            result = _parse_score(raw_score)
            if result is None:
                await interaction.followup.send(
                    embed=error_embed(
                        "Invalid Score",
                        f"**{district}**: `{raw_score}` is not valid.\n"
                        "Use `stars.percent` — e.g. `2.075` for 2⭐ 75%."
                    ),
                    ephemeral=True,
                )
                return

            parsed[district] = result

        async with connection.pool.acquire() as conn:
            async with conn.transaction():
                for district, (stars, percent) in parsed.items():
                    await conn.execute(
                        """
                        INSERT INTO qualifier_scores (team_id, district, stars, percent, submitted_by)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (team_id, district)
                        DO UPDATE SET stars = $3, percent = $4, submitted_by = $5, submitted_at = NOW()
                        """,
                        self.team_id, district, stars, percent, interaction.user.id,
                    )

        lines = [
            f"**{d}** — {s}⭐ {p}%"
            for d, (s, p) in parsed.items()
        ]
        total_stars = sum(s for s, _ in parsed.values())
        total_pct = sum(p for _, p in parsed.values())
        lines.append(f"\n**Total — {total_stars}⭐ {total_pct}%**")

        await interaction.followup.send(
            embed=success_embed(
                f"Qualifier Scores Submitted — {self.team_name}",
                "\n".join(lines),
            ),
            ephemeral=True,
        )


# ── Cog ───────────────────────────────────────────────────────────────────────

class Qualifier(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /qualifier-submit ─────────────────────────────────────────────────────

    @app_commands.command(name="qualifier-submit", description="Submit qualifier scores for a team (Admin only).")
    @app_commands.autocomplete(team=qualifier_team_autocomplete)
    @app_commands.describe(team="The team to submit scores for")
    @is_admin()
    async def qualifier_submit(self, interaction: discord.Interaction, team: str):
        async with connection.pool.acquire() as conn:
            team_row = await conn.fetchrow(
                "SELECT id FROM teams WHERE name = $1 AND is_approved = TRUE", team
            )
            if not team_row:
                await interaction.response.send_message(
                    embed=error_embed("Not Found", f"Approved team **{team}** not found."),
                    ephemeral=True,
                )
                return

            existing_rows = await conn.fetch(
                "SELECT district, stars, percent FROM qualifier_scores WHERE team_id = $1",
                team_row["id"],
            )

        existing = {r["district"]: r for r in existing_rows}
        modal = QualifierSubmitModal(self, team, team_row["id"], existing)
        await interaction.response.send_modal(modal)

    # ── /qualifier-lb ─────────────────────────────────────────────────────────

    @app_commands.command(name="qualifier-lb", description="Show the qualifier leaderboard.")
    @qualifier_access_check()
    async def qualifier_lb(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        async with connection.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.name AS team_name,
                       SUM(qs.stars)   AS total_stars,
                       SUM(qs.percent) AS total_percent,
                       COUNT(qs.district) AS districts_done
                FROM qualifier_scores qs
                JOIN teams t ON qs.team_id = t.id
                GROUP BY t.id, t.name
                ORDER BY total_stars DESC, total_percent DESC
                """
            )

        if not rows:
            await interaction.followup.send(
                embed=error_embed("No Data", "No qualifier scores have been submitted yet.")
            )
            return

        lines = []
        for idx, row in enumerate(rows, start=1):
            lines.append(
                f"{_rank(idx)} **{row['team_name']}** — "
                f"{row['total_stars']}⭐ {row['total_percent']}%"
            )

        embed = success_embed("🏆 Qualifier Leaderboard", "\n".join(lines))
        await interaction.followup.send(embed=embed)

    # ── /qualifier-team-info ──────────────────────────────────────────────────

    @app_commands.command(name="qualifier-team-info", description="Show a team's qualifier scores and roster.")
    @app_commands.autocomplete(team=qualifier_team_autocomplete)
    @app_commands.describe(team="The team to view")
    @qualifier_access_check()
    async def qualifier_team_info(self, interaction: discord.Interaction, team: str):
        await interaction.response.defer(ephemeral=False)

        async with connection.pool.acquire() as conn:
            team_row = await conn.fetchrow(
                "SELECT id, name, logo_url FROM teams WHERE name = $1 AND is_approved = TRUE", team
            )
            if not team_row:
                await interaction.followup.send(
                    embed=error_embed("Not Found", f"Approved team **{team}** not found."),
                    ephemeral=True,
                )
                return

            members = await conn.fetch(
                """
                SELECT user_id, role FROM team_members
                WHERE team_id = $1
                ORDER BY
                    CASE role WHEN 'leader' THEN 1 WHEN 'sudo' THEN 2 ELSE 3 END,
                    user_id
                """,
                team_row["id"],
            )

            scores = await conn.fetch(
                "SELECT district, stars, percent FROM qualifier_scores WHERE team_id = $1",
                team_row["id"],
            )

        score_map = {r["district"]: r for r in scores}

        embed = discord.Embed(
            title=f"📋 {team_row['name']} — Qualifier",
            color=discord.Color.gold(),
        )

        if team_row["logo_url"]:
            embed.set_thumbnail(url=team_row["logo_url"])

        # Roster
        member_lines = []
        for m in members:
            icon = "👑" if m["role"] == "leader" else "⭐" if m["role"] == "sudo" else "👤"
            label = "(Leader)" if m["role"] == "leader" else "(Co-Leader)" if m["role"] == "sudo" else ""
            plink = await fetch_player_link(self.bot, m['user_id'], interaction.guild)
            member_lines.append(f"{icon} {plink} {label}")
        embed.add_field(
            name=f"Roster ({len(members)})",
            value="\n".join(member_lines) if member_lines else "No members",
            inline=False,
        )

        # Scores per district
        score_lines = []
        total_stars = total_pct = 0
        for district in QUALIFIER_DISTRICTS:
            row = score_map.get(district)
            if row:
                score_lines.append(f"**{district}** — {row['stars']}⭐ {row['percent']}%")
                total_stars += row["stars"]
                total_pct += row["percent"]
            else:
                score_lines.append(f"**{district}** — *not submitted*")

        score_lines.append(f"\n**Total — {total_stars}⭐ {total_pct}%**")
        embed.add_field(name="Qualifier Scores", value="\n".join(score_lines), inline=False)

        embed.set_footer(text=FOOTER)
        await interaction.followup.send(embed=embed)

    # ── /qualifier-district-lb ────────────────────────────────────────────────

    @app_commands.command(name="qualifier-district-lb", description="Show team rankings for a qualifier district.")
    @app_commands.autocomplete(district=qualifier_district_autocomplete)
    @app_commands.describe(district="The qualifier district to view")
    @qualifier_access_check()
    async def qualifier_district_lb(self, interaction: discord.Interaction, district: str):
        await interaction.response.defer(ephemeral=False)

        if district not in QUALIFIER_DISTRICTS:
            await interaction.followup.send(
                embed=error_embed("Invalid District", f"**{district}** is not a qualifier district."),
                ephemeral=True,
            )
            return

        async with connection.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.name AS team_name, qs.stars, qs.percent
                FROM qualifier_scores qs
                JOIN teams t ON qs.team_id = t.id
                WHERE qs.district = $1
                ORDER BY qs.stars DESC, qs.percent DESC
                """,
                district,
            )

        if not rows:
            await interaction.followup.send(
                embed=error_embed("No Data", f"No scores submitted for **{district}** yet.")
            )
            return

        lines = []
        for idx, row in enumerate(rows, start=1):
            lines.append(
                f"{_rank(idx)} **{row['team_name']}** — {row['stars']}⭐ {row['percent']}%"
            )

        total = len(rows)
        avg_stars = round(sum(r["stars"] for r in rows) / total, 2)
        avg_pct = round(sum(r["percent"] for r in rows) / total, 1)

        description = "\n".join(lines) + f"\n\n**Avg — {avg_stars}⭐ {avg_pct}%** across {total} teams"

        embed = success_embed(f"📊 {district} — Qualifier Rankings", description)
        await interaction.followup.send(embed=embed)

    # ── /qualifier-toggle-public ──────────────────────────────────────────────

    @app_commands.command(
        name="qualifier-toggle-public",
        description="Toggle qualifier commands between admin-only and public access (Admin only)."
    )
    @app_commands.autocomplete(enabled=bool_autocomplete)
    @app_commands.describe(enabled="true to make commands public, false to make them admin-only")
    @is_admin()
    async def qualifier_toggle_public(self, interaction: discord.Interaction, enabled: str):
        # Validate input
        enabled_lower = enabled.lower()
        if enabled_lower not in ["true", "false"]:
            await interaction.response.send_message(
                embed=error_embed(
                    "Invalid Input",
                    "Please provide either `true` or `false`."
                ),
                ephemeral=True,
            )
            return

        async with connection.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO settings (key, value)
                VALUES ('qualifier_public_commands', $1)
                ON CONFLICT (key)
                DO UPDATE SET value = $1
                """,
                enabled_lower,
            )

        status = "**public**" if enabled_lower == "true" else "**admin-only**"
        commands_list = "`/qualifier-lb`, `/qualifier-team-info`, `/qualifier-district-lb`"
        
        await interaction.response.send_message(
            embed=success_embed(
                "Qualifier Access Updated",
                f"Qualifier commands ({commands_list}) are now {status}."
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Qualifier(bot))
