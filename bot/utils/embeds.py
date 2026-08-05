import discord
from datetime import datetime, timezone

FOOTER = "Anshu's Invitational 3"


# ── Generic ───────────────────────────────────────────────────────────────────

def success_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=discord.Color.green())
    embed.set_footer(text=FOOTER)
    return embed


def error_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=discord.Color.red())
    embed.set_footer(text=FOOTER)
    return embed


def admin_log_embed(title: str, description: str, color: discord.Color = discord.Color.blue()) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=FOOTER)
    return embed


# ── Bases ─────────────────────────────────────────────────────────────────────

def base_card_embed(team_name: str, district_name: str, link: str, screenshot_url: str, *, is_admin: bool = False) -> discord.Embed:
    """Single base card shown in /view-bases."""
    color = discord.Color.gold() if is_admin else discord.Color.blue()
    embed = discord.Embed(
        title=f"{team_name} — {district_name}",
        description=f"[Base Link](<{link}>)",
        color=color,
    )
    embed.set_image(url=screenshot_url)
    embed.set_footer(text=FOOTER)
    return embed


def base_status_embed(team_name: str, match_id: int, status_lines: list[str], count: int) -> discord.Embed:
    """Checklist shown in /base-status."""
    color = discord.Color.green() if count == 9 else discord.Color.orange()
    embed = discord.Embed(
        title=f"Base Submission Status — {team_name}",
        description=f"**Match #{match_id}**\n\n" + "\n".join(status_lines) + f"\n\n**{count}/9 Districts Submitted**",
        color=color,
    )
    embed.set_footer(text=FOOTER)
    return embed


def send_bases_summary_embed(team_name: str, match_id: int) -> discord.Embed:
    """Header embed for /send-bases."""
    embed = discord.Embed(
        title=f"🗺️ {team_name} — Base Screenshots (Match #{match_id})",
        description="Here are the submitted base screenshots:",
        color=discord.Color.orange(),
    )
    embed.set_footer(text=FOOTER)
    return embed


def send_bases_card_embed(district_name: str, screenshot_url: str) -> discord.Embed:
    """Per-district card for /send-bases."""
    embed = discord.Embed(
        title=district_name,
        description=f"[View Base]({screenshot_url})",
        color=discord.Color.blue(),
    )
    embed.set_image(url=screenshot_url)
    embed.set_footer(text=FOOTER)
    return embed


def remind_bases_embed(match_id: int, missing_lines: list[str]) -> discord.Embed:
    """Warning embed sent to team channel by /remind-bases."""
    embed = discord.Embed(
        title="⚠️ Base Submission Reminder",
        description=f"**Match #{match_id}**\n\nMissing bases for:\n" + "\n".join(missing_lines) + "\n\n**Please submit these bases ASAP!**",
        color=discord.Color.red(),
    )
    embed.set_footer(text=FOOTER)
    return embed


# ── Teams ─────────────────────────────────────────────────────────────────────

def account_info_embed() -> discord.Embed:
    """Pinned account-info message sent to new team channels."""
    embed = discord.Embed(
        title="📌 AI-3 Tournament — Account Information",
        description=(
            "For the accounts used for the AI-3 Tournament:\n\n"
            "You can use the accounts made for AI-2, but you will need to send a friend request to both host accounts below.\n\n"
            "**Host Accounts:**\n"
            "> [Ai3-ch9 host](<https://link.clashofclans.com/nl?action=OpenPlayerProfile&tag=RP9CY2229>)\n"
            "> [Ai3-ch10 host](<https://link.clashofclans.com/nl?action=OpenPlayerProfile&tag=R2R82PPRV>)\n\n"
            "If you do not have an account, you have **2 options:**\n\n"
            "**Option 1** — Make your own account and use our email to log in. "
            "You will still need to send a friend request to both host accounts.\n\n"
            "**Option 2** — We can make an account for you."
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text=FOOTER)
    return embed


def team_announce_embed(team_name: str, logo_url: str) -> discord.Embed:
    """Public announcement embed for /announce-team."""
    embed = discord.Embed(
        title=f"Welcome {team_name} to Anshu's Invitational 3!",
        color=discord.Color.gold(),
    )
    embed.set_image(url=logo_url)
    embed.set_footer(text=FOOTER)
    return embed


def teams_list_embed(teams: list) -> discord.Embed:
    """Approved teams list for /teams-list."""
    embed = discord.Embed(
        title="🏆 Approved Teams",
        description=f"Total: **{len(teams)}** teams",
        color=discord.Color.blue(),
    )
    team_lines = [f"• **{t['name']}**" for t in teams]
    embed.add_field(name="Teams", value="\n".join(team_lines), inline=False)
    embed.set_footer(text=FOOTER)
    return embed


def team_info_embed(team: dict, member_lines: list[str], active_matches: list, completed_matches: list, completed_match_scores: dict) -> discord.Embed:
    """Detailed team info card for /team-info. member_lines are pre-formatted strings."""
    embed = discord.Embed(
        title=f"📋 {team['name']}",
        color=discord.Color.gold() if team['is_approved'] else discord.Color.greyple(),
    )

    if team['logo_url']:
        embed.set_thumbnail(url=team['logo_url'])

    # Members (pre-built lines passed in from cog)
    embed.add_field(
        name=f"Members ({len(member_lines)})",
        value="\n".join(member_lines) if member_lines else "No members",
        inline=False,
    )

    # Status & created
    embed.add_field(name="Status", value="✅ Approved" if team['is_approved'] else "⏳ Pending Approval", inline=True)
    if team['created_at']:
        embed.add_field(name="Created", value=f"<t:{int(team['created_at'].timestamp())}:R>", inline=True)

    # Upcoming matches
    if active_matches:
        match_lines = []
        for match in active_matches:
            status_emoji = "🟢" if match['status'] == 'active' else "🟡" if match['status'] == 'scheduled' else "⚪"
            line = f"{status_emoji} Match #{match['id']}: {match['t1']} vs {match['t2']}"
            if match['status'] == 'scheduled' and match['scheduled_time']:
                line += f" • <t:{int(match['scheduled_time'].timestamp())}:R>"
            elif match['status'] == 'active':
                line += " • In Progress"
            match_lines.append(line)
        embed.add_field(name=f"Upcoming Matches ({len(active_matches)})", value="\n".join(match_lines), inline=False)

    # Completed matches
    if completed_matches:
        match_lines = []
        for match in completed_matches:
            score_dict = completed_match_scores.get(match['id'], {})
            t1_stars, t1_pct = score_dict.get(match['team1_id'], (0, 0))
            t2_stars, t2_pct = score_dict.get(match['team2_id'], (0, 0))
            if t1_stars > t2_stars:
                winner = match['t1']
            elif t2_stars > t1_stars:
                winner = match['t2']
            else:
                winner = "Tie"
            match_lines.append(
                f"🏁 Match #{match['id']}: {match['t1']} vs {match['t2']}\n"
                f"   Score: {t1_stars}⭐ {t1_pct}% - {t2_stars}⭐ {t2_pct}% • Winner: **{winner}**"
            )
        embed.add_field(name=f"Completed Matches ({len(completed_matches)})", value="\n".join(match_lines), inline=False)

    embed.set_footer(text=FOOTER)
    return embed


# ── Matches ───────────────────────────────────────────────────────────────────

def upcoming_matches_embed(rows: list) -> discord.Embed:
    """Upcoming matches list for /matches."""
    embed = discord.Embed(title="📅 Upcoming Matches", color=discord.Color.blue())
    for m in rows:
        if m['status'] == 'scheduled' and m['scheduled_time']:
            time_str = f"🟡 Scheduled — <t:{int(m['scheduled_time'].timestamp())}:F>"
        else:
            time_str = "🕐 Not yet scheduled"
        embed.add_field(
            name=f"Match #{m['id']}: {m['team1_name']} vs {m['team2_name']}",
            value=time_str,
            inline=False,
        )
    embed.set_footer(text=FOOTER)
    return embed


# ── Help ──────────────────────────────────────────────────────────────────────

def get_overview_embed(is_admin: bool, is_participant: bool) -> discord.Embed:
    """Overview embed shown when /help is first called."""
    role_name = "Admin" if is_admin else "Participant" if is_participant else "Public"
    color = discord.Color.red() if is_admin else discord.Color.green() if is_participant else discord.Color.blurple()
    
    embed = discord.Embed(
        title=f"� Command Reference - {role_name}",
        description="Select a category from the dropdown below to view available commands.",
        color=color,
    )
    
    if is_admin:
        categories = "👥 Team Management\n⚔️ Match Management\n🗺️ Base Management\n⚔️ Attack Management\n📊 Statistics\n🎯 Qualifier\n🔧 Utility"
    elif is_participant:
        categories = "👥 Team Commands\n🗺️ Base Commands\n🌐 General Commands\n📊 Statistics\n🎯 Qualifier"
    else:
        categories = "👥 Team Commands\n📅 Match Commands\n📊 Statistics\n🎯 Qualifier\n🌐 Utility"
    
    embed.add_field(name="Available Categories", value=categories, inline=False)
    embed.set_footer(text=FOOTER)
    return embed


def get_team_management_embed(is_admin: bool) -> discord.Embed:
    """Team management commands."""
    embed = discord.Embed(
        title="👥 Team Management Commands",
        color=discord.Color.red() if is_admin else discord.Color.green(),
    )
    
    if is_admin:
        embed.description = (
            "`/create-team` - Register a new team with 3-5 members\n"
            "`/approve-team` - Approve a team and create their private channel\n"
            "`/announce-team` - Post a team announcement (requires logo)\n"
            "`/add-logo` - Upload a logo for your team (Leader only)\n"
            "`/admin-add-logo` - Upload or replace a logo for any team\n"
            "`/edit-team` - Change a team's name or full roster\n"
            "`/delete-team` - Delete a team and remove their role\n"
            "`/set-coleader` - Give a team member co-leader permissions\n"
            "`/set-player-timezone` - Store a player's UTC offset\n"
            "`/teams-list` - View all approved teams\n"
            "`/team-info` - View detailed information about a team\n"
            "`/refresh-all-announcements` - Update logo URLs in all announcements"
        )
    else:
        embed.add_field(
            name="Leader/Co-Leader Commands",
            value=(
                "`/add-logo` - Upload a logo for your team\n"
                "`/set-player-timezone` - Store a player's UTC offset"
            ),
            inline=False,
        )
        embed.add_field(
            name="Everyone",
            value=(
                "`/create-team` - Register a new team (if not on one)\n"
                "`/teams-list` - View all approved teams\n"
                "`/team-info` - View detailed information about a team"
            ),
            inline=False,
        )
    
    embed.set_footer(text=FOOTER)
    return embed


def get_match_management_embed() -> discord.Embed:
    """Match management commands (Admin only)."""
    embed = discord.Embed(
        title="⚔️ Match Management Commands",
        description=(
            "`/set-match` - Create a new match between two teams\n"
            "`/schedule-match` - Set the match time and mark as scheduled\n"
            "`/start-match` - Start a match and post the live embed\n"
            "`/end-match` - End a match and move to archive\n"
            "`/delete-match` - Delete a match completely\n"
            "`/clear-data` - Wipe all match data (testing only)\n"
            "`/matches` - View all upcoming matches\n"
            "`/match-timezones` - Render player UTC offsets for a match"
        ),
        color=discord.Color.red(),
    )
    embed.set_footer(text=FOOTER)
    return embed


def get_base_management_embed(is_admin: bool) -> discord.Embed:
    """Base management commands."""
    embed = discord.Embed(
        title="🗺️ Base Management Commands",
        color=discord.Color.red() if is_admin else discord.Color.green(),
    )
    
    if is_admin:
        embed.description = (
            "`/submit-base` - Submit a district base (auto-detects district)\n"
            "`/view-bases` - View any team's submitted bases (specify team)\n"
            "`/send-bases` - Publicly post a team's base screenshots\n"
            "`/base-status` - Check base submission status (all matches)\n"
            "`/remind-bases` - Ping a team about missing bases\n"
            "`/reset-base-reminder` - Reset automatic reminder status for a match"
        )
    else:
        embed.add_field(
            name="Leader/Co-Leader Commands",
            value="`/submit-base` - Submit a district base (auto-detects district)",
            inline=False,
        )
        embed.add_field(
            name="All Team Members",
            value=(
                "`/view-bases` - View your team's submitted bases\n"
                "`/base-status` - Check which bases your team has submitted"
            ),
            inline=False,
        )
    
    embed.set_footer(text=FOOTER)
    return embed


def get_attack_management_embed() -> discord.Embed:
    """Attack management commands (Admin only)."""
    embed = discord.Embed(
        title="⚔️ Attack Management Commands",
        description=(
            "`/log-attack` - Log both attacks for a district\n"
            "`/edit-attack` - Edit attack stars and percent\n"
            "`/edit-attacker` - Change the attacker for a specific attack"
        ),
        color=discord.Color.red(),
    )
    embed.set_footer(text=FOOTER)
    return embed


def get_statistics_embed() -> discord.Embed:
    """Statistics commands (available to everyone)."""
    embed = discord.Embed(
        title="📊 Statistics Commands",
        description=(
            "`/district-stat-team` - Team rankings for a specific district\n"
            "`/district-stat-player` - Player rankings for a specific district\n"
            "`/district-stat-log` - Score history after 2nd attack for a district\n"
            "`/tournament-stat` - Average scores across all districts\n"
            "`/player-stat-log` - Full attack log for a player\n"
            "`/player-stat` - Per-district summary for a player\n"
            "`/team-stat-log` - Full attack log for a team\n"
            "`/team-stat` - Per-district summary for a team\n"
            "`/match-stat` - District breakdown for a completed match\n"
            "`/relative-lb-player` - Normalized player leaderboard\n"
            "`/relative-lb-team` - Normalized team leaderboard"
        ),
        color=discord.Color.blue(),
    )
    embed.set_footer(text=FOOTER)
    return embed


def get_qualifier_embed(is_admin: bool) -> discord.Embed:
    """Qualifier commands."""
    embed = discord.Embed(
        title="🎯 Qualifier Commands",
        color=discord.Color.red() if is_admin else discord.Color.gold(),
    )
    
    if is_admin:
        embed.description = (
            "`/qualifier-submit` - Submit qualifier scores for a team\n"
            "`/qualifier-lb` - Qualifier leaderboard (ranked by total score)\n"
            "`/qualifier-team-info` - Team roster and per-district qualifier scores\n"
            "`/qualifier-district-lb` - Rankings for a specific qualifier district\n"
            "`/qualifier-toggle-public` - Toggle qualifier commands public/admin-only"
        )
    else:
        embed.description = (
            "`/qualifier-lb` - Qualifier leaderboard (ranked by total score)\n"
            "`/qualifier-team-info` - Team roster and qualifier scores\n"
            "`/qualifier-district-lb` - Rankings for a qualifier district"
        )
    
    embed.set_footer(text=FOOTER)
    return embed


def get_utility_embed(is_admin: bool) -> discord.Embed:
    """Utility commands."""
    embed = discord.Embed(
        title="🔧 Utility Commands" if is_admin else "🌐 Utility Commands",
        color=discord.Color.red() if is_admin else discord.Color.blurple(),
    )
    
    if is_admin:
        embed.description = (
            "`/help` - Show this command reference\n"
            "`/create-anti-bot-channel` - Create a honeypot channel for scam bots"
        )
    else:
        embed.description = "`/help` - Show this command reference"
    
    embed.set_footer(text=FOOTER)
    return embed


def get_general_commands_embed() -> discord.Embed:
    """General commands for participants."""
    embed = discord.Embed(
        title="🌐 General Commands",
        description=(
            "`/create-team` - Register a new team (if not on one)\n"
            "`/teams-list` - View all approved teams\n"
            "`/team-info` - View detailed information about a team\n"
            "`/matches` - View all upcoming matches\n"
            "`/match-timezones` - Render player UTC offsets for a match\n"
            "`/help` - Show this command reference"
        ),
        color=discord.Color.green(),
    )
    embed.set_footer(text=FOOTER)
    return embed


def get_match_commands_embed() -> discord.Embed:
    """Match commands for public users."""
    embed = discord.Embed(
        title="📅 Match Commands",
        description="`/matches` - View all upcoming matches",
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=FOOTER)
    return embed
