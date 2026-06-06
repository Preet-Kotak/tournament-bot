import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional

import bot.db.connection as connection
from bot.utils.checks import is_admin, is_team_leader_or_admin
from bot.utils.embeds import success_embed, error_embed, admin_log_embed
from bot.config import (
    PARTICIPANT_ROLE_ID,
    ADMIN_LOG_CHANNEL_ID,
    APPROVE_ANNOUNCE_CHANNEL_ID,
    TEAM_CHANNEL_CATEGORY_ID
)

log = logging.getLogger(__name__)

class ApproveTeamView(discord.ui.View):
    def __init__(self, cog: 'Teams', team_name: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.team_name = team_name

    @discord.ui.button(label="Approve Team", style=discord.ButtonStyle.success, custom_id="dynamic_approve_btn")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from bot.config import ADMIN_IDS
        if interaction.user.id not in ADMIN_IDS:
            await interaction.response.send_message("Only admins can use this button.", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=True)
        button.disabled = True
        await interaction.message.edit(view=self)
        
        await self.cog.process_team_approval(interaction, self.team_name)

class Teams(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="create-team", description="Register a new team for the tournament.")
    async def create_team(
        self,
        interaction: discord.Interaction,
        name: str,
        member1: discord.Member,
        member2: discord.Member,
        member3: discord.Member,
        member4: Optional[discord.Member] = None,
        member5: Optional[discord.Member] = None
    ):
        await interaction.response.defer(ephemeral=True)
        
        members = [m for m in [member1, member2, member3, member4, member5] if m is not None]
        
        # Check uniqueness of members
        if len(set(m.id for m in members)) != len(members):
            await interaction.followup.send(embed=error_embed("Duplicate Members", "You provided the same member multiple times."))
            return

        async with connection.pool.acquire() as conn:
            # Check if name exists
            existing_team = await conn.fetchrow("SELECT id FROM teams WHERE name = $1", name)
            if existing_team:
                await interaction.followup.send(embed=error_embed("Team Exists", f"The team name '{name}' is already taken."))
                return

            # Check if any member is already in an approved team
            member_ids = [m.id for m in members]
            in_team_records = await conn.fetch(
                """
                SELECT tm.user_id, t.name 
                FROM team_members tm
                JOIN teams t ON tm.team_id = t.id
                WHERE tm.user_id = ANY($1::bigint[]) AND t.is_approved = TRUE
                """,
                member_ids
            )
            if in_team_records:
                taken_users = ", ".join([f"<@{r['user_id']}> ({r['name']})" for r in in_team_records])
                await interaction.followup.send(embed=error_embed("Members Already in Teams", f"The following members are already in approved teams: {taken_users}"))
                return
                
            try:
                # Create Discord Role
                guild = interaction.guild
                team_role = await guild.create_role(name=name, reason=f"Team creation for {name}")
                
                # Assign Participant and Team Roles
                participant_role = guild.get_role(PARTICIPANT_ROLE_ID)
                for member in members:
                    roles_to_add = [team_role]
                    if participant_role and participant_role not in member.roles:
                        roles_to_add.append(participant_role)
                    try:
                        await member.add_roles(*roles_to_add)
                    except discord.Forbidden:
                        log.warning(f"Failed to add roles to {member.name}")

                # DB Insertion
                async with conn.transaction():
                    team_id = await conn.fetchval(
                        "INSERT INTO teams (name, team_role_id) VALUES ($1, $2) RETURNING id",
                        name, team_role.id
                    )
                    
                    # Insert members
                    member_records = []
                    for i, m in enumerate(members):
                        role = "leader" if i == 0 else "member"
                        member_records.append((team_id, m.id, role))
                        
                    await conn.copy_records_to_table(
                        'team_members',
                        columns=['team_id', 'user_id', 'role'],
                        records=member_records
                    )

                # Send Admin Log
                if ADMIN_LOG_CHANNEL_ID:
                    log_channel = guild.get_channel(ADMIN_LOG_CHANNEL_ID)
                    if log_channel:
                        member_tags = ", ".join([m.mention for m in members])
                        embed = admin_log_embed(
                            "New Team Registered",
                            f"**Team Name:** {name}\n**Leader:** {member1.mention}\n**Total Members:** {len(members)}\n**Members:** {member_tags}"
                        )
                        await log_channel.send(embed=embed, view=ApproveTeamView(self, name))

                await interaction.followup.send(embed=success_embed("Team Created", f"Team '{name}' has been created successfully. Wait for an admin to approve it."))
                
            except Exception as e:
                log.error(f"Error creating team: {e}")
                await interaction.followup.send(embed=error_embed("Error", "An unexpected error occurred while creating the team."))

    @app_commands.command(name="add-logo", description="Upload a logo for your team (Team Leader only).")
    @is_team_leader_or_admin()
    async def add_logo(self, interaction: discord.Interaction, logo: discord.Attachment):
        await interaction.response.defer(ephemeral=True)
        
        if not logo.content_type or not logo.content_type.startswith("image/"):
            await interaction.followup.send(embed=error_embed("Invalid File", "Please upload a valid image file."))
            return

        async with connection.pool.acquire() as conn:
            # Find the user's team
            record = await conn.fetchrow(
                """
                SELECT t.id, t.name 
                FROM teams t 
                JOIN team_members tm ON t.id = tm.team_id 
                WHERE tm.user_id = $1 AND tm.role IN ('leader', 'sudo')
                """,
                interaction.user.id
            )
            
            if not record:
                await interaction.followup.send(embed=error_embed("Not Found", "Could not find a team where you are a leader."))
                return
                
            team_id = record['id']
            team_name = record['name']
            
            await conn.execute("UPDATE teams SET logo_url = $1 WHERE id = $2", logo.url, team_id)
            
            # Send Admin Log
            if ADMIN_LOG_CHANNEL_ID:
                log_channel = interaction.guild.get_channel(ADMIN_LOG_CHANNEL_ID)
                if log_channel:
                    embed = admin_log_embed("Team Logo Uploaded", f"Team: **{team_name}**")
                    embed.set_image(url=logo.url)
                    view = ApproveTeamView(self, team_name)
                    await log_channel.send(embed=embed, view=view)

            await interaction.followup.send(embed=success_embed("Logo Added", "Your team logo has been updated successfully."))

    @app_commands.command(name="approve-team", description="Approve a team and create their private channel (Admin only).")
    @is_admin()
    async def approve_team(self, interaction: discord.Interaction, team_name: str):
        await interaction.response.defer(ephemeral=True)
        await self.process_team_approval(interaction, team_name)

    async def process_team_approval(self, interaction: discord.Interaction, team_name: str):
        
        async with connection.pool.acquire() as conn:
            team = await conn.fetchrow("SELECT * FROM teams WHERE name = $1", team_name)
            
            if not team:
                await interaction.followup.send(embed=error_embed("Not Found", f"Team '{team_name}' does not exist."))
                return
                
            if team['is_approved']:
                await interaction.followup.send(embed=error_embed("Already Approved", f"Team '{team_name}' is already approved."))
                return
                
            guild = interaction.guild
            
            try:
                # Create private channel
                category = guild.get_channel(TEAM_CHANNEL_CATEGORY_ID)
                team_role = guild.get_role(team['team_role_id'])
                
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    guild.me: discord.PermissionOverwrite(read_messages=True)
                }
                
                if team_role:
                    overwrites[team_role] = discord.PermissionOverwrite(read_messages=True)
                    
                channel = await guild.create_text_channel(
                    name=f"{team_name.lower().replace(' ', '-')}",
                    category=category,
                    overwrites=overwrites
                )
                
                # Update database
                await conn.execute(
                    "UPDATE teams SET is_approved = TRUE, channel_id = $1 WHERE id = $2",
                    channel.id, team['id']
                )
                
                # Fetch members to tag them
                members = await conn.fetch("SELECT user_id FROM team_members WHERE team_id = $1", team['id'])
                member_tags = " ".join([f"<@{m['user_id']}>" for m in members])

                # Welcome message in team channel
                await channel.send(
                    f"{member_tags}\nThanks for participating in the tournament! You can use this as your team channel."
                )

                # Account info — pinned message
                account_embed = discord.Embed(
                    title="📌 AI-3 Tournament — Account Information",
                    description=(
                        "For the accounts used for the AI-3 Tournament:\n\n"
                        "You can use the accounts made for AI-2, but you will need to send a friend request to both host accounts below.\n\n"
                        "**Host Accounts:**\n"
                        "> [Ai3-ch9 host](link)\n"
                        "> [Ai3-ch10 host](link)\n\n"
                        "If you do not have an account, you have **2 options:**\n\n"
                        "**Option 1** — Make your own account and use our email to log in. "
                        "You will still need to send a friend request to both host accounts.\n\n"
                        "**Option 2** — We can make an account for you."
                    ),
                    color=discord.Color.gold()
                )
                account_embed.set_footer(text="AI-3 tournament")
                pinned_msg = await channel.send(embed=account_embed)
                await pinned_msg.pin()

                await interaction.followup.send(embed=success_embed("Team Approved", f"Team '{team_name}' approved and channel {channel.mention} created."))
                
            except Exception as e:
                log.error(f"Error approving team: {e}")
                await interaction.followup.send(embed=error_embed("Error", "An unexpected error occurred while approving the team."))

    @app_commands.command(name="announce-team", description="Announce an approved team in the announcements channel (Admin only).")
    @is_admin()
    async def announce_team(self, interaction: discord.Interaction, team_name: str):
        await interaction.response.defer(ephemeral=True)

        async with connection.pool.acquire() as conn:
            team = await conn.fetchrow("SELECT * FROM teams WHERE name = $1", team_name)
            if not team:
                await interaction.followup.send(embed=error_embed("Not Found", f"Team '{team_name}' does not exist."))
                return
            if not team['is_approved']:
                await interaction.followup.send(embed=error_embed("Not Approved", f"Team '{team_name}' has not been approved yet."))
                return
            if not team['logo_url']:
                await interaction.followup.send(embed=error_embed("No Logo", f"Team '{team_name}' does not have a logo. Upload one with `/add-logo` first."))
                return

            members = await conn.fetch("SELECT user_id FROM team_members WHERE team_id = $1", team['id'])
            member_tags = " ".join([f"<@{m['user_id']}>" for m in members])

        if not APPROVE_ANNOUNCE_CHANNEL_ID:
            await interaction.followup.send(embed=error_embed("No Channel", "Announcement channel is not configured."))
            return

        announce_channel = interaction.guild.get_channel(APPROVE_ANNOUNCE_CHANNEL_ID)
        if not announce_channel:
            await interaction.followup.send(embed=error_embed("Not Found", "Could not find the announcement channel."))
            return

        embed = discord.Embed(
            title="Welcome to the Tournament!",
            description=f"Please welcome **{team_name}** to AI-3!",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=team['logo_url'])
        embed.set_footer(text="AI-3 tournament")
        await announce_channel.send(content=member_tags, embed=embed)

        await interaction.followup.send(embed=success_embed("Announced", f"Team '{team_name}' has been announced."))

    @app_commands.command(name="delete-team", description="Delete a team and its roles completely (Admin only).")
    @is_admin()
    async def delete_team(self, interaction: discord.Interaction, team_name: str):
        await interaction.response.defer(ephemeral=True)
        
        async with connection.pool.acquire() as conn:
            team = await conn.fetchrow("SELECT * FROM teams WHERE name = $1", team_name)
            
            if not team:
                await interaction.followup.send(embed=error_embed("Not Found", f"Team '{team_name}' does not exist."))
                return
                

                
            guild = interaction.guild
            
            # Remove roles
            team_role = guild.get_role(team['team_role_id'])
            if team_role:
                try:
                    await team_role.delete(reason=f"Team {team_name} deleted")
                except discord.HTTPException:
                    log.warning(f"Failed to delete role for team {team_name}")

            # DB Deletion (Cascade handles team_members)
            await conn.execute("DELETE FROM teams WHERE id = $1", team['id'])
            
            await interaction.followup.send(embed=success_embed("Team Deleted", f"Team '{team_name}' has been deleted completely."))

    @app_commands.command(name="edit-team", description="Change a team's name or its entire roster (Admin only).")
    @is_admin()
    async def edit_team(
        self,
        interaction: discord.Interaction,
        team_name: str,
        new_name: Optional[str] = None,
        member1: Optional[discord.Member] = None,
        member2: Optional[discord.Member] = None,
        member3: Optional[discord.Member] = None,
        member4: Optional[discord.Member] = None,
        member5: Optional[discord.Member] = None
    ):
        await interaction.response.defer(ephemeral=True)
        
        async with connection.pool.acquire() as conn:
            team = await conn.fetchrow("SELECT * FROM teams WHERE name = $1", team_name)
            if not team:
                await interaction.followup.send(embed=error_embed("Not Found", f"Team '{team_name}' does not exist."))
                return

            guild = interaction.guild
            team_id = team['id']
            
            # Handle name change
            if new_name and new_name != team_name:
                existing = await conn.fetchrow("SELECT id FROM teams WHERE name = $1", new_name)
                if existing:
                    await interaction.followup.send(embed=error_embed("Name Taken", f"The name '{new_name}' is already taken."))
                    return
                
                await conn.execute("UPDATE teams SET name = $1 WHERE id = $2", new_name, team_id)
                
                # Update role and channel names
                team_role = guild.get_role(team['team_role_id'])
                if team_role:
                    try:
                        await team_role.edit(name=new_name)
                    except discord.HTTPException:
                        pass
                    
                if team['is_approved'] and team['channel_id']:
                    channel = guild.get_channel(team['channel_id'])
                    if channel:
                        try:
                            await channel.edit(name=f"team-{new_name.lower().replace(' ', '-')}")
                        except discord.HTTPException:
                            pass
                        
                final_name = new_name
            else:
                final_name = team_name

            # Handle roster change
            members = [m for m in [member1, member2, member3, member4, member5] if m is not None]
            if members:
                if len(members) < 3:
                    await interaction.followup.send(embed=error_embed("Too Few Members", "A team must have at least 3 members."))
                    return
                    
                if len(set(m.id for m in members)) != len(members):
                    await interaction.followup.send(embed=error_embed("Duplicate Members", "You provided the same member multiple times."))
                    return
                    
                # Check if members are in other approved teams
                member_ids = [m.id for m in members]
                in_team_records = await conn.fetch(
                    """
                    SELECT tm.user_id, t.name 
                    FROM team_members tm
                    JOIN teams t ON tm.team_id = t.id
                    WHERE tm.user_id = ANY($1::bigint[]) AND t.is_approved = TRUE AND t.id != $2
                    """,
                    member_ids, team_id
                )
                if in_team_records:
                    taken_users = ", ".join([f"<@{r['user_id']}> ({r['name']})" for r in in_team_records])
                    await interaction.followup.send(embed=error_embed("Members Already in Teams", f"The following members are already in other approved teams: {taken_users}"))
                    return

                # Fetch old members to remove roles
                old_member_records = await conn.fetch("SELECT user_id FROM team_members WHERE team_id = $1", team_id)
                old_member_ids = {r['user_id'] for r in old_member_records}
                
                team_role = guild.get_role(team['team_role_id'])
                participant_role = guild.get_role(PARTICIPANT_ROLE_ID)
                
                # Remove roles from old members
                for old_id in old_member_ids:
                    member = guild.get_member(old_id)
                    if member and team_role:
                        try:
                            await member.remove_roles(team_role)
                            if participant_role:
                                await member.remove_roles(participant_role)
                        except discord.HTTPException:
                            pass

                # Clear old members in DB
                async with conn.transaction():
                    await conn.execute("DELETE FROM team_members WHERE team_id = $1", team_id)
                    
                    # Insert new members
                    member_records = []
                    for i, m in enumerate(members):
                        role = "leader" if i == 0 else "member"
                        member_records.append((team_id, m.id, role))
                        
                    await conn.copy_records_to_table(
                        'team_members',
                        columns=['team_id', 'user_id', 'role'],
                        records=member_records
                    )
                    
                # Add roles to new members
                for member in members:
                    roles_to_add = []
                    if team_role and team_role not in member.roles:
                        roles_to_add.append(team_role)
                    if participant_role and participant_role not in member.roles:
                        roles_to_add.append(participant_role)
                    if roles_to_add:
                        try:
                            await member.add_roles(*roles_to_add)
                        except discord.HTTPException:
                            pass

            await interaction.followup.send(embed=success_embed("Team Edited", f"Team '{final_name}' has been successfully updated."))

    @app_commands.command(name="set-sudo-leader", description="Give a team member sudo leader permissions (Admin only).")
    @is_admin()
    async def set_sudo_leader(self, interaction: discord.Interaction, team_name: str, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        
        async with connection.pool.acquire() as conn:
            team = await conn.fetchrow("SELECT id FROM teams WHERE name = $1", team_name)
            if not team:
                await interaction.followup.send(embed=error_embed("Not Found", f"Team '{team_name}' does not exist."))
                return
                
            record = await conn.fetchrow("SELECT role FROM team_members WHERE team_id = $1 AND user_id = $2", team['id'], member.id)
            if not record:
                await interaction.followup.send(embed=error_embed("Not In Team", f"{member.mention} is not a member of '{team_name}'."))
                return
                
            if record['role'] == 'leader':
                await interaction.followup.send(embed=error_embed("Already Leader", f"{member.mention} is already the primary leader."))
                return
                
            if record['role'] == 'sudo':
                await interaction.followup.send(embed=error_embed("Already Sudo", f"{member.mention} is already a sudo leader."))
                return
                
            await conn.execute("UPDATE team_members SET role = 'sudo' WHERE team_id = $1 AND user_id = $2", team['id'], member.id)
            await interaction.followup.send(embed=success_embed("Sudo Leader Set", f"{member.mention} has been granted sudo leader permissions for '{team_name}'."))

async def setup(bot: commands.Bot):
    await bot.add_cog(Teams(bot))
