import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional

import bot.db.connection as connection
from bot.utils.checks import is_admin
from bot.utils.embeds import success_embed, error_embed
from bot.utils.discord_utils import player_link
from bot.utils.constants import DISTRICT_NAMES, resolve_district
from bot.utils.autocomplete import (
    district_autocomplete,
    team_autocomplete,
    active_match_autocomplete,
)

log = logging.getLogger(__name__)


async def update_player_district_stats(match_id: int, team_id: int, district: int):
    """
    Update player_district_stats for a specific district.
    Called after logging, editing attacks, or editing attackers.

    If both attacks on a district are by the same player, adds/updates a
    player_district_stats record with completed=TRUE and final scores.
    If attacks are by different players (or only one attack exists), removes
    any existing records for all involved players.
    """
    async with connection.pool.acquire() as conn:
        attacks = await conn.fetch(
            """SELECT attacker_id, stars_after, percent_after, attack_num
            FROM attacks
            WHERE match_id = $1 AND team_id = $2 AND district = $3
            ORDER BY attack_num""",
            match_id, team_id, district
        )

        if len(attacks) == 2 and attacks[0]["attacker_id"] == attacks[1]["attacker_id"]:
            player_id = attacks[0]["attacker_id"]
            final_stars = attacks[1]["stars_after"]
            final_percent = attacks[1]["percent_after"]

            await conn.execute(
                """INSERT INTO player_district_stats
                (player_id, match_id, district, completed, final_stars, final_percent)
                VALUES ($1, $2, $3, TRUE, $4, $5)
                ON CONFLICT (player_id, match_id, district)
                DO UPDATE SET completed = TRUE, final_stars = $4, final_percent = $5""",
                player_id, match_id, district, final_stars, final_percent
            )
        else:
            # Different players or incomplete — remove any existing records
            for attack in attacks:
                await conn.execute(
                    """DELETE FROM player_district_stats
                    WHERE player_id = $1 AND match_id = $2 AND district = $3""",
                    attack["attacker_id"], match_id, district
                )


def _resolve_district(district: str) -> Optional[int]:
    """Return the district number for a district name string, or None if not found."""
    return resolve_district(district)


class EditAttackModal(discord.ui.Modal, title="Edit Attack Details"):
    def __init__(self, cog: "Attacks", match_id: int, district: int, team_id: int, team_name: str, prefill_data: dict):
        super().__init__()
        self.cog = cog
        self.match_id = match_id
        self.district = district
        self.team_id = team_id
        self.team_name = team_name

        self.attack1_stars = discord.ui.TextInput(
            label="Attack 1 Stars (0-3)",
            placeholder="Enter stars (0-3)",
            default=str(prefill_data.get("attack1_stars", 0)),
            min_length=1, max_length=1, required=True
        )
        self.attack1_percent = discord.ui.TextInput(
            label="Attack 1 Percent (0-100)",
            placeholder="Enter percent (0-100)",
            default=str(prefill_data.get("attack1_percent", 0)),
            min_length=1, max_length=3, required=True
        )
        self.attack2_stars = discord.ui.TextInput(
            label="Attack 2 Stars (0-3)",
            placeholder="Enter stars (0-3)",
            default=str(prefill_data.get("attack2_stars", 0)),
            min_length=1, max_length=1, required=True
        )
        self.attack2_percent = discord.ui.TextInput(
            label="Attack 2 Percent (0-100)",
            placeholder="Enter percent (0-100)",
            default=str(prefill_data.get("attack2_percent", 0)),
            min_length=1, max_length=3, required=True
        )

        self.add_item(self.attack1_stars)
        self.add_item(self.attack1_percent)
        self.add_item(self.attack2_stars)
        self.add_item(self.attack2_percent)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            a1_stars = int(self.attack1_stars.value)
            a1_percent = int(self.attack1_percent.value)
            a2_stars = int(self.attack2_stars.value)
            a2_percent = int(self.attack2_percent.value)
        except ValueError:
            await interaction.followup.send(embed=error_embed("Invalid Input", "All values must be numbers."))
            return

        if not (0 <= a1_stars <= 3 and 0 <= a2_stars <= 3):
            await interaction.followup.send(embed=error_embed("Invalid Stars", "Stars must be between 0 and 3."))
            return

        if not (0 <= a1_percent <= 100 and 0 <= a2_percent <= 100):
            await interaction.followup.send(embed=error_embed("Invalid Percent", "Percent must be between 0 and 100."))
            return

        async with connection.pool.acquire() as conn:
            attacks = await conn.fetch(
                """SELECT id, attack_num FROM attacks
                WHERE match_id = $1 AND team_id = $2 AND district = $3
                ORDER BY attack_num""",
                self.match_id, self.team_id, self.district
            )

            if len(attacks) >= 1:
                await conn.execute(
                    "UPDATE attacks SET stars_after = $1, percent_after = $2 WHERE id = $3",
                    a1_stars, a1_percent, attacks[0]["id"]
                )

            if len(attacks) >= 2:
                await conn.execute(
                    """UPDATE attacks SET stars_before = $1, percent_before = $2,
                    stars_after = $3, percent_after = $4
                    WHERE id = $5""",
                    a1_stars, a1_percent, a2_stars, a2_percent, attacks[1]["id"]
                )

            await conn.execute(
                """UPDATE district_scores
                SET current_stars = $1, current_percent = $2,
                attack1_done = TRUE, attack2_done = TRUE
                WHERE match_id = $3 AND team_id = $4 AND district = $5""",
                a2_stars, a2_percent, self.match_id, self.team_id, self.district
            )

        await update_player_district_stats(self.match_id, self.team_id, self.district)

        district_name = DISTRICT_NAMES[self.district]
        await interaction.followup.send(
            embed=success_embed(
                "Attack Edited",
                f"Updated attacks for **{self.team_name}** at **{district_name}**:\n"
                f"Attack 1: {a1_stars}⭐ {a1_percent}%\n"
                f"Attack 2: {a2_stars}⭐ {a2_percent}%"
            )
        )

        from bot.cogs.matches import refresh_match_embed
        await refresh_match_embed(self.cog.bot, self.match_id)


class Attacks(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Commands ──────────────────────────────────────────────────────────────

    @app_commands.command(name="log-attack", description="Log both attacks for a district (Admin only).")
    @app_commands.autocomplete(match=active_match_autocomplete, district=district_autocomplete, team=team_autocomplete)
    @app_commands.describe(
        match="The active match ID",
        district="The district name",
        team="The attacking team",
        attacker1="Player who did attack 1",
        attack1_stars="Stars after attack 1 (0-3)",
        attack1_percent="Percent after attack 1 (0-100)",
        attack2_stars="Stars after attack 2 (0-3)",
        attack2_percent="Percent after attack 2 (0-100)",
        attacker2="Player who did attack 2 (defaults to attacker1)",
    )
    @is_admin()
    async def log_attack(
        self,
        interaction: discord.Interaction,
        match: int,
        district: str,
        team: str,
        attacker1: discord.Member,
        attack1_stars: int,
        attack1_percent: int,
        attack2_stars: int,
        attack2_percent: int,
        attacker2: Optional[discord.Member] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        if not (0 <= attack1_stars <= 3 and 0 <= attack2_stars <= 3):
            await interaction.followup.send(embed=error_embed("Invalid Stars", "Stars must be between 0 and 3."))
            return

        if not (0 <= attack1_percent <= 100 and 0 <= attack2_percent <= 100):
            await interaction.followup.send(embed=error_embed("Invalid Percent", "Percent must be between 0 and 100."))
            return

        if attack2_stars < attack1_stars:
            await interaction.followup.send(embed=error_embed("Invalid Attack", "Attack 2 stars must be >= Attack 1 stars."))
            return

        district_num = _resolve_district(district)
        if district_num is None:
            await interaction.followup.send(embed=error_embed("Invalid District", "District not found."))
            return

        if attacker2 is None:
            attacker2 = attacker1

        async with connection.pool.acquire() as conn:
            match_record = await conn.fetchrow("SELECT * FROM matches WHERE id = $1", match)
            if not match_record:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match} does not exist."))
                return

            if match_record["status"] != "active":
                await interaction.followup.send(embed=error_embed("Invalid Status", "Match must be active to log attacks."))
                return

            team_record = await conn.fetchrow("SELECT id, name FROM teams WHERE name = $1", team)
            if not team_record:
                await interaction.followup.send(embed=error_embed("Not Found", f"Team '{team}' not found."))
                return

            if team_record["id"] not in (match_record["team1_id"], match_record["team2_id"]):
                await interaction.followup.send(embed=error_embed("Invalid Team", f"Team '{team}' is not part of this match."))
                return

            existing = await conn.fetchval(
                "SELECT COUNT(*) FROM attacks WHERE match_id = $1 AND team_id = $2 AND district = $3",
                match, team_record["id"], district_num
            )
            if existing > 0:
                await interaction.followup.send(
                    embed=error_embed(
                        "Already Logged",
                        f"Attacks for **{district}** have already been logged for **{team}**. "
                        f"Use `/edit-attack` to modify them."
                    )
                )
                return

            await conn.execute(
                """INSERT INTO attacks
                (match_id, team_id, district, attack_num, attacker_id, stars_before, percent_before, stars_after, percent_after)
                VALUES ($1, $2, $3, 1, $4, 0, 0, $5, $6)""",
                match, team_record["id"], district_num, attacker1.id, attack1_stars, attack1_percent
            )
            await conn.execute(
                """INSERT INTO attacks
                (match_id, team_id, district, attack_num, attacker_id, stars_before, percent_before, stars_after, percent_after)
                VALUES ($1, $2, $3, 2, $4, $5, $6, $7, $8)""",
                match, team_record["id"], district_num, attacker2.id,
                attack1_stars, attack1_percent, attack2_stars, attack2_percent
            )
            await conn.execute(
                """UPDATE district_scores
                SET current_stars = $1, current_percent = $2, attack1_done = TRUE, attack2_done = TRUE
                WHERE match_id = $3 AND team_id = $4 AND district = $5""",
                attack2_stars, attack2_percent, match, team_record["id"], district_num
            )

        await update_player_district_stats(match, team_record["id"], district_num)

        await interaction.followup.send(
            embed=success_embed(
                "Attacks Logged",
                f"Logged attacks for **{team}** at **{district}**:\n"
                f"Attack 1: {player_link(attacker1.id, attacker1.display_name)} — {attack1_stars}⭐ {attack1_percent}%\n"
                f"Attack 2: {player_link(attacker2.id, attacker2.display_name)} — {attack2_stars}⭐ {attack2_percent}%"
            )
        )

        from bot.cogs.matches import refresh_match_embed
        await refresh_match_embed(self.bot, match)

    @app_commands.command(name="edit-attack", description="Edit attack stars and percent for a district (Admin only).")
    @app_commands.autocomplete(match=active_match_autocomplete, district=district_autocomplete, team=team_autocomplete)
    @app_commands.describe(
        match="The active match ID",
        district="The district name",
        team="The attacking team",
    )
    @is_admin()
    async def edit_attack(self, interaction: discord.Interaction, match: int, district: str, team: str):
        district_num = _resolve_district(district)
        if district_num is None:
            await interaction.response.send_message(embed=error_embed("Invalid District", "District not found."), ephemeral=True)
            return

        async with connection.pool.acquire() as conn:
            match_record = await conn.fetchrow("SELECT * FROM matches WHERE id = $1", match)
            if not match_record:
                await interaction.response.send_message(embed=error_embed("Not Found", f"Match #{match} does not exist."), ephemeral=True)
                return

            team_record = await conn.fetchrow("SELECT id, name FROM teams WHERE name = $1", team)
            if not team_record:
                await interaction.response.send_message(embed=error_embed("Not Found", f"Team '{team}' not found."), ephemeral=True)
                return

            if team_record["id"] not in (match_record["team1_id"], match_record["team2_id"]):
                await interaction.response.send_message(embed=error_embed("Invalid Team", f"Team '{team}' is not part of this match."), ephemeral=True)
                return

            attacks = await conn.fetch(
                """SELECT attack_num, stars_after, percent_after
                FROM attacks
                WHERE match_id = $1 AND team_id = $2 AND district = $3
                ORDER BY attack_num""",
                match, team_record["id"], district_num
            )

            if not attacks:
                await interaction.response.send_message(
                    embed=error_embed("No Attacks", f"No attacks logged yet for **{district}** in this match."),
                    ephemeral=True
                )
                return

            prefill = {
                "attack1_stars": attacks[0]["stars_after"] if len(attacks) > 0 else 0,
                "attack1_percent": attacks[0]["percent_after"] if len(attacks) > 0 else 0,
                "attack2_stars": attacks[1]["stars_after"] if len(attacks) > 1 else 0,
                "attack2_percent": attacks[1]["percent_after"] if len(attacks) > 1 else 0,
            }

        modal = EditAttackModal(self, match, district_num, team_record["id"], team_record["name"], prefill)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="edit-attacker", description="Change the attacker for a specific attack (Admin only).")
    @app_commands.autocomplete(match=active_match_autocomplete, district=district_autocomplete, team=team_autocomplete)
    @app_commands.describe(
        match="The active match ID",
        district="The district name",
        team="The attacking team",
        attack_number="Attack number (1 or 2)",
        new_attacker="The new attacker",
    )
    @is_admin()
    async def edit_attacker(
        self,
        interaction: discord.Interaction,
        match: int,
        district: str,
        team: str,
        attack_number: int,
        new_attacker: discord.Member,
    ):
        await interaction.response.defer(ephemeral=True)

        if attack_number not in (1, 2):
            await interaction.followup.send(embed=error_embed("Invalid Attack Number", "Attack number must be 1 or 2."))
            return

        district_num = _resolve_district(district)
        if district_num is None:
            await interaction.followup.send(embed=error_embed("Invalid District", "District not found."))
            return

        async with connection.pool.acquire() as conn:
            match_record = await conn.fetchrow("SELECT * FROM matches WHERE id = $1", match)
            if not match_record:
                await interaction.followup.send(embed=error_embed("Not Found", f"Match #{match} does not exist."))
                return

            team_record = await conn.fetchrow("SELECT id, name FROM teams WHERE name = $1", team)
            if not team_record:
                await interaction.followup.send(embed=error_embed("Not Found", f"Team '{team}' not found."))
                return

            if team_record["id"] not in (match_record["team1_id"], match_record["team2_id"]):
                await interaction.followup.send(embed=error_embed("Invalid Team", f"Team '{team}' is not part of this match."))
                return

            result = await conn.execute(
                """UPDATE attacks SET attacker_id = $1
                WHERE match_id = $2 AND team_id = $3 AND district = $4 AND attack_num = $5""",
                new_attacker.id, match, team_record["id"], district_num, attack_number
            )

            if result == "UPDATE 0":
                await interaction.followup.send(
                    embed=error_embed("Not Found", f"Attack #{attack_number} not found for **{district}**.")
                )
                return

        await update_player_district_stats(match, team_record["id"], district_num)

        await interaction.followup.send(
            embed=success_embed(
                "Attacker Updated",
                f"Attack #{attack_number} at **{district}** for **{team}** is now assigned to {player_link(new_attacker.id, new_attacker.display_name)}."
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Attacks(bot))
