import re
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands


# =========================================================
# HELPERS
# =========================================================

def clean_username(value: str) -> str:
    return value.strip().lstrip("@").lower()


def parse_user_id(value: str):
    value = str(value).strip()
    value = re.sub(r"[<@!>]", "", value)

    if not value.isdigit():
        return None

    return int(value)


def subscription_is_valid(sub) -> bool:

    if not sub:
        return False

    if not sub["active"]:
        return False

    try:
        expires = datetime.fromisoformat(
            sub["expires_at"]
        )
    except Exception:
        return False

    return expires > datetime.now(timezone.utc)


def owner_check(interaction, owner_id: int) -> bool:
    return interaction.user.id == owner_id


# =========================================================
# SAFE INTERACTION HANDLING
# =========================================================

async def safe_defer(
    interaction: discord.Interaction
) -> bool:

    try:

        if interaction.is_expired():
            return False

        if interaction.response.is_done():
            return True

        await interaction.response.defer(
            ephemeral=True
        )

        return True

    except (
        discord.NotFound,
        discord.HTTPException,
        Exception,
    ):

        return False


async def safe_followup(
    interaction: discord.Interaction,
    content=None,
    *,
    embed=None
):

    try:

        if interaction.is_expired():
            return False

        await interaction.followup.send(
            content=content,
            embed=embed,
            ephemeral=True
        )

        return True

    except (
        discord.NotFound,
        discord.HTTPException,
        Exception,
    ):

        return False


# =========================================================
# REGISTER COMMANDS
# =========================================================

def register_commands(
    bot,
    owner_id: int,
    owner_guild_id: int
):

    owner_guild = discord.Object(
        id=owner_guild_id
    )

    # =====================================================
    # CUSTOMER: MONITOR
    # =====================================================

    @bot.tree.command(
        name="monitor",
        description="Start monitoring an Instagram account."
    )
    @app_commands.describe(
        username="Instagram username",
        price="Service value in USD"
    )
    async def monitor(
        interaction: discord.Interaction,
        username: str,
        price: float
    ):

        if not await safe_defer(interaction):
            return

        username = clean_username(username)

        if not username:

            await safe_followup(
                interaction,
                "❌ Invalid Instagram username."
            )
            return

        if price < 0:

            await safe_followup(
                interaction,
                "❌ Price cannot be negative."
            )
            return

        sub = await bot.db.subscription(
            interaction.user.id
        )

        if not subscription_is_valid(sub):

            await safe_followup(
                interaction,
                "🔒 **No active subscription.**\n\n"
                "Please contact the InstaMonitor owner "
                "to activate your access."
            )
            return

        try:

            account = await bot.db.add_account(
                interaction.user.id,
                username,
                price
            )

        except Exception as exc:

            if "UNIQUE" in str(exc).upper():

                await safe_followup(
                    interaction,
                    f"⚠️ **@{username}** is already "
                    "being monitored."
                )

            else:

                await safe_followup(
                    interaction,
                    "❌ Could not add the account."
                )

            return

        embed = discord.Embed(
            title="📋 Monitoring Started",
            color=0x5865F2
        )

        embed.description = (
            "🟢 **ACCOUNT ADDED SUCCESSFULLY**"
        )

        embed.add_field(
            name="📸 Instagram",
            value=f"**@{username}**",
            inline=True
        )

        embed.add_field(
            name="💵 Value",
            value=f"**${price:.2f}**",
            inline=True
        )

        embed.add_field(
            name="⏱ Monitoring",
            value=f"Every **{bot.monitor.interval}s**",
            inline=True
        )

        embed.set_footer(
            text="InstaMonitor • Account monitoring"
        )

        await safe_followup(
            interaction,
            embed=embed
        )

    # =====================================================
    # CUSTOMER: UNMONITOR
    # =====================================================

    @bot.tree.command(
        name="unmonitor",
        description="Stop monitoring an Instagram account."
    )
    @app_commands.describe(
        username="Instagram username"
    )
    async def unmonitor(
        interaction: discord.Interaction,
        username: str
    ):

        if not await safe_defer(interaction):
            return

        username = clean_username(username)

        try:

            removed = await bot.db.remove_account(
                interaction.user.id,
                username
            )

        except Exception:

            await safe_followup(
                interaction,
                "❌ Could not remove the account."
            )
            return

        if removed:

            await safe_followup(
                interaction,
                f"🛑 Monitoring stopped for **@{username}**."
            )

        else:

            await safe_followup(
                interaction,
                f"❌ **@{username}** is not in "
                "your monitoring list."
            )

    # =====================================================
    # CUSTOMER: STATUS
    # =====================================================

    @bot.tree.command(
        name="status",
        description="Check the current Instagram status."
    )
    @app_commands.describe(
        username="Instagram username"
    )
    async def status(
        interaction: discord.Interaction,
        username: str
    ):

        if not await safe_defer(interaction):
            return

        username = clean_username(username)

        account = await bot.db.get_account(
            interaction.user.id,
            username
        )

        if not account:

            await safe_followup(
                interaction,
                f"❌ **@{username}** is not being monitored."
            )
            return

        status_value = account["status"]

        if status_value == "ACTIVE":

            icon = "🟢"
            color = 0x2ECC71

        elif status_value == "UNAVAILABLE":

            icon = "🔴"
            color = 0xE74C3C

        else:

            icon = "🟡"
            color = 0xF1C40F

        embed = discord.Embed(
            title=f"{icon} @{username}",
            color=color
        )

        embed.add_field(
            name="Status",
            value=f"**{status_value}**",
            inline=True
        )

        embed.add_field(
            name="Value",
            value=f"${account['price_usd']:.2f}",
            inline=True
        )

        embed.add_field(
            name="Last Checked",
            value=(
                account["last_checked_at"]
                or "Never"
            ),
            inline=False
        )

        await safe_followup(
            interaction,
            embed=embed
        )

    # =====================================================
    # CUSTOMER: LIST
    # =====================================================

    @bot.tree.command(
        name="list",
        description="Show your monitored Instagram accounts."
    )
    async def list_accounts(
        interaction: discord.Interaction
    ):

        if not await safe_defer(interaction):
            return

        try:

            accounts = await bot.db.list_accounts(
                interaction.user.id
            )

        except Exception:

            await safe_followup(
                interaction,
                "❌ Could not load your monitoring list."
            )
            return

        if not accounts:

            await safe_followup(
                interaction,
                "📋 **No accounts are currently being monitored.**"
            )
            return

        lines = []

        for account in accounts:

            status_value = account["status"]

            if status_value == "ACTIVE":
                icon = "🟢"

            elif status_value == "UNAVAILABLE":
                icon = "🔴"

            else:
                icon = "🟡"

            lines.append(
                f"{icon} **@{account['username']}** "
                f"• `{status_value}` "
                f"• `${account['price_usd']:.2f}`"
            )

        embed = discord.Embed(
            title="📋 Monitoring List",
            description="\n".join(lines),
            color=0x5865F2
        )

        embed.set_footer(
            text=f"{len(accounts)} account(s)"
        )

        await safe_followup(
            interaction,
            embed=embed
        )

    # =====================================================
    # CUSTOMER: HISTORY
    # =====================================================

    @bot.tree.command(
        name="history",
        description="Show recent account events."
    )
    @app_commands.describe(
        username="Instagram username"
    )
    async def history(
        interaction: discord.Interaction,
        username: str
    ):

        if not await safe_defer(interaction):
            return

        username = clean_username(username)

        try:

            rows = await bot.db.history(
                interaction.user.id,
                username
            )

        except Exception:

            await safe_followup(
                interaction,
                "❌ Could not load account history."
            )
            return

        if not rows:

            await safe_followup(
                interaction,
                "📋 No history found."
            )
            return

        lines = []

        for row in rows:

            event_type = row["event_type"]

            if event_type == "BAN_LIKE":
                event_name = "🔴 BANNED"

            elif event_type == "UNBAN_LIKE":
                event_name = "🟢 RESTORED"

            else:
                event_name = event_type

            lines.append(
                f"`{row['detected_at'][:19]}` "
                f"**{event_name}**\n"
                f"{row['old_status']} → "
                f"{row['new_status']}"
            )

        embed = discord.Embed(
            title=f"📜 @{username} History",
            description="\n\n".join(lines),
            color=0x9B59B6
        )

        await safe_followup(
            interaction,
            embed=embed
        )

    # =====================================================
    # CUSTOMER: REPORT
    # =====================================================

    @bot.tree.command(
        name="report",
        description="Show your monitoring report."
    )
    @app_commands.choices(
        period=[
            app_commands.Choice(
                name="Today",
                value="today"
            ),
            app_commands.Choice(
                name="Month",
                value="month"
            )
        ]
    )
    async def report(
        interaction: discord.Interaction,
        period: app_commands.Choice[str]
    ):

        if not await safe_defer(interaction):
            return

        now = datetime.now(timezone.utc)

        if period.value == "today":

            start = now.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0
            )

        else:

            start = now.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0
            )

        try:

            row = await bot.db.report(
                interaction.user.id,
                start.isoformat()
            )

        except Exception:

            await safe_followup(
                interaction,
                "❌ Could not generate the report."
            )
            return

        bans = row["bans"] or 0
        unbans = row["unbans"] or 0
        revenue = row["revenue"] or 0

        embed = discord.Embed(
            title=f"📊 {period.name} Report",
            color=0x5865F2
        )

        embed.add_field(
            name="🔴 Banned",
            value=f"**{bans}**",
            inline=True
        )

        embed.add_field(
            name="🟢 Restored",
            value=f"**{unbans}**",
            inline=True
        )

        embed.add_field(
            name="💰 Revenue",
            value=f"**${revenue:.2f}**",
            inline=True
        )

        await safe_followup(
            interaction,
            embed=embed
        )

    # =====================================================
    # CUSTOMER: NOTIFICATION CHANNEL
    # =====================================================

    @bot.tree.command(
        name="set_notifications",
        description="Choose where your monitoring alerts are sent."
    )
    @app_commands.describe(
        channel="Select the Discord channel for alerts"
    )
    async def set_notifications(
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):

        if not await safe_defer(interaction):
            return

        if interaction.guild is None:

            await safe_followup(
                interaction,
                "❌ This command must be used inside a server."
            )
            return

        # Make sure the bot can actually send messages.
        #
        # interaction.guild.me can be None if the bot's member cache
        # isn't populated (e.g. right after startup, or if the guilds
        # intent was ever off). Calling channel.permissions_for(None)
        # crashes immediately rather than raising a catchable Discord
        # error, which silently hangs the interaction. We resolve the
        # bot's member fresh via the API instead, so this always works
        # or fails with a message you can actually see.
        me = interaction.guild.me

        if me is None:
            try:
                me = await interaction.guild.fetch_member(bot.user.id)
            except discord.NotFound:
                await safe_followup(
                    interaction,
                    "❌ I couldn't find myself as a member of this "
                    "server. The bot may need to be re-invited."
                )
                return
            except Exception as exc:
                await safe_followup(
                    interaction,
                    f"❌ Unexpected error resolving bot membership: `{exc}`"
                )
                return

        try:
            permissions = channel.permissions_for(me)
        except Exception as exc:
            await safe_followup(
                interaction,
                f"❌ Unexpected error checking permissions: `{exc}`"
            )
            return

        if not permissions.send_messages:

            await safe_followup(
                interaction,
                f"❌ I cannot send messages in "
                f"{channel.mention}.\n\n"
                "Give the bot **Send Messages** permission "
                "in that channel."
            )
            return

        if not permissions.embed_links:

            await safe_followup(
                interaction,
                f"⚠️ I can send messages to "
                f"{channel.mention}, but I don't have "
                "**Embed Links** permission."
            )
            return

        try:

            await bot.db.set_notification_channel(
                interaction.user.id,
                interaction.guild.id,
                channel.id,
            )

        except Exception:

            await safe_followup(
                interaction,
                "❌ Could not save notification settings."
            )
            return

        embed = discord.Embed(
            title="🔔 Notifications Configured",
            description=(
                "Your monitoring alerts will be sent to "
                f"{channel.mention}."
            ),
            color=0x2ECC71
        )

        embed.add_field(
            name="🔴 Banned",
            value="Enabled",
            inline=True
        )

        embed.add_field(
            name="🟢 Restored",
            value="Enabled",
            inline=True
        )

        embed.set_footer(
            text="Make sure Discord notifications are enabled on your phone."
        )

        await safe_followup(
            interaction,
            embed=embed
        )

        # Test message so the customer can immediately
        # verify that the bot can send to this channel.
        try:

            await channel.send(
                content=interaction.user.mention,
                embed=discord.Embed(
                    title="✅ Notification Test",
                    description=(
                        "Your InstaMonitor notification channel "
                        "is working correctly."
                    ),
                    color=0x2ECC71
                )
            )

        except Exception:
            pass

    # =====================================================
    # OWNER: GRANT ACCESS
    # =====================================================

    @bot.tree.command(
        name="grant_access",
        description="OWNER ONLY: grant customer access.",
        guild=owner_guild
    )
    @app_commands.describe(
        user_id="Customer Discord User ID",
        days="Subscription duration in days",
        plan="Subscription plan"
    )
    async def grant_access(
        interaction: discord.Interaction,
        user_id: str,
        days: int,
        plan: str
    ):

        if not await safe_defer(interaction):
            return

        if not owner_check(interaction, owner_id):

            await safe_followup(
                interaction,
                "⛔ **Owner only.**"
            )
            return

        parsed_id = parse_user_id(user_id)

        if parsed_id is None:

            await safe_followup(
                interaction,
                "❌ Invalid Discord User ID."
            )
            return

        if days <= 0:

            await safe_followup(
                interaction,
                "❌ Days must be greater than 0."
            )
            return

        try:

            user = await bot.fetch_user(parsed_id)

        except discord.NotFound:

            await safe_followup(
                interaction,
                "❌ Discord user could not be found."
            )
            return

        now = datetime.now(timezone.utc)

        expires = now + timedelta(days=days)

        await bot.db.set_subscription(
            parsed_id,
            plan.strip(),
            now.isoformat(),
            expires.isoformat()
        )

        embed = discord.Embed(
            title="👤 Access Granted",
            color=0x2ECC71
        )

        embed.description = (
            "✅ **CUSTOMER ACCESS ACTIVATED**"
        )

        embed.add_field(
            name="👤 Customer",
            value=(
                f"{user.mention}\n"
                f"`{parsed_id}`"
            ),
            inline=False
        )

        embed.add_field(
            name="📦 Plan",
            value=f"**{plan.strip()}**",
            inline=True
        )

        embed.add_field(
            name="📅 Duration",
            value=f"**{days} days**",
            inline=True
        )

        embed.add_field(
            name="⏱ Expires",
            value=(
                f"`{expires.strftime('%Y-%m-%d %H:%M UTC')}`"
            ),
            inline=False
        )

        await safe_followup(
            interaction,
            embed=embed
        )

        try:

            await user.send(
                embed=discord.Embed(
                    title="🎉 InstaMonitor Access Activated",
                    description=(
                        "Your monitoring subscription is now active.\n\n"
                        f"📦 Plan: **{plan.strip()}**\n"
                        f"📅 Duration: **{days} days**\n"
                        f"⏱ Expires: "
                        f"**{expires.strftime('%Y-%m-%d %H:%M UTC')}**\n\n"
                        "You can now use InstaMonitor."
                    ),
                    color=0x2ECC71
                )
            )

        except (
            discord.Forbidden,
            discord.HTTPException
        ):
            pass

    # =====================================================
    # OWNER: EXTEND ACCESS
    # =====================================================

    @bot.tree.command(
        name="extend_access",
        description="OWNER ONLY: extend customer access.",
        guild=owner_guild
    )
    @app_commands.describe(
        user_id="Customer Discord User ID",
        days="Additional days"
    )
    async def extend_access(
        interaction: discord.Interaction,
        user_id: str,
        days: int
    ):

        if not await safe_defer(interaction):
            return

        if not owner_check(interaction, owner_id):

            await safe_followup(
                interaction,
                "⛔ **Owner only.**"
            )
            return

        parsed_id = parse_user_id(user_id)

        if parsed_id is None:

            await safe_followup(
                interaction,
                "❌ Invalid Discord User ID."
            )
            return

        if days <= 0:

            await safe_followup(
                interaction,
                "❌ Days must be greater than 0."
            )
            return

        sub = await bot.db.subscription(parsed_id)

        if not sub:

            await safe_followup(
                interaction,
                "❌ No subscription exists for this user."
            )
            return

        current_expiry = datetime.fromisoformat(
            sub["expires_at"]
        )

        base = max(
            current_expiry,
            datetime.now(timezone.utc)
        )

        expires = base + timedelta(days=days)

        await bot.db.set_subscription(
            parsed_id,
            sub["plan"],
            sub["starts_at"],
            expires.isoformat()
        )

        await safe_followup(
            interaction,
            "✅ **Access Extended**\n\n"
            f"Customer: `{parsed_id}`\n"
            f"Added: **{days} days**\n"
            f"New expiry: "
            f"`{expires.strftime('%Y-%m-%d %H:%M UTC')}`"
        )

    # =====================================================
    # OWNER: ACCESS STATUS
    # =====================================================

    @bot.tree.command(
        name="access_status",
        description="OWNER ONLY: check customer subscription.",
        guild=owner_guild
    )
    @app_commands.describe(
        user_id="Customer Discord User ID"
    )
    async def access_status(
        interaction: discord.Interaction,
        user_id: str
    ):

        if not await safe_defer(interaction):
            return

        if not owner_check(interaction, owner_id):

            await safe_followup(
                interaction,
                "⛔ **Owner only.**"
            )
            return

        parsed_id = parse_user_id(user_id)

        if parsed_id is None:

            await safe_followup(
                interaction,
                "❌ Invalid Discord User ID."
            )
            return

        sub = await bot.db.subscription(parsed_id)

        if not sub:

            await safe_followup(
                interaction,
                "📋 No subscription found."
            )
            return

        active = subscription_is_valid(sub)

        embed = discord.Embed(
            title="🔐 Customer Subscription",
            color=(
                0x2ECC71
                if active
                else 0xE74C3C
            )
        )

        embed.add_field(
            name="👤 User ID",
            value=f"`{parsed_id}`",
            inline=False
        )

        embed.add_field(
            name="📦 Plan",
            value=f"**{sub['plan']}**",
            inline=True
        )

        embed.add_field(
            name="📊 Status",
            value=(
                "🟢 ACTIVE"
                if active
                else "🔴 EXPIRED"
            ),
            inline=True
        )

        embed.add_field(
            name="⏱ Expires",
            value=f"`{sub['expires_at']}`",
            inline=False
        )

        await safe_followup(
            interaction,
            embed=embed
        )

    # =====================================================
    # OWNER: HELP
    # =====================================================

    @bot.tree.command(
        name="owner_help",
        description="OWNER ONLY: show owner commands.",
        guild=owner_guild
    )
    async def owner_help(
        interaction: discord.Interaction
    ):

        if not await safe_defer(interaction):
            return

        if not owner_check(interaction, owner_id):

            await safe_followup(
                interaction,
                "⛔ **Owner only.**"
            )
            return

        embed = discord.Embed(
            title="👤 InstaMonitor Owner Panel",
            color=0x5865F2
        )

        embed.description = (
            "**Customer Management**\n\n"
            "👤 `/grant_access`\n"
            "Give a customer a subscription.\n\n"
            "💳 `/extend_access`\n"
            "Add days to a subscription.\n\n"
            "🔐 `/access_status`\n"
            "Check customer access.\n\n"
            "👤 `/owner_help`\n"
            "Show this panel."
        )

        await safe_followup(
            interaction,
            embed=embed
        )