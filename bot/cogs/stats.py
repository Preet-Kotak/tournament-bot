import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional
from collections import defaultdict

import bot.db.connection as connection
from bot.utils.embeds import success_embed, error_embed, FOOTER
from bot.utils.discord_utils import fetch_player_link
from bot.utils.constants import DISTRICT_NAMES, resolve_district
from bot.utils.autocomplete import (
    district_autocomplete,
    team_autocomplete,
    completed_match_autocomplete,
)

log = logging.getLogger(__name__)

RANK_EMOJIS = ["🥇", "🥈", "🥉"]


def _rank(position: int) -> str:
    """Return medal emoji for top 3, '#N' for the rest."""
    return RANK_EMOJIS[position - 1] if position <= 3 else f"#{position}"


def _resolve_district(district: str) -> Optional[int]:
    return resolve_district(district)


def _paginate(items: list[str], per_page: int = 10) -> list[str]:
    """Split a list of string entries into page-sized chunks joined by double newlines."""
    pages = []
    for i in range(0, len(items), per_page):
        pages.append("\n\n".join(items[i : i + per_page]))
    return pages


class StatsPageView(discord.ui.View):
    """Pagination view for stats commands with large result sets."""

    def __init__(self, embeds: list[discord.Embed], timeout: int = 180):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.embeds) - 1
        self.page_counter.label = f"{self.current_page + 1} / {len(self.embeds)}"

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.gray)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_counter(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass  # display only

    @discord.ui.button(label="Next", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)


def _build_paginated_embeds(title: str, lines: list[str], per_page: int = 10) -> list[discord.Embed]:
    """Build a list of embeds, each holding up to per_page lines."""
    pages = _paginate(lines, per_page)
    embeds = []
    for content in pages:
        embed = success_embed(title=title, description=content)
        embeds.append(embed)
    return embeds


async def _send_paginated(interaction: discord.Interaction, title: str, lines: list[str], per_page: int = 10):
    """Send a paginated response or a single embed if everything fits on one page."""
    embeds = _build_paginated_embeds(title, lines, per_page)
    if len(embeds) == 1:
        await interaction.followup.send(embed=embeds[0])
    else:
        view = StatsPageView(embeds=embeds)
        await interaction.followup.send(embed=embeds[0], view=view)


class Stats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /district-stat-team ───────────────────────────────────────────────────

    @app_commands.command(name="district-stat-team", description="View team rankings for a specific district.")
    @app_commands.autocomplete(district=district_autocomplete, team=team_autocomplete)
    @app_commands.describe(
        district="The district to query",
        team="(Optional) Filter to show only this team's rank",
    )
    async def district_stat_team(
        self,
        interaction: discord.Interaction,
        district: str,
        team: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=False)

        district_num = _resolve_district(district)
        if district_num is None:
            await interaction.followup.send(embed=error_embed("Invalid District", "District not found."), ephemeral=True)
            return

        try:
            async with connection.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        t.name AS team_name,
                        AVG(ds.current_stars) AS avg_stars,
                        AVG(ds.current_percent) AS avg_percent,
                        COUNT(*) AS match_count
                    FROM district_scores ds
                    JOIN matches m ON ds.match_id = m.id
                    JOIN teams t ON ds.team_id = t.id
                    WHERE m.status = 'completed'
                        AND ds.district = $1
                        AND ds.attack2_done = TRUE
                    GROUP BY t.id, t.name
                    ORDER BY avg_stars DESC, avg_percent DESC
                    """,
                    district_num,
                )

            if not rows:
                await interaction.followup.send(
                    embed=error_embed("No Data", f"No completed matches found for **{district}**."),
                    ephemeral=True,
                )
                return

            lines = []
            for idx, row in enumerate(rows, start=1):
                avg_stars = round(row["avg_stars"], 1)
                avg_percent = round(row["avg_percent"], 1)
                lines.append(
                    f"{_rank(idx)} {row['team_name']} — {avg_stars}⭐ {avg_percent}% ({row['match_count']} matches)"
                )

            # If a team filter was supplied, show only that team's entry
            if team:
                team_lower = team.lower()
                filtered = [l for l in lines if team_lower in l.lower()]
                if not filtered:
                    await interaction.followup.send(
                        embed=error_embed("Not Found", f"No data for **{team}** in **{district}**."),
                        ephemeral=True,
                    )
                    return
                lines = filtered

            embed = success_embed(
                title=f"{district} Leaderboard | Teams",
                description="\n".join(lines),
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            log.error(f"Error in district_stat_team: {e}")
            await interaction.followup.send(
                embed=error_embed("Database Error", "An error occurred while fetching team statistics."),
                ephemeral=True,
            )

    # ── /district-stat-player ─────────────────────────────────────────────────

    @app_commands.command(name="district-stat-player", description="View player rankings for a specific district.")
    @app_commands.autocomplete(district=district_autocomplete)
    @app_commands.describe(
        district="The district to query",
        player="(Optional) Filter to show only this player's rank",
    )
    async def district_stat_player(
        self,
        interaction: discord.Interaction,
        district: str,
        player: Optional[discord.Member] = None,
    ):
        await interaction.response.defer(ephemeral=False)

        district_num = _resolve_district(district)
        if district_num is None:
            await interaction.followup.send(embed=error_embed("Invalid District", "District not found."), ephemeral=True)
            return

        try:
            async with connection.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        pds.player_id,
                        AVG(pds.final_stars) AS avg_stars,
                        AVG(pds.final_percent) AS avg_percent,
                        COUNT(*) AS match_count
                    FROM player_district_stats pds
                    JOIN matches m ON pds.match_id = m.id
                    WHERE m.status = 'completed'
                        AND pds.district = $1
                        AND pds.completed = TRUE
                    GROUP BY pds.player_id
                    ORDER BY avg_stars DESC, avg_percent DESC
                    """,
                    district_num,
                )

            if not rows:
                await interaction.followup.send(
                    embed=error_embed("No Data", f"No completed matches found for **{district}**."),
                    ephemeral=True,
                )
                return

            lines = []
            for idx, row in enumerate(rows, start=1):
                avg_stars = round(row["avg_stars"], 1)
                avg_percent = round(row["avg_percent"], 1)
                plink = await fetch_player_link(self.bot, row['player_id'])
                lines.append(
                    f"{_rank(idx)} {plink} — {avg_stars}⭐ {avg_percent}% ({row['match_count']} matches)"
                )

            # If a player filter was supplied, find their rank entry
            if player:
                filtered = [l for l in lines if str(player.id) in l]
                if not filtered:
                    await interaction.followup.send(
                        embed=error_embed("Not Found", f"{player.mention} has no data in **{district}**."),
                        ephemeral=True,
                    )
                    return
                embed = success_embed(
                    title=f"{district} Rank | {player.display_name}",
                    description=filtered[0],
                )
                await interaction.followup.send(embed=embed)
                return

            await _send_paginated(interaction, f"{district} Leaderboard | Players", lines)

        except Exception as e:
            log.error(f"Error in district_stat_player: {e}")
            await interaction.followup.send(
                embed=error_embed("Database Error", "An error occurred while fetching player statistics."),
                ephemeral=True,
            )

    # ── /tournament-stat ──────────────────────────────────────────────────────

    @app_commands.command(name="tournament-stat", description="View average scores for all districts across all completed matches.")
    async def tournament_stat(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        try:
            async with connection.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        ds.district,
                        AVG(ds.current_stars) AS avg_stars,
                        AVG(ds.current_percent) AS avg_percent
                    FROM district_scores ds
                    JOIN matches m ON ds.match_id = m.id
                    WHERE m.status = 'completed'
                        AND ds.attack2_done = TRUE
                    GROUP BY ds.district
                    ORDER BY ds.district
                    """
                )

            if not rows:
                await interaction.followup.send(
                    embed=error_embed("No Data", "No completed matches found."),
                    ephemeral=True,
                )
                return

            district_stats = {row["district"]: (round(row["avg_stars"], 1), round(row["avg_percent"], 1)) for row in rows}
            lines = []
            for d in range(9):
                name = DISTRICT_NAMES[d]
                if d in district_stats:
                    avg_stars, avg_percent = district_stats[d]
                    lines.append(f"{name} — {avg_stars}⭐ {avg_percent}%")
                else:
                    lines.append(f"{name} — No data")

            embed = success_embed(title="Tournament Statistics | All Districts", description="\n".join(lines))
            await interaction.followup.send(embed=embed)

        except Exception as e:
            log.error(f"Error in tournament_stat: {e}")
            await interaction.followup.send(
                embed=error_embed("Database Error", "An error occurred while fetching tournament statistics."),
                ephemeral=True,
            )

    # ── /player-stat-log ──────────────────────────────────────────────────────

    @app_commands.command(name="player-stat-log", description="View complete attack history for a player.")
    async def player_stat_log(self, interaction: discord.Interaction, player: discord.Member):
        await interaction.response.defer(ephemeral=False)

        try:
            async with connection.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        a.district,
                        a.stars_before, a.percent_before,
                        a.stars_after, a.percent_after,
                        t1.name AS team1_name,
                        t2.name AS team2_name
                    FROM attacks a
                    JOIN matches m ON a.match_id = m.id
                    JOIN teams t1 ON m.team1_id = t1.id
                    JOIN teams t2 ON m.team2_id = t2.id
                    WHERE a.attacker_id = $1
                        AND m.status = 'completed'
                    ORDER BY m.id DESC, a.district ASC, a.attack_num ASC
                    """,
                    player.id,
                )

            if not rows:
                await interaction.followup.send(
                    embed=error_embed("No Data", f"No attack history found for {player.mention}."),
                    ephemeral=True,
                )
                return

            lines = [
                f"{row['team1_name']}_vs_{row['team2_name']} | {DISTRICT_NAMES.get(row['district'], str(row['district']))}\n"
                f"{row['stars_before']}⭐ {row['percent_before']}% → {row['stars_after']}⭐ {row['percent_after']}%"
                for row in rows
            ]

            await _send_paginated(interaction, f"Attack Log: {player.display_name}", lines)

        except Exception as e:
            log.error(f"Error in player_stat_log: {e}")
            await interaction.followup.send(
                embed=error_embed("Database Error", "An error occurred while fetching player attack history."),
                ephemeral=True,
            )

    # ── /player-stat ──────────────────────────────────────────────────────────

    @app_commands.command(name="player-stat", description="View average district statistics for a player.")
    async def player_stat(self, interaction: discord.Interaction, player: discord.Member):
        await interaction.response.defer(ephemeral=False)

        try:
            async with connection.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                        pds.district,
                        AVG(pds.final_stars) AS avg_stars,
                        AVG(pds.final_percent) AS avg_percent
                    FROM player_district_stats pds
                    JOIN matches m ON pds.match_id = m.id
                    WHERE pds.player_id = $1
                        AND m.status = 'completed'
                        AND pds.completed = TRUE
                    GROUP BY pds.district
                    ORDER BY pds.district ASC
                    """,
                    player.id,
                )

                totals_row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE pds.final_stars = 3) AS three_star_count,
                        COUNT(*) FILTER (WHERE pds.final_stars = 1) AS one_star_count
                    FROM player_district_stats pds
                    JOIN matches m ON pds.match_id = m.id
                    WHERE pds.player_id = $1
                        AND m.status = 'completed'
                        AND pds.completed = TRUE
                    """,
                    player.id,
                )

            if not rows:
                await interaction.followup.send(
                    embed=error_embed("No Data", f"No district statistics found for {player.mention}."),
                    ephemeral=True,
                )
                return

            lines = [
                f"{DISTRICT_NAMES.get(row['district'], str(row['district']))} — {round(row['avg_stars'], 1)}⭐ {round(row['avg_percent'], 1)}%"
                for row in rows
            ]

            embed = success_embed(title=f"Player Stats: {player.display_name}", description="\n".join(lines))
            embed.set_footer(
                text=f"{FOOTER} | 3⭐: {totals_row['three_star_count']}  •  1⭐: {totals_row['one_star_count']}"
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            log.error(f"Error in player_stat: {e}")
            await interaction.followup.send(
                embed=error_embed("Database Error", "An error occurred while fetching player statistics."),
                ephemeral=True,
            )

    # ── /team-stat-log ────────────────────────────────────────────────────────

    @app_commands.command(name="team-stat-log", description="View complete attack history for a team.")
    @app_commands.autocomplete(team=team_autocomplete)
    async def team_stat_log(self, interaction: discord.Interaction, team: str):
        await interaction.response.defer(ephemeral=False)

        try:
            async with connection.pool.acquire() as conn:
                team_row = await conn.fetchrow("SELECT id FROM teams WHERE name = $1", team)
                if not team_row:
                    await interaction.followup.send(
                        embed=error_embed("Team Not Found", f"Team '{team}' not found."),
                        ephemeral=True,
                    )
                    return

                rows = await conn.fetch(
                    """
                    SELECT
                        a.district,
                        a.attacker_id,
                        a.stars_before, a.percent_before,
                        a.stars_after, a.percent_after,
                        t1.name AS team1_name,
                        t2.name AS team2_name
                    FROM attacks a
                    JOIN matches m ON a.match_id = m.id
                    JOIN teams t1 ON m.team1_id = t1.id
                    JOIN teams t2 ON m.team2_id = t2.id
                    WHERE a.team_id = $1
                        AND m.status = 'completed'
                    ORDER BY m.id DESC, a.district ASC, a.attack_num ASC
                    """,
                    team_row["id"],
                )

            if not rows:
                await interaction.followup.send(
                    embed=error_embed("No Data", f"No attack history found for team '{team}'."),
                    ephemeral=True,
                )
                return

            lines = []
            for row in rows:
                plink = await fetch_player_link(self.bot, row['attacker_id'])
                lines.append(
                    f"{row['team1_name']}_vs_{row['team2_name']} | {DISTRICT_NAMES.get(row['district'], str(row['district']))}\n"
                    f"{plink} {row['stars_before']}⭐ {row['percent_before']}% → "
                    f"{row['stars_after']}⭐ {row['percent_after']}%"
                )

            await _send_paginated(interaction, f"Team Attack Log: {team}", lines)

        except Exception as e:
            log.error(f"Error in team_stat_log: {e}")
            await interaction.followup.send(
                embed=error_embed("Database Error", "An error occurred while fetching team attack history."),
                ephemeral=True,
            )

    # ── /team-stat ────────────────────────────────────────────────────────────

    @app_commands.command(name="team-stat", description="View average district statistics for a team.")
    @app_commands.autocomplete(team=team_autocomplete)
    async def team_stat(self, interaction: discord.Interaction, team: str):
        await interaction.response.defer(ephemeral=False)

        try:
            async with connection.pool.acquire() as conn:
                team_row = await conn.fetchrow("SELECT id FROM teams WHERE name = $1", team)
                if not team_row:
                    await interaction.followup.send(
                        embed=error_embed("Team Not Found", f"Team '{team}' not found."),
                        ephemeral=True,
                    )
                    return

                rows = await conn.fetch(
                    """
                    SELECT
                        ds.district,
                        AVG(ds.current_stars) AS avg_stars,
                        AVG(ds.current_percent) AS avg_percent
                    FROM district_scores ds
                    JOIN matches m ON ds.match_id = m.id
                    WHERE ds.team_id = $1
                        AND m.status = 'completed'
                        AND ds.attack2_done = TRUE
                    GROUP BY ds.district
                    ORDER BY ds.district ASC
                    """,
                    team_row["id"],
                )

                totals_row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE ds.current_stars = 3) AS three_star_count,
                        COUNT(*) FILTER (WHERE ds.current_stars = 1) AS one_star_count
                    FROM district_scores ds
                    JOIN matches m ON ds.match_id = m.id
                    WHERE ds.team_id = $1
                        AND m.status = 'completed'
                        AND ds.attack2_done = TRUE
                    """,
                    team_row["id"],
                )

            if not rows:
                await interaction.followup.send(
                    embed=error_embed("No Data", f"No district statistics found for team '{team}'."),
                    ephemeral=True,
                )
                return

            lines = [
                f"{DISTRICT_NAMES.get(row['district'], str(row['district']))} — {round(row['avg_stars'], 1)}⭐ {round(row['avg_percent'], 1)}%"
                for row in rows
            ]

            embed = success_embed(title=f"Team Stats: {team}", description="\n".join(lines))
            embed.set_footer(
                text=f"{FOOTER} | 3⭐: {totals_row['three_star_count']}  •  1⭐: {totals_row['one_star_count']}"
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            log.error(f"Error in team_stat: {e}")
            await interaction.followup.send(
                embed=error_embed("Database Error", "An error occurred while fetching team statistics."),
                ephemeral=True,
            )

    # ── /match-stat ───────────────────────────────────────────────────────────

    @app_commands.command(name="match-stat", description="View detailed district statistics for a completed match.")
    @app_commands.autocomplete(match_id=completed_match_autocomplete)
    async def match_stat(self, interaction: discord.Interaction, match_id: int):
        await interaction.response.defer(ephemeral=False)

        try:
            async with connection.pool.acquire() as conn:
                match_row = await conn.fetchrow(
                    """
                    SELECT m.id, m.team1_id, m.team2_id,
                           t1.name AS team1_name, t2.name AS team2_name
                    FROM matches m
                    JOIN teams t1 ON m.team1_id = t1.id
                    JOIN teams t2 ON m.team2_id = t2.id
                    WHERE m.id = $1 AND m.status = 'completed'
                    """,
                    match_id,
                )

                if not match_row:
                    await interaction.followup.send(
                        embed=error_embed("Match Not Found", f"Match #{match_id} does not exist or is not completed."),
                        ephemeral=True,
                    )
                    return

                score_rows = await conn.fetch(
                    """
                    SELECT district, team_id, current_stars, current_percent
                    FROM district_scores
                    WHERE match_id = $1 AND team_id IN ($2, $3)
                    ORDER BY district ASC, team_id ASC
                    """,
                    match_id, match_row["team1_id"], match_row["team2_id"],
                )

            team1_id = match_row["team1_id"]
            team2_id = match_row["team2_id"]
            team1_name = match_row["team1_name"]
            team2_name = match_row["team2_name"]

            # Build nested lookup {district: {team_id: row}}
            scores: dict = {}
            for row in score_rows:
                scores.setdefault(row["district"], {})[row["team_id"]] = row

            COL_DISTRICT = 22
            COL_TEAM = 14

            def fmt(stars: int, percent: int) -> str:
                return f"{stars}\u2b50 {percent}%"

            header = f"{'District':<{COL_DISTRICT}}{team1_name:<{COL_TEAM}}{team2_name}"
            sep = "-" * (COL_DISTRICT + COL_TEAM + len(team2_name) + 2)

            t1_stars = t1_pct = t2_stars = t2_pct = 0
            district_lines = []
            for d in range(9):
                d1 = scores.get(d, {}).get(team1_id)
                d2 = scores.get(d, {}).get(team2_id)
                s1 = d1["current_stars"] if d1 else 0
                p1 = d1["current_percent"] if d1 else 0
                s2 = d2["current_stars"] if d2 else 0
                p2 = d2["current_percent"] if d2 else 0
                t1_stars += s1; t1_pct += p1
                t2_stars += s2; t2_pct += p2
                district_lines.append(f"{DISTRICT_NAMES[d]:<{COL_DISTRICT}}{fmt(s1, p1):<{COL_TEAM}}{fmt(s2, p2)}")

            total_line = f"{'Total':<{COL_DISTRICT}}{fmt(t1_stars, t1_pct):<{COL_TEAM}}{fmt(t2_stars, t2_pct)}"

            if t1_stars > t2_stars or (t1_stars == t2_stars and t1_pct >= t2_pct):
                winner = team1_name
            else:
                winner = team2_name

            table = "\n".join([header, sep, *district_lines, sep, total_line, "", f"Winner: {winner}"])
            embed = success_embed(
                title=f"Match #{match_id}: {team1_name} vs {team2_name}",
                description=f"```\n{table}\n```",
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            log.error(f"Error in match_stat: {e}")
            await interaction.followup.send(
                embed=error_embed("Database Error", "An error occurred while fetching match statistics."),
                ephemeral=True,
            )


    # ── /relative-lb-player ─────────────────────────────────────────────────

    @app_commands.command(
        name="relative-lb-player",
        description="Player leaderboard with scores normalized across all districts."
    )
    async def relative_lb_player(self, interaction: discord.Interaction):
        """
        Formula:
            adj_stars   = (player_avg_on_district / district_avg) * global_avg_stars
            adj_percent = (player_avg_on_district / district_avg) * global_avg_percent
        Capped at 3 / 100.  Only counts player_district_stats where completed = TRUE.
        """
        await interaction.response.defer(ephemeral=False)

        try:
            async with connection.pool.acquire() as conn:
                # 1. Global average (avg of all 9 district averages)
                global_avg = await conn.fetchrow(
                    """
                    SELECT
                        AVG(avg_stars)   AS global_avg_stars,
                        AVG(avg_percent) AS global_avg_percent
                    FROM (
                        SELECT district,
                               AVG(current_stars)   AS avg_stars,
                               AVG(current_percent) AS avg_percent
                        FROM district_scores ds
                        JOIN matches m ON ds.match_id = m.id
                        WHERE m.status = 'completed'
                          AND ds.attack2_done = TRUE
                        GROUP BY district
                    ) district_avgs
                    """
                )
                if not global_avg or global_avg["global_avg_stars"] is None:
                    await interaction.followup.send(
                        embed=error_embed("No Data", "No completed matches found.")
                    )
                    return

                global_avg_stars   = float(global_avg["global_avg_stars"])
                global_avg_percent = float(global_avg["global_avg_percent"])

                # 2. Per-district averages
                district_avgs = await conn.fetch(
                    """
                    SELECT district,
                           AVG(current_stars)   AS avg_stars,
                           AVG(current_percent) AS avg_percent
                    FROM district_scores ds
                    JOIN matches m ON ds.match_id = m.id
                    WHERE m.status = 'completed'
                      AND ds.attack2_done = TRUE
                    GROUP BY district
                    """
                )
                district_avg_map = {
                    r["district"]: (float(r["avg_stars"]), float(r["avg_percent"]))
                    for r in district_avgs
                }

                # 3. Player averages per district (from player_district_stats, completed only)
                rows = await conn.fetch(
                    """
                    SELECT
                        pds.player_id,
                        pds.district,
                        AVG(pds.final_stars)   AS avg_stars,
                        AVG(pds.final_percent) AS avg_percent,
                        COUNT(*) AS match_count
                    FROM player_district_stats pds
                    JOIN matches m ON pds.match_id = m.id
                    WHERE m.status = 'completed'
                      AND pds.completed = TRUE
                    GROUP BY pds.player_id, pds.district
                    """
                )

                if not rows:
                    await interaction.followup.send(
                        embed=error_embed("No Data", "No player statistics found.")
                    )
                    return

                # 4. Group by player and normalize
                player_data = defaultdict(list)
                for r in rows:
                    player_data[r["player_id"]].append(
                        (r["district"], r["avg_stars"], r["avg_percent"], r["match_count"])
                    )

                player_scores = []
                for player_id, districts in player_data.items():
                    adj_stars_sum = 0.0
                    adj_pct_sum   = 0.0
                    district_count = 0
                    for district, avg_stars, avg_pct, _ in districts:
                        if district not in district_avg_map:
                            continue
                        d_avg_stars, d_avg_pct = district_avg_map[district]
                        if d_avg_stars == 0 or d_avg_pct == 0:
                            continue

                        ratio_stars = avg_stars / d_avg_stars
                        ratio_pct   = avg_pct   / d_avg_pct

                        adj_stars = min(ratio_stars * global_avg_stars, 3.0)
                        adj_pct   = min(ratio_pct   * global_avg_percent, 100.0)

                        adj_stars_sum += adj_stars
                        adj_pct_sum   += adj_pct
                        district_count += 1

                    if district_count == 0:
                        continue

                    avg_adj_stars = round(adj_stars_sum / district_count, 2)
                    avg_adj_pct   = round(adj_pct_sum   / district_count, 1)
                    player_scores.append(
                        (player_id, avg_adj_stars, avg_adj_pct, district_count)
                    )

                # 5. Sort
                player_scores.sort(key=lambda x: (x[1], x[2]), reverse=True)

                if not player_scores:
                    await interaction.followup.send(
                        embed=error_embed("No Data", "No player scores could be computed.")
                    )
                    return

                lines = []
                for idx, (player_id, adj_stars, adj_pct, d_count) in enumerate(
                    player_scores, start=1
                ):
                    plink = await fetch_player_link(self.bot, player_id)
                    lines.append(
                        f"{_rank(idx)} {plink} — {adj_stars}⭐ {adj_pct}% ({d_count} districts)"
                    )

                title = (
                    "🏆 Relative Player Leaderboard\n"
                    f"Global base: {round(global_avg_stars, 2)}⭐ {round(global_avg_percent, 1)}%"
                )
                await _send_paginated(interaction, title, lines)

        except Exception as e:
            log.error(f"Error in relative_lb_player: {e}")
            await interaction.followup.send(
                embed=error_embed("Database Error", "An error occurred while fetching the leaderboard."),
                ephemeral=True,
            )

    # ── /relative-lb-team ─────────────────────────────────────────────────────

    @app_commands.command(
        name="relative-lb-team",
        description="Team leaderboard with scores normalized across all districts."
    )
    async def relative_lb_team(self, interaction: discord.Interaction):
        """
        Formula:
            adj_stars   = (team_avg_on_district / district_avg) * global_avg_stars
            adj_percent = (team_avg_on_district / district_avg) * global_avg_percent
        Capped at 3 / 100.  Only counts district_scores where attack2_done = TRUE.
        """
        await interaction.response.defer(ephemeral=False)

        try:
            async with connection.pool.acquire() as conn:
                # 1. Global average
                global_avg = await conn.fetchrow(
                    """
                    SELECT
                        AVG(avg_stars)   AS global_avg_stars,
                        AVG(avg_percent) AS global_avg_percent
                    FROM (
                        SELECT district,
                               AVG(current_stars)   AS avg_stars,
                               AVG(current_percent) AS avg_percent
                        FROM district_scores ds
                        JOIN matches m ON ds.match_id = m.id
                        WHERE m.status = 'completed'
                          AND ds.attack2_done = TRUE
                        GROUP BY district
                    ) district_avgs
                    """
                )
                if not global_avg or global_avg["global_avg_stars"] is None:
                    await interaction.followup.send(
                        embed=error_embed("No Data", "No completed matches found.")
                    )
                    return

                global_avg_stars   = float(global_avg["global_avg_stars"])
                global_avg_percent = float(global_avg["global_avg_percent"])

                # 2. Per-district averages
                district_avgs = await conn.fetch(
                    """
                    SELECT district,
                           AVG(current_stars)   AS avg_stars,
                           AVG(current_percent) AS avg_percent
                    FROM district_scores ds
                    JOIN matches m ON ds.match_id = m.id
                    WHERE m.status = 'completed'
                      AND ds.attack2_done = TRUE
                    GROUP BY district
                    """
                )
                district_avg_map = {
                    r["district"]: (float(r["avg_stars"]), float(r["avg_percent"]))
                    for r in district_avgs
                }

                # 3. Team averages per district
                rows = await conn.fetch(
                    """
                    SELECT
                        ds.team_id,
                        t.name AS team_name,
                        ds.district,
                        AVG(ds.current_stars)   AS avg_stars,
                        AVG(ds.current_percent) AS avg_percent,
                        COUNT(*) AS match_count
                    FROM district_scores ds
                    JOIN matches m ON ds.match_id = m.id
                    JOIN teams t ON ds.team_id = t.id
                    WHERE m.status = 'completed'
                      AND ds.attack2_done = TRUE
                    GROUP BY ds.team_id, t.name, ds.district
                    """
                )

                if not rows:
                    await interaction.followup.send(
                        embed=error_embed("No Data", "No team statistics found.")
                    )
                    return

                # 4. Group by team and normalize
                team_data = defaultdict(list)
                for r in rows:
                    team_data[r["team_id"]].append(
                        (r["team_name"], r["district"], r["avg_stars"], r["avg_percent"])
                    )

                team_scores = []
                for team_id, districts in team_data.items():
                    team_name = districts[0][0]
                    adj_stars_sum = 0.0
                    adj_pct_sum   = 0.0
                    district_count = 0
                    for _, district, avg_stars, avg_pct in districts:
                        if district not in district_avg_map:
                            continue
                        d_avg_stars, d_avg_pct = district_avg_map[district]
                        if d_avg_stars == 0 or d_avg_pct == 0:
                            continue

                        ratio_stars = avg_stars / d_avg_stars
                        ratio_pct   = avg_pct   / d_avg_pct

                        adj_stars = min(ratio_stars * global_avg_stars, 3.0)
                        adj_pct   = min(ratio_pct   * global_avg_percent, 100.0)

                        adj_stars_sum += adj_stars
                        adj_pct_sum   += adj_pct
                        district_count += 1

                    if district_count == 0:
                        continue

                    avg_adj_stars = round(adj_stars_sum / district_count, 2)
                    avg_adj_pct   = round(adj_pct_sum   / district_count, 1)
                    team_scores.append(
                        (team_id, team_name, avg_adj_stars, avg_adj_pct, district_count)
                    )

                # 5. Sort
                team_scores.sort(key=lambda x: (x[2], x[3]), reverse=True)

                if not team_scores:
                    await interaction.followup.send(
                        embed=error_embed("No Data", "No team scores could be computed.")
                    )
                    return

                lines = []
                for idx, (team_id, team_name, adj_stars, adj_pct, d_count) in enumerate(
                    team_scores, start=1
                ):
                    lines.append(
                        f"{_rank(idx)} **{team_name}** — {adj_stars}⭐ {adj_pct}% ({d_count} districts)"
                    )

                title = (
                    "🏆 Relative Team Leaderboard\n"
                    f"Global base: {round(global_avg_stars, 2)}⭐ {round(global_avg_percent, 1)}%"
                )
                await _send_paginated(interaction, title, lines)

        except Exception as e:
            log.error(f"Error in relative_lb_team: {e}")
            await interaction.followup.send(
                embed=error_embed("Database Error", "An error occurred while fetching the leaderboard."),
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))
