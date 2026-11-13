"""
Tournament Management Cog - Multi-tournament system

This cog handles:
- Tournament CRUD operations (create, list, info, delete)
- Tournament lifecycle (setup → registration → active → completed)
- Admin assignment and management
- Role and channel creation for tournaments
- Tournament configuration (districts, qualifiers)
"""

import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import logging

import bot.db.connection as connection
from bot.utils.tournament_checks import (
    super_admin_only,
    get_active_tournament,
    get_tournament_by_id,
    get_all_tournaments,
    add_tournament_admin,
    remove_tournament_admin,
    get_tournament_admins,
    NotSuperAdmin,
    TournamentNotFound
)
from bot.utils.embeds import success_embed, error_embed, admin_log_embed
from bot.config import ADMIN_LOG_CHANNEL_ID

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Autocomplete Functions
# ═══════════════════════════════════════════════════════════════════════════

async def tournament_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for tournament selection (all tournaments)."""
    tournaments = await get_all_tournaments()
    choices = []
    for t in tournaments:
        label = f"{t['name']} ({t['initials']}) - {t['status'].title()}"
        if current.lower() in label.lower():
            choices.append(app_commands.Choice(name=label[:100], value=str(t['id'])))
    return choices[:25]


async def member_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for member selection."""
    if not interaction.guild:
        return []
    
    members = []
    for member in interaction.guild.members:
        if member.bot:
            continue
        display = f"{member.display_name} (@{member.name})"
        if current.lower() in display.lower():
            members.append(app_commands.Choice(name=display[:100], value=str(member.id)))
        if len(members) >= 25:
            break
    return members


async def status_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
    """Autocomplete for tournament status."""
    statuses = [
        ("Setup (Initial configuration)", "setup"),
        ("Registration (Teams can register)", "registration"),
        ("Active (Tournament in progress)", "active"),
        ("Completed (Tournament finished)", "completed"),
    ]
    return [
        app_commands.Choice(name=name, value=value)
        for name, value in statuses
        if current.lower() in name.lower()
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Modal for Tournament Creation
# ═══════════════════════════════════════════════════════════════════════════

class TournamentCreateModal(discord.ui.Modal, title="Create Tournament"):
    """Modal for collecting tournament details during creation."""
    
    name = discord.ui.TextInput(
        label="Tournament Name",
        placeholder="e.g., Anshu's Invitational 4",
        max_length=100,
        required=True
    )
    
    initials = discord.ui.TextInput(
        label="Tournament Initials (max 5 chars)",
        placeholder="e.g., AI4, CC1",
        max_length=5,
        required=True
    )
    
    description = discord.ui.TextInput(
        label="Description (optional)",
        placeholder="Brief description of the tournament",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False
    )
    
    host_accounts = discord.ui.TextInput(
        label="Host Accounts (optional, comma-separated)",
        placeholder="e.g., HostAccount1, HostAccount2",
        style=discord.TextStyle.paragraph,
        max_length=200,
        required=False
    )
    
    def __init__(self, cog: "Tournaments"):
        super().__init__()
        self.cog = cog
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Validate initials format
        initials = self.initials.value.strip().upper()
        if not initials.isalnum():
            await interaction.followup.send(
                embed=error_embed("Invalid Initials", "Initials must contain only letters and numbers."),
                ephemeral=True
            )
            return
        
        # Check if initials already exist
        async with connection.pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT COUNT(*) FROM tournaments WHERE LOWER(initials) = LOWER($1)",
                initials
            )
            if existing > 0:
                await interaction.followup.send(
                    embed=error_embed("Duplicate Initials", f"A tournament with initials **{initials}** already exists."),
                    ephemeral=True
                )
                return
        
        try:
            # Create roles
            guild = interaction.guild
            participant_role = await guild.create_role(
                name=f"{initials}-Participant",
                mentionable=True,
                reason=f"Tournament participant role for {self.name.value}"
            )
            
            admin_role = await guild.create_role(
                name=f"{initials}-Admin",
                mentionable=True,
                reason=f"Tournament admin role for {self.name.value}"
            )
            
            # Create team channel category
            category = await guild.create_category(
                name=f"{self.name.value} Teams",
                reason=f"Team channels category for tournament {self.name.value}"
            )
            
            # Insert tournament into database
            async with connection.pool.acquire() as conn:
                tournament_id = await conn.fetchval(
                    """
                    INSERT INTO tournaments 
                    (name, initials, participant_role_id, admin_role_id, team_channel_category_id, 
                     created_by, description, host_accounts, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'setup')
                    RETURNING id
                    """,
                    self.name.value.strip(),
                    initials,
                    participant_role.id,
                    admin_role.id,
                    category.id,
                    interaction.user.id,
                    self.description.value.strip() if self.description.value else None,
                    self.host_accounts.value.strip() if self.host_accounts.value else None
                )
                
                # Add creator as first tournament admin
                await add_tournament_admin(tournament_id, interaction.user.id, interaction.user.id)
            
            # Assign admin role to creator
            member = guild.get_member(interaction.user.id)
            if member:
                await member.add_roles(admin_role)
            
            # Send confirmation
            embed = success_embed(
                "Tournament Created Successfully",
                f"**{self.name.value}** (`{initials}`)\n\n"
                f"✅ Participant Role: {participant_role.mention}\n"
                f"✅ Admin Role: {admin_role.mention}\n"
                f"✅ Team Category: {category.mention}\n"
                f"✅ You have been assigned as the first admin\n\n"
                f"**Next Steps:**\n"
                f"1. Use `/tournament-configure` to set up districts and qualifiers\n"
                f"2. Use `/tournament-add-admin` to assign additional admins\n"
                f"3. Use `/tournament-set-status` to open registration when ready"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Log to admin channel
            if ADMIN_LOG_CHANNEL_ID:
                log_channel = guild.get_channel(ADMIN_LOG_CHANNEL_ID)
                if log_channel:
                    log_embed = admin_log_embed(
                        "Tournament Created",
                        f"**{self.name.value}** (`{initials}`)\n"
                        f"Created by: {interaction.user.mention}\n"
                        f"Status: Setup",
                        color=discord.Color.green()
                    )
                    await log_channel.send(embed=log_embed)
            
            log.info(f"Tournament created: {self.name.value} ({initials}) by {interaction.user.id}")
            
        except Exception as e:
            log.error(f"Error creating tournament: {e}")
            await interaction.followup.send(
                embed=error_embed("Error", f"Failed to create tournament: {e}"),
                ephemeral=True
            )


# ═══════════════════════════════════════════════════════════════════════════
# Modal for Tournament Configuration
# ═══════════════════════════════════════════════════════════════════════════

class TournamentConfigureModal(discord.ui.Modal, title="Configure Tournament"):
    """Modal for configuring tournament districts and qualifiers."""
    
    has_qualifiers = discord.ui.TextInput(
        label="Enable Qualifiers? (yes/no)",
        placeholder="yes or no",
        max_length=3,
        default="yes",
        required=True
    )
    
    enabled_districts = discord.ui.TextInput(
        label="Enabled Districts (comma-separated 0-8)",
        placeholder="e.g., 0,1,2,3,4,5,6,7,8",
        default="0,1,2,3,4,5,6,7,8",
        max_length=30,
        required=True
    )
    
    qualifier_districts = discord.ui.TextInput(
        label="Qualifier Districts (if enabled)",
        placeholder="Barbarian Camp, Wizard Valley, etc.",
        style=discord.TextStyle.paragraph,
        default="Barbarian Camp, Wizard Valley, Balloon Lagoon, Builder's Workshop, Dragon Cliffs, Golem Quarry",
        max_length=300,
        required=False
    )
    
    def __init__(self, cog: "Tournaments", tournament_id: int, tournament_name: str):
        super().__init__()
        self.cog = cog
        self.tournament_id = tournament_id
        self.tournament_name = tournament_name
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Parse has_qualifiers
            has_qual = self.has_qualifiers.value.strip().lower() in ('yes', 'y', 'true', '1')
            
            # Parse enabled districts
            districts_str = self.enabled_districts.value.strip()
            enabled_districts = []
            for d in districts_str.split(','):
                d = d.strip()
                if d.isdigit() and 0 <= int(d) <= 8:
                    enabled_districts.append(int(d))
            
            if not enabled_districts:
                await interaction.followup.send(
                    embed=error_embed("Invalid Districts", "Please provide valid district numbers (0-8)."),
                    ephemeral=True
                )
                return
            
            # Parse qualifier districts
            qualifier_districts = []
            if has_qual and self.qualifier_districts.value.strip():
                qualifier_districts = [d.strip() for d in self.qualifier_districts.value.split(',') if d.strip()]
            
            # Update database
            async with connection.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE tournaments
                    SET has_qualifiers = $1, enabled_districts = $2, qualifier_districts = $3
                    WHERE id = $4
                    """,
                    has_qual,
                    enabled_districts,
                    qualifier_districts if qualifier_districts else None,
                    self.tournament_id
                )
            
            embed = success_embed(
                "Tournament Configured",
                f"**{self.tournament_name}**\n\n"
                f"Qualifiers: {'✅ Enabled' if has_qual else '❌ Disabled'}\n"
                f"Enabled Districts: {', '.join(map(str, enabled_districts))}\n"
                f"Qualifier Districts: {len(qualifier_districts) if qualifier_districts else 0}"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            log.info(f"Tournament configured: {self.tournament_name} (ID: {self.tournament_id})")
            
        except Exception as e:
            log.error(f"Error configuring tournament: {e}")
            await interaction.followup.send(
                embed=error_embed("Error", f"Failed to configure tournament: {e}"),
                ephemeral=True
            )


# ═══════════════════════════════════════════════════════════════════════════
# Tournaments Cog
# ═══════════════════════════════════════════════════════════════════════════

class Tournaments(commands.Cog):
    """Tournament management commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # ──────────────────────────────────────────────────────────────────────
    # SUPER ADMIN COMMANDS
    # ──────────────────────────────────────────────────────────────────────
    
    @app_commands.command(name="tournament-create", description="[Super Admin] Create a new tournament")
    @super_admin_only()
    async def tournament_create(self, interaction: discord.Interaction):
        """Create a new tournament with roles and channels."""
        modal = TournamentCreateModal(self)
        await interaction.response.send_modal(modal)
    
    @app_commands.command(name="tournament-configure", description="[Super Admin] Configure tournament districts and qualifiers")
    @app_commands.autocomplete(tournament=tournament_autocomplete)
    @super_admin_only()
    async def tournament_configure(self, interaction: discord.Interaction, tournament: str):
        """Configure which districts are enabled and whether qualifiers are used."""
        tournament_id = int(tournament)
        t = await get_tournament_by_id(tournament_id)
        
        if not t:
            await interaction.response.send_message(
                embed=error_embed("Not Found", "Tournament not found."),
                ephemeral=True
            )
            return
        
        modal = TournamentConfigureModal(self, tournament_id, t['name'])
        await interaction.response.send_modal(modal)
    
    @app_commands.command(name="tournament-set-status", description="[Super Admin] Change tournament status")
    @app_commands.autocomplete(tournament=tournament_autocomplete, status=status_autocomplete)
    @super_admin_only()
    async def tournament_set_status(
        self,
        interaction: discord.Interaction,
        tournament: str,
        status: str
    ):
        """
        Change tournament status.
        
        Status flow: setup → registration → active → completed
        
        Only one tournament can be 'active' at a time.
        """
        await interaction.response.defer(ephemeral=True)
        
        tournament_id = int(tournament)
        t = await get_tournament_by_id(tournament_id)
        
        if not t:
            await interaction.followup.send(
                embed=error_embed("Not Found", "Tournament not found."),
                ephemeral=True
            )
            return
        
        # Validate status
        if status not in ('setup', 'registration', 'active', 'completed'):
            await interaction.followup.send(
                embed=error_embed("Invalid Status", "Status must be: setup, registration, active, or completed."),
                ephemeral=True
            )
            return
        
        try:
            async with connection.pool.acquire() as conn:
                # If setting to 'active', ensure no other tournament is active
                if status == 'active':
                    active_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM tournaments WHERE status = 'active' AND id != $1",
                        tournament_id
                    )
                    if active_count > 0:
                        await interaction.followup.send(
                            embed=error_embed(
                                "Conflict",
                                "Another tournament is already active. Complete or deactivate it first."
                            ),
                            ephemeral=True
                        )
                        return
                
                # Update status
                await conn.execute(
                    "UPDATE tournaments SET status = $1 WHERE id = $2",
                    status,
                    tournament_id
                )
            
            embed = success_embed(
                "Status Updated",
                f"**{t['name']}** status changed to: **{status.title()}**"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Log to admin channel
            if ADMIN_LOG_CHANNEL_ID:
                log_channel = interaction.guild.get_channel(ADMIN_LOG_CHANNEL_ID)
                if log_channel:
                    log_embed = admin_log_embed(
                        "Tournament Status Changed",
                        f"**{t['name']}** (`{t['initials']}`)\n"
                        f"New Status: **{status.title()}**\n"
                        f"Changed by: {interaction.user.mention}",
                        color=discord.Color.blue()
                    )
                    await log_channel.send(embed=log_embed)
            
            log.info(f"Tournament {t['name']} status changed to {status} by {interaction.user.id}")
            
        except Exception as e:
            log.error(f"Error updating tournament status: {e}")
            await interaction.followup.send(
                embed=error_embed("Error", f"Failed to update status: {e}"),
                ephemeral=True
            )
    
    @app_commands.command(name="tournament-add-admin", description="[Super Admin] Add an admin to a tournament")
    @app_commands.autocomplete(tournament=tournament_autocomplete, admin=member_autocomplete)
    @super_admin_only()
    async def tournament_add_admin(
        self,
        interaction: discord.Interaction,
        tournament: str,
        admin: str
    ):
        """Assign a user as admin for a tournament."""
        await interaction.response.defer(ephemeral=True)
        
        tournament_id = int(tournament)
        admin_id = int(admin)
        
        t = await get_tournament_by_id(tournament_id)
        if not t:
            await interaction.followup.send(
                embed=error_embed("Not Found", "Tournament not found."),
                ephemeral=True
            )
            return
        
        admin_member = interaction.guild.get_member(admin_id)
        if not admin_member:
            await interaction.followup.send(
                embed=error_embed("Not Found", "Member not found in this server."),
                ephemeral=True
            )
            return
        
        # Add to database
        success = await add_tournament_admin(tournament_id, admin_id, interaction.user.id)
        
        if not success:
            await interaction.followup.send(
                embed=error_embed("Already Admin", f"{admin_member.mention} is already an admin of **{t['name']}**."),
                ephemeral=True
            )
            return
        
        # Assign admin role
        if t['admin_role_id']:
            admin_role = interaction.guild.get_role(t['admin_role_id'])
            if admin_role:
                await admin_member.add_roles(admin_role)
        
        embed = success_embed(
            "Admin Added",
            f"{admin_member.mention} is now an admin of **{t['name']}**."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        # Log to admin channel
        if ADMIN_LOG_CHANNEL_ID:
            log_channel = interaction.guild.get_channel(ADMIN_LOG_CHANNEL_ID)
            if log_channel:
                log_embed = admin_log_embed(
                    "Tournament Admin Added",
                    f"**{t['name']}** (`{t['initials']}`)\n"
                    f"New Admin: {admin_member.mention}\n"
                    f"Added by: {interaction.user.mention}",
                    color=discord.Color.green()
                )
                await log_channel.send(embed=log_embed)
        
        log.info(f"Admin {admin_id} added to tournament {t['name']} by {interaction.user.id}")
    
    @app_commands.command(name="tournament-remove-admin", description="[Super Admin] Remove an admin from a tournament")
    @app_commands.autocomplete(tournament=tournament_autocomplete, admin=member_autocomplete)
    @super_admin_only()
    async def tournament_remove_admin(
        self,
        interaction: discord.Interaction,
        tournament: str,
        admin: str
    ):
        """Remove a user from tournament admins."""
        await interaction.response.defer(ephemeral=True)
        
        tournament_id = int(tournament)
        admin_id = int(admin)
        
        t = await get_tournament_by_id(tournament_id)
        if not t:
            await interaction.followup.send(
                embed=error_embed("Not Found", "Tournament not found."),
                ephemeral=True
            )
            return
        
        admin_member = interaction.guild.get_member(admin_id)
        
        # Remove from database
        success = await remove_tournament_admin(tournament_id, admin_id)
        
        if not success:
            await interaction.followup.send(
                embed=error_embed("Not Admin", f"User is not an admin of **{t['name']}**."),
                ephemeral=True
            )
            return
        
        # Remove admin role
        if admin_member and t['admin_role_id']:
            admin_role = interaction.guild.get_role(t['admin_role_id'])
            if admin_role and admin_role in admin_member.roles:
                await admin_member.remove_roles(admin_role)
        
        member_mention = admin_member.mention if admin_member else f"<@{admin_id}>"
        embed = success_embed(
            "Admin Removed",
            f"{member_mention} is no longer an admin of **{t['name']}**."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        log.info(f"Admin {admin_id} removed from tournament {t['name']} by {interaction.user.id}")
    
    @app_commands.command(name="tournament-delete", description="[Super Admin] Delete a tournament (CAREFUL!)")
    @app_commands.autocomplete(tournament=tournament_autocomplete)
    @super_admin_only()
    async def tournament_delete(self, interaction: discord.Interaction, tournament: str, confirm: bool = False):
        """
        Delete a tournament and all associated data.
        
        WARNING: This will CASCADE delete all teams, matches, qualifier scores, etc.
        """
        await interaction.response.defer(ephemeral=True)
        
        tournament_id = int(tournament)
        t = await get_tournament_by_id(tournament_id)
        
        if not t:
            await interaction.followup.send(
                embed=error_embed("Not Found", "Tournament not found."),
                ephemeral=True
            )
            return
        
        if not confirm:
            await interaction.followup.send(
                embed=error_embed(
                    "Confirmation Required",
                    f"⚠️ This will permanently delete **{t['name']}** and ALL associated data (teams, matches, scores).\n\n"
                    f"To confirm, run the command again with `confirm: True`"
                ),
                ephemeral=True
            )
            return
        
        try:
            # Delete from database (cascades to all related data)
            async with connection.pool.acquire() as conn:
                await conn.execute("DELETE FROM tournaments WHERE id = $1", tournament_id)
            
            # Clean up Discord resources (roles, channels)
            guild = interaction.guild
            
            if t['participant_role_id']:
                role = guild.get_role(t['participant_role_id'])
                if role:
                    await role.delete(reason=f"Tournament {t['name']} deleted")
            
            if t['admin_role_id']:
                role = guild.get_role(t['admin_role_id'])
                if role:
                    await role.delete(reason=f"Tournament {t['name']} deleted")
            
            if t['team_channel_category_id']:
                category = guild.get_channel(t['team_channel_category_id'])
                if category:
                    # Delete all channels in category
                    for channel in category.channels:
                        await channel.delete(reason=f"Tournament {t['name']} deleted")
                    await category.delete(reason=f"Tournament {t['name']} deleted")
            
            embed = success_embed(
                "Tournament Deleted",
                f"**{t['name']}** and all associated data has been permanently deleted."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            log.info(f"Tournament {t['name']} deleted by {interaction.user.id}")
            
        except Exception as e:
            log.error(f"Error deleting tournament: {e}")
            await interaction.followup.send(
                embed=error_embed("Error", f"Failed to delete tournament: {e}"),
                ephemeral=True
            )
    
    # ──────────────────────────────────────────────────────────────────────
    # PUBLIC COMMANDS
    # ──────────────────────────────────────────────────────────────────────
    
    @app_commands.command(name="tournament-list", description="View all tournaments")
    async def tournament_list(self, interaction: discord.Interaction):
        """Display a list of all tournaments with their status."""
        await interaction.response.defer(ephemeral=False)
        
        tournaments = await get_all_tournaments()
        
        if not tournaments:
            await interaction.followup.send(
                embed=error_embed("No Tournaments", "No tournaments have been created yet."),
                ephemeral=True
            )
            return
        
        # Group by status
        by_status = {'active': [], 'registration': [], 'setup': [], 'completed': []}
        for t in tournaments:
            by_status[t['status']].append(t)
        
        description_parts = []
        
        # Active tournaments
        if by_status['active']:
            description_parts.append("**🏆 Active Tournaments**")
            for t in by_status['active']:
                description_parts.append(f"• **{t['name']}** (`{t['initials']}`)")
        
        # Registration open
        if by_status['registration']:
            description_parts.append("\n**📝 Registration Open**")
            for t in by_status['registration']:
                description_parts.append(f"• **{t['name']}** (`{t['initials']}`)")
        
        # Setup phase
        if by_status['setup']:
            description_parts.append("\n**⚙️ In Setup**")
            for t in by_status['setup']:
                description_parts.append(f"• **{t['name']}** (`{t['initials']}`)")
        
        # Completed
        if by_status['completed']:
            description_parts.append("\n**✅ Completed**")
            for t in by_status['completed'][:5]:  # Show only last 5 completed
                description_parts.append(f"• **{t['name']}** (`{t['initials']}`)")
            if len(by_status['completed']) > 5:
                description_parts.append(f"... and {len(by_status['completed']) - 5} more")
        
        embed = discord.Embed(
            title="📋 Tournaments",
            description="\n".join(description_parts),
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Total: {len(tournaments)} tournaments")
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="tournament-info", description="View details about a tournament")
    @app_commands.autocomplete(tournament=tournament_autocomplete)
    async def tournament_info(self, interaction: discord.Interaction, tournament: str):
        """Display detailed information about a specific tournament."""
        await interaction.response.defer(ephemeral=False)
        
        tournament_id = int(tournament)
        t = await get_tournament_by_id(tournament_id)
        
        if not t:
            await interaction.followup.send(
                embed=error_embed("Not Found", "Tournament not found."),
                ephemeral=True
            )
            return
        
        # Get team and match counts
        async with connection.pool.acquire() as conn:
            team_count = await conn.fetchval(
                "SELECT COUNT(*) FROM teams WHERE tournament_id = $1", tournament_id
            )
            match_count = await conn.fetchval(
                "SELECT COUNT(*) FROM matches WHERE tournament_id = $1", tournament_id
            )
        
        # Get admin list
        admin_ids = await get_tournament_admins(tournament_id)
        admin_mentions = [f"<@{uid}>" for uid in admin_ids[:10]]  # Show max 10
        admin_text = ", ".join(admin_mentions) if admin_mentions else "None"
        if len(admin_ids) > 10:
            admin_text += f" +{len(admin_ids) - 10} more"
        
        # Build description
        description_parts = [
            f"**Initials:** `{t['initials']}`",
            f"**Status:** {t['status'].title()}",
            f"**Teams:** {team_count}",
            f"**Matches:** {match_count}",
            f"**Qualifiers:** {'✅ Enabled' if t['has_qualifiers'] else '❌ Disabled'}",
        ]
        
        if t['description']:
            description_parts.append(f"\n**Description:**\n{t['description']}")
        
        if t['enabled_districts']:
            districts_str = ", ".join(map(str, sorted(t['enabled_districts'])))
            description_parts.append(f"\n**Enabled Districts:** {districts_str}")
        
        if t['host_accounts']:
            description_parts.append(f"\n**Host Accounts:** {t['host_accounts']}")
        
        description_parts.append(f"\n**Admins:**\n{admin_text}")
        
        embed = discord.Embed(
            title=f"🏆 {t['name']}",
            description="\n".join(description_parts),
            color=discord.Color.gold()
        )
        
        if t['logo_url']:
            embed.set_thumbnail(url=t['logo_url'])
        
        created_date = t['created_at'].strftime("%B %d, %Y") if t['created_at'] else "Unknown"
        embed.set_footer(text=f"Created: {created_date}")
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="tournament-current", description="Show info about the active tournament")
    async def tournament_current(self, interaction: discord.Interaction):
        """Display information about the currently active tournament."""
        await interaction.response.defer(ephemeral=False)
        
        tournament = await get_active_tournament()
        
        if not tournament:
            await interaction.followup.send(
                embed=error_embed("No Active Tournament", "There is no active tournament right now."),
                ephemeral=True
            )
            return
        
        # Reuse tournament-info logic
        await self.tournament_info.callback(self, interaction, str(tournament['id']))
    
    @app_commands.command(name="tournament-admins", description="View admins for a tournament")
    @app_commands.autocomplete(tournament=tournament_autocomplete)
    async def tournament_admins(self, interaction: discord.Interaction, tournament: str):
        """Display all admins for a specific tournament."""
        await interaction.response.defer(ephemeral=False)
        
        tournament_id = int(tournament)
        t = await get_tournament_by_id(tournament_id)
        
        if not t:
            await interaction.followup.send(
                embed=error_embed("Not Found", "Tournament not found."),
                ephemeral=True
            )
            return
        
        admin_ids = await get_tournament_admins(tournament_id)
        
        if not admin_ids:
            await interaction.followup.send(
                embed=error_embed("No Admins", f"**{t['name']}** has no assigned admins."),
                ephemeral=True
            )
            return
        
        admin_mentions = [f"<@{uid}>" for uid in admin_ids]
        
        embed = discord.Embed(
            title=f"👥 Admins for {t['name']}",
            description="\n".join(f"{i+1}. {mention}" for i, mention in enumerate(admin_mentions)),
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Total: {len(admin_ids)} admins")
        
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tournaments(bot))
