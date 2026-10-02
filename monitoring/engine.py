import asyncio
import logging
import os
from datetime import datetime, timezone

import discord
from playwright.async_api import async_playwright

from monitoring.classifier import Status
from screenshots.capture import capture_public_profile


log = logging.getLogger("instawatch.monitor")


def utcnow_dt():
    return datetime.now(timezone.utc)


def parse_iso(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def format_datetime(value):
    if not value:
        return "Unknown"

    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(value)


def format_duration(seconds):
    if seconds is None:
        return "Unknown"

    seconds = max(0, int(seconds))

    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return (
        f"{hours} hours, "
        f"{minutes} minutes, "
        f"{seconds} seconds"
    )


class BrowserResult:

    def __init__(
        self,
        status,
        confidence,
        reason,
        title="",
        text="",
    ):
        self.status = status
        self.confidence = confidence
        self.reason = reason
        self.title = title
        self.text = text


class MonitoringEngine:

    def __init__(
        self,
        db,
        bot,
        interval_seconds=15,
        screenshot_enabled=True,
        timeout_seconds=30,
    ):

        self.db = db
        self.bot = bot

        self.interval = max(
            10,
            interval_seconds,
        )

        self.screenshot_enabled = screenshot_enabled
        self.timeout_seconds = timeout_seconds

        self.task = None
        self.running = False

        self.playwright = None
        self.browser = None

        # Maximum number of simultaneous Instagram checks.
        self.browser_sem = asyncio.Semaphore(5)

        # account_id -> {
        #     "status": Status,
        #     "count": int
        # }
        self.confirmations = {}

        self.confirmation_required = 2

    # =====================================================
    # START
    # =====================================================

    async def start(self):

        log.info("Starting Playwright browser...")

        self.playwright = await async_playwright().start()

        self.browser = await self.playwright.chromium.launch(
            headless=True
        )

        self.running = True

        self.task = asyncio.create_task(
            self.loop()
        )

        log.info(
            "Monitoring engine started: "
            "interval=%ss confirmations=%s",
            self.interval,
            self.confirmation_required,
        )

    # =====================================================
    # STOP
    # =====================================================

    async def stop(self):

        self.running = False

        if self.task:

            self.task.cancel()

            try:
                await self.task
            except asyncio.CancelledError:
                pass

            self.task = None

        if self.browser:

            try:
                await self.browser.close()
            except Exception:
                pass

            self.browser = None

        if self.playwright:

            try:
                await self.playwright.stop()
            except Exception:
                pass

            self.playwright = None

        log.info("Monitoring engine stopped.")

    # =====================================================
    # MAIN LOOP
    # =====================================================

    async def loop(self):

        while self.running:

            started = (
                asyncio
                .get_running_loop()
                .time()
            )

            try:

                await self.db.deactivate_expired()

                accounts = await self.db.all_accounts()

                if accounts:

                    await asyncio.gather(
                        *(
                            self.check_one(account)
                            for account in accounts
                        ),
                        return_exceptions=True,
                    )

            except Exception:

                log.exception(
                    "Monitoring tick failed"
                )

            elapsed = (
                asyncio
                .get_running_loop()
                .time()
                - started
            )

            await asyncio.sleep(
                max(
                    0,
                    self.interval - elapsed,
                )
            )

    # =====================================================
    # BROWSER CHECK
    # =====================================================

    async def browser_check(self, username):

        async with self.browser_sem:

            page = await self.browser.new_page(
                viewport={
                    "width": 1280,
                    "height": 900,
                },
                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/151.0 Safari/537.36"
                ),
                locale="en-US",
            )

            try:

                url = (
                    f"https://www.instagram.com/"
                    f"{username}/"
                )

                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout_seconds * 1000,
                )

                await page.wait_for_timeout(2500)

                title = await page.title()

                try:

                    body_text = await page.locator(
                        "body"
                    ).inner_text(
                        timeout=10000
                    )

                except Exception:

                    body_text = ""

                text = (
                    body_text or ""
                ).lower()

                title_lower = (
                    title or ""
                ).lower()

                status_code = (
                    response.status
                    if response
                    else 0
                )

                # =================================================
                # UNAVAILABLE / BANNED
                # =================================================

                unavailable_markers = [
                    "page isn't available",
                    "page isn’t available",
                    "page isnt available",
                    "page is not available",
                    "this page isn't available",
                    "this page isn’t available",
                    "this page isnt available",
                    "this page is not available",
                    "profile isn't available",
                    "profile isn’t available",
                    "profile isnt available",
                    "profile is not available",
                    "the link may be broken",
                    "the link you followed may be broken",
                    "the profile may have been removed",
                    "the page may have been removed",
                    "sorry, this page isn't available",
                    "sorry, this page isn’t available",
                ]

                if any(
                    marker in text
                    or marker in title_lower
                    for marker in unavailable_markers
                ):

                    return BrowserResult(
                        Status.UNAVAILABLE,
                        "HIGH",
                        "Clear unavailable-page signal",
                        title,
                        body_text,
                    )

                # =================================================
                # ACTIVE PROFILE
                # =================================================

                active_signals = []

                if (
                    "instagram photos and videos"
                    in title_lower
                ):
                    active_signals.append(
                        "Instagram profile title"
                    )

                if "followers" in text:
                    active_signals.append("followers")

                if "following" in text:
                    active_signals.append("following")

                if "posts" in text:
                    active_signals.append("posts")

                if username.lower() in text:
                    active_signals.append("username")

                if (
                    len(active_signals) >= 2
                    and len(body_text.strip()) > 100
                ):

                    return BrowserResult(
                        Status.ACTIVE,
                        "HIGH",
                        "Browser-rendered public profile detected",
                        title,
                        body_text,
                    )

                # =================================================
                # EMPTY PAGE
                # =================================================

                if (
                    title.strip().lower() == "instagram"
                    and len(body_text.strip()) == 0
                ):

                    return BrowserResult(
                        Status.UNKNOWN,
                        "LOW",
                        "Instagram returned an empty page",
                        title,
                        body_text,
                    )

                # =================================================
                # LOGIN / CHALLENGE / RATE LIMIT
                # =================================================

                ambiguous_markers = [
                    "challenge_required",
                    "challenge required",
                    "checkpoint_required",
                    "checkpoint required",
                    "please wait a few minutes",
                    "temporarily blocked",
                    "rate limit",
                    "try again later",
                    "something went wrong",
                ]

                if any(
                    marker in text
                    for marker in ambiguous_markers
                ):

                    return BrowserResult(
                        Status.UNKNOWN,
                        "LOW",
                        "Login/challenge/rate-limit signal",
                        title,
                        body_text,
                    )

                # =================================================
                # HTTP ERRORS
                # =================================================

                if status_code == 404:

                    return BrowserResult(
                        Status.UNAVAILABLE,
                        "HIGH",
                        "HTTP 404",
                        title,
                        body_text,
                    )

                if status_code in (
                    401,
                    403,
                    429,
                    500,
                    502,
                    503,
                    504,
                ):

                    return BrowserResult(
                        Status.UNKNOWN,
                        "LOW",
                        f"HTTP {status_code}",
                        title,
                        body_text,
                    )

                return BrowserResult(
                    Status.UNKNOWN,
                    "LOW",
                    "Browser could not establish reliable profile status",
                    title,
                    body_text,
                )

            except Exception as exc:

                error_text = str(exc).lower()

                # =================================================
                # DNS / NETWORK / TIMEOUT
                # =================================================

                temporary_errors = (
                    "err_name_not_resolved",
                    "err_connection_reset",
                    "err_connection_closed",
                    "err_connection_refused",
                    "err_timed_out",
                    "err_network_changed",
                    "err_internet_disconnected",
                    "timeout",
                    "timed out",
                    "network",
                )

                if any(
                    error in error_text
                    for error in temporary_errors
                ):

                    log.debug(
                        "@%s → temporary network/DNS failure",
                        username,
                    )

                    return BrowserResult(
                        Status.UNKNOWN,
                        "LOW",
                        "Temporary network/DNS failure",
                    )

                # Do NOT print the complete Playwright traceback.
                log.warning(
                    "@%s → browser check failed: %s",
                    username,
                    type(exc).__name__,
                )

                return BrowserResult(
                    Status.UNKNOWN,
                    "LOW",
                    "Temporary browser failure",
                )

            finally:

                try:
                    await page.close()
                except Exception:
                    pass

    # =====================================================
    # CHECK ACCOUNT
    # =====================================================

    async def check_one(self, account):
        username = account["username"]
        result = await self.browser_check(username)

        log.info(
            "@%s -> %s (%s) - %s",
            username, result.status.value, result.confidence, result.reason,
        )

        if result.status == Status.UNKNOWN:
            self.confirmations.pop(account["id"], None)
            return

        account_id = account["id"]
        pending = self.confirmations.get(account_id)
        if pending and pending["status"] == result.status:
            pending["count"] += 1
        else:
            pending = {"status": result.status, "count": 1}
            self.confirmations[account_id] = pending

        log.info(
            "Account %s pending %s: %s/%s",
            account_id, result.status.value, pending["count"], self.confirmation_required,
        )

        if pending["count"] < self.confirmation_required:
            return

        self.confirmations.pop(account_id, None)
        current = await self.db.get_account(account["owner_id"], username)
        if not current:
            return

        previous_status = current["status"]
        confirmed_status = result.status.value
        if previous_status == confirmed_status:
            return

        detected_at = utcnow_dt().isoformat()

        # Build and DELIVER the alert before removing the account. If Discord
        # delivery fails, keep the account in the database so a later 3/3
        # confirmation can retry instead of silently losing the notification.
        if (
            previous_status == Status.ACTIVE.value
            and confirmed_status == Status.UNAVAILABLE.value
        ):
            delivered = await self.send_banned_alert(
                current, result, detected_at
            )
            if not delivered:
                log.error(
                    "Keeping @%s monitored because BANNED notification was not delivered.",
                    username,
                )
                return

            updated = await self.db.update_check(account_id, confirmed_status)
            if not updated:
                return

            _, old_status, new_status, detected_at = updated
            await self.db.mark_unavailable(account_id, detected_at)
            await self.db.add_event(
                current, "BAN_LIKE", old_status, new_status, detected_at
            )
            await self.remove_from_monitoring(current)
            return

        if (
            previous_status == Status.UNAVAILABLE.value
            and confirmed_status == Status.ACTIVE.value
        ):
            duration = None
            if current["unavailable_since"]:
                start = parse_iso(current["unavailable_since"])
                if start:
                    duration = int((utcnow_dt() - start).total_seconds())

            screenshot = None
            if self.screenshot_enabled:
                try:
                    screenshot = await capture_public_profile(username)
                except Exception as exc:
                    log.warning(
                        "Screenshot capture failed for @%s: %s",
                        username, type(exc).__name__,
                    )

            delivered = await self.send_restored_alert(
                current, result, detected_at, duration, screenshot
            )
            if not delivered:
                log.error(
                    "Keeping @%s monitored because RESTORED notification was not delivered.",
                    username,
                )
                return

            updated = await self.db.update_check(account_id, confirmed_status)
            if not updated:
                return

            _, old_status, new_status, detected_at = updated
            await self.db.mark_restored(account_id, detected_at)
            await self.db.add_event(
                current, "UNBAN_LIKE", old_status, new_status, detected_at, duration, screenshot
            )
            await self.remove_from_monitoring(current)
            return

        # Save confirmed status when there is no special alert transition.
        updated = await self.db.update_check(account_id, confirmed_status)
        if updated:
            log.info('@%s confirmed status saved: %s', username, confirmed_status)

    # =====================================================
    # REMOVE FROM MONITORING
    # =====================================================

    async def remove_from_monitoring(self, account):

        try:

            removed = await self.db.remove_account(
                account["owner_id"],
                account["username"],
            )

            self.confirmations.pop(
                account["id"],
                None,
            )

            if removed:

                log.info(
                    "Account @%s removed from active "
                    "monitoring after confirmed status change.",
                    account["username"],
                )

            else:

                log.warning(
                    "Account @%s was already removed "
                    "from active monitoring.",
                    account["username"],
                )

        except Exception:

            log.exception(
                "Failed to remove @%s from monitoring",
                account["username"],
            )

    # =====================================================
    # GET NOTIFICATION CHANNEL
    # =====================================================

    async def get_notification_channel(self, owner_id):
        try:
            row = await self.db.get_notification_channel(owner_id)
            if not row:
                return None
            channel = self.bot.get_channel(row["channel_id"])
            if channel:
                return channel
            try:
                return await self.bot.fetch_channel(row["channel_id"])
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        except Exception:
            log.exception("Failed to load notification channel for owner %s", owner_id)
            return None

    # =====================================================
    # GET CLIENT
    # =====================================================

    async def get_owner(self, owner_id):

        try:

            user = self.bot.get_user(
                owner_id
            )

            if user:
                return user

            return await self.bot.fetch_user(
                owner_id
            )

        except Exception:

            return None

    async def _send_alert(self, account, embed, screenshot=None):
        """Send both a DM and configured server alert when possible."""
        delivered = False
        user = await self.get_owner(account["owner_id"])

        if user:
            try:
                if screenshot and os.path.exists(screenshot):
                    await user.send(
                        embed=embed,
                        file=discord.File(screenshot, filename=f"{account['username']}_restored.png"),
                    )
                else:
                    await user.send(embed=embed)
                delivered = True
                log.info("Alert DM delivered to owner %s for @%s.", account["owner_id"], account["username"])
            except discord.Forbidden:
                log.warning("DM unavailable for owner %s; continuing with channel alert.", account["owner_id"])
            except discord.HTTPException as exc:
                log.warning("DM delivery failed for @%s: %s", account["username"], exc)

        channel = await self.get_notification_channel(account["owner_id"])
        if channel:
            try:
                allowed = discord.AllowedMentions(users=[user] if user else [])
                content = user.mention if user else None
                if screenshot and os.path.exists(screenshot):
                    await channel.send(
                        content=content, embed=embed,
                        file=discord.File(screenshot, filename=f"{account['username']}_restored.png"),
                        allowed_mentions=allowed,
                    )
                else:
                    await channel.send(content=content, embed=embed, allowed_mentions=allowed)
                delivered = True
                log.info("Alert channel delivered to %s for @%s.", channel.id, account["username"])
            except discord.Forbidden:
                log.warning("Bot lacks permission to send alerts in channel %s.", channel.id)
            except discord.HTTPException as exc:
                log.warning("Channel delivery failed for @%s: %s", account["username"], exc)

        if not delivered:
            log.error(
                "ALERT DELIVERY FAILED for @%s (owner %s). "
                "Customer must enable DMs or configure /set_notifications.",
                account["username"], account["owner_id"],
            )
        return delivered

    # =====================================================
    # SEND BANNED ALERT
    # =====================================================

    async def send_banned_alert(self, account, result, detected_at):
        embed = discord.Embed(
            title=f"🔴 Account Banned | @{account['username']}",
            color=discord.Color.red(),
        )
        embed.description = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔴 **ACCOUNT BANNED**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📅 **Banned at:** {format_datetime(detected_at)}"
        )
        embed.add_field(name="💵 Service Value", value=f"${account['price_usd']:.2f}", inline=True)
        embed.add_field(name="🎯 Confidence", value=result.confidence, inline=True)
        embed.add_field(name="🔎 Detection", value=result.reason, inline=False)
        embed.set_footer(text="InstaMonitor • Instagram Account Monitoring")
        return await self._send_alert(account, embed)

    # =====================================================
    # SEND RESTORED ALERT
    # =====================================================

    async def send_restored_alert(self, account, result, detected_at, duration, screenshot=None):
        embed = discord.Embed(
            title=f"🟢 Account Restored | @{account['username']}",
            color=discord.Color.green(),
        )
        embed.description = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 **ACCOUNT RESTORED**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏱️ **Time Taken:** {format_duration(duration)}\n\n"
            f"📅 **Restored at:** {format_datetime(detected_at)}"
        )
        embed.add_field(name="💵 Service Value", value=f"${account['price_usd']:.2f}", inline=True)
        embed.add_field(name="🎯 Confidence", value=result.confidence, inline=True)
        embed.add_field(name="🔎 Detection", value=result.reason, inline=False)
        embed.set_footer(text="InstaMonitor • Account Recovery Monitoring")
        if screenshot and os.path.exists(screenshot):
            embed.set_image(url=f"attachment://{account['username']}_restored.png")
        return await self._send_alert(account, embed, screenshot=screenshot)

