import discord
from discord.ext import commands
from discord import app_commands
import logging

import bot.db.connection as connection
from bot.utils.checks import is_admin
from bot.utils.embeds import admin_log_embed, FOOTER
from bot.config import WELCOME_CHANNEL_ID, ANNOUNCEMENT_CHANNEL_ID, SELF_ROLES_CHANNEL_ID, ADMIN_LOG_CHANNEL_ID

log = logging.getLogger(__name__)


class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._honeypot_channel_ids: set[int] = set()

    async def cog_load(self):
        """Load honeypot channel IDs from DB into memory on startup."""
        async with connection.pool.acquire() as conn:
            rows = await conn.fetch("SELECT channel_id FROM honeypot_channels")
            self._honeypot_channel_ids = {r["channel_id"] for r in rows}
        log.info(f"Loaded {len(self._honeypot_channel_ids)} honeypot channel(s).")

    # ── Welcome ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not WELCOME_CHANNEL_ID:
            return

        channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
        if not channel:
            log.warning(f"Welcome channel {WELCOME_CHANNEL_ID} not found.")
            return

        announcement_mention = f"<#{ANNOUNCEMENT_CHANNEL_ID}>" if ANNOUNCEMENT_CHANNEL_ID else "#announcements"
        self_roles_mention = f"<#{SELF_ROLES_CHANNEL_ID}>" if SELF_ROLES_CHANNEL_ID else "#self-roles"

        message = (
            f"Hey {member.mention}, welcome to **Anshu's Invitational**! "
            f"Have a look at {announcement_mention} for news about tournaments. "
            f"Grab some self roles in {self_roles_mention}!"
        )

        try:
            await channel.send(message)
        except discord.HTTPException as e:
            log.error(f"Failed to send welcome message: {e}")

    # ── Honeypot trap ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore DMs, bots, and non-honeypot channels
        if not message.guild:
            return
        if message.channel.id not in self._honeypot_channel_ids:
            return
        if message.author.bot:
            return

        # Admins are exempt
        member = message.guild.get_member(message.author.id)
        if member and member.guild_permissions.administrator:
            return

        log.info(f"Honeypot triggered by {message.author} ({message.author.id}) in #{message.channel.name}")

        try:
            # Softban: ban (deletes messages) then immediately unban
            await message.guild.ban(
                message.author,
                reason="Honeypot channel triggered — softban",
                delete_message_days=1,
            )
            await message.guild.unban(
                message.author,
                reason="Honeypot softban — automatic unban",
            )

            # Log to admin channel
            if ADMIN_LOG_CHANNEL_ID:
                log_channel = message.guild.get_channel(ADMIN_LOG_CHANNEL_ID)
                if log_channel:
                    embed = admin_log_embed(
                        "🚨 Scam Detection Triggered",
                        f"**User:** {message.author.mention} (`{message.author}` | `{message.author.id}`)\n"
                        f"**Channel:** {message.channel.mention}\n"
                        f"**Action:** Softbanned (ban + instant unban)",
                        color=discord.Color.red(),
                    )
                    embed.set_thumbnail(url=message.author.display_avatar.url)
                    await log_channel.send(embed=embed)

        except discord.Forbidden:
            log.warning(f"Missing permissions to softban {message.author}.")
        except discord.HTTPException as e:
            log.error(f"Error softbanning {message.author}: {e}")

    # ── /create-anti-bot-channel ──────────────────────────────────────────────

    @app_commands.command(
        name="create-anti-bot-channel",
        description="Create a honeypot channel that softbans anyone who sends a message (Admin only)."
    )
    @is_admin()
    async def create_anti_bot_channel(self, interaction: discord.Interaction, channel_name: str):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild

        # Permissions: everyone can view and send (so bots/users stumble in),
        # but the bot needs to be able to manage it
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                read_message_history=True,
            )
        }

        try:
            # Create channel with no category
            channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                reason=f"Honeypot channel created by {interaction.user}",
            )

            # Post and pin the warning embed
            embed = discord.Embed(
                title="⚠️ DO NOT SEND MESSAGES IN THIS CHANNEL",
                description=(
                    "This channel is used to catch spam bots. "
                    "Any messages sent here will result in a **softban**.\n\n"
                    "Normal members do not need to interact with this channel in any way.\n"
                    "If you do not wish to see this channel, right click or long press it "
                    "and select **\"Hide from Channel List\"**.\n\n"
                ),
                color=discord.Color.red(),
            )
            embed.set_footer(text=FOOTER)
            warning_msg = await channel.send(embed=embed)
            await warning_msg.pin()

            # Store in DB and in-memory cache
            async with connection.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO honeypot_channels (channel_id) VALUES ($1) ON CONFLICT DO NOTHING",
                    channel.id,
                )
            self._honeypot_channel_ids.add(channel.id)

            await interaction.followup.send(
                f"✅ Honeypot channel {channel.mention} created and registered.",
                ephemeral=True,
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to create channels.", ephemeral=True
            )
        except discord.HTTPException as e:
            log.error(f"Error creating honeypot channel: {e}")
            await interaction.followup.send(
                "❌ Something went wrong while creating the channel.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))
