import asyncio
import logging
import os

from dotenv import load_dotenv

import discord
from discord.ext import commands
from aiohttp import web

from database.db import Database
from monitoring.engine import MonitoringEngine
from bot.commands import register_commands


# =========================================================
# LOAD ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

log = logging.getLogger("instawatch")


# =========================================================
# ENVIRONMENT
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

ADMIN_USER_ID = int(
    os.getenv("ADMIN_USER_ID", "0")
)

OWNER_GUILD_ID = int(
    os.getenv("OWNER_GUILD_ID", "0")
)

CHECK_INTERVAL = int(
    os.getenv(
        "CHECK_INTERVAL_SECONDS",
        "15"
    )
)

DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    "instawatch.db"
)

SCREENSHOT_ENABLED = (
    os.getenv(
        "SCREENSHOT_ENABLED",
        "true"
    ).lower()
    == "true"
)

INSTAGRAM_TIMEOUT = int(
    os.getenv(
        "INSTAGRAM_TIMEOUT_SECONDS",
        "30"
    )
)

PORT = int(os.getenv("PORT", "10000"))


# =========================================================
# VALIDATION
# =========================================================

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is missing in .env"
    )


if ADMIN_USER_ID == 0:
    raise RuntimeError(
        "ADMIN_USER_ID is missing or invalid in .env"
    )


if OWNER_GUILD_ID == 0:
    raise RuntimeError(
        "OWNER_GUILD_ID is missing or invalid in .env"
    )


# =========================================================
# BOT
# =========================================================

class InstaWatchBot(commands.Bot):

    def __init__(self):

        # Slash-command bot. Message content intent is NOT required —
        # but the `guilds` intent IS required. Without it, Discord never
        # sends the bot gateway events for guild members, so
        # `interaction.guild.me` stays None. Code that calls
        # channel.permissions_for(interaction.guild.me) then crashes
        # immediately (AttributeError: 'NoneType' object has no
        # attribute 'id') the moment it tries to resolve permissions —
        # which is exactly what was causing /set_notifications to hang
        # and show "The application did not respond".
        intents = discord.Intents.none()
        intents.guilds = True

        super().__init__(
            command_prefix="!",
            intents=intents
        )

        # -------------------------------------------------
        # DATABASE
        # -------------------------------------------------

        self.db = Database(
            DATABASE_PATH
        )

        # -------------------------------------------------
        # MONITORING ENGINE
        # -------------------------------------------------

        self.monitor = MonitoringEngine(
            db=self.db,
            bot=self,
            interval_seconds=CHECK_INTERVAL,
            screenshot_enabled=SCREENSHOT_ENABLED,
            timeout_seconds=INSTAGRAM_TIMEOUT
        )

    # =====================================================
    # SETUP
    # =====================================================

    async def setup_hook(self):

        log.info(
            "Connecting to database..."
        )

        await self.db.connect()

        await self.db.initialize()

        log.info(
            "Database initialized."
        )

        # -------------------------------------------------
        # REGISTER COMMANDS
        #
        # ADMIN_USER_ID
        # = Your Discord User ID
        #
        # OWNER_GUILD_ID
        # = Your private/admin Discord server ID
        # -------------------------------------------------

        register_commands(
            self,
            ADMIN_USER_ID,
            OWNER_GUILD_ID
        )

        # -------------------------------------------------
        # START MONITORING
        # -------------------------------------------------

        log.info(
            "Starting monitoring engine..."
        )

        await self.monitor.start()

        # -------------------------------------------------
        # COMMAND SYNC
        # -------------------------------------------------
        # Customer commands are global for scalability. We also
        # copy them into every guild the bot currently belongs to
        # so customers get immediate guild commands instead of
        # waiting for Discord's global-command propagation.
        # Owner commands remain restricted to OWNER_GUILD_ID.
        # -------------------------------------------------

        log.info("Syncing global customer slash commands...")
        await self.tree.sync()

        for guild in list(self.guilds):
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("Synced customer commands to guild %s (%s).", guild.name, guild.id)
            except discord.HTTPException:
                log.exception("Failed to sync customer commands to guild %s (%s).", guild.name, guild.id)

        log.info("Slash commands synchronized.")

    # =====================================================
    # CLOSE
    # =====================================================

    async def close(self):

        log.info(
            "Shutting down InstaMonitor..."
        )

        try:

            await self.monitor.stop()

        except Exception:

            log.exception(
                "Error stopping monitoring engine"
            )

        try:

            await self.db.close()

        except Exception:

            log.exception(
                "Error closing database"
            )

        await super().close()

        log.info(
            "InstaMonitor stopped."
        )


# =========================================================
# CREATE BOT
# =========================================================

bot = InstaWatchBot()


# =========================================================
# READY EVENT
# =========================================================

@bot.event
async def on_guild_join(guild: discord.Guild):
    """Make customer commands available immediately in a new customer server."""
    try:
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        log.info("Synced customer commands to newly joined guild %s (%s).", guild.name, guild.id)
    except discord.HTTPException:
        log.exception("Failed to sync commands to newly joined guild %s (%s).", guild.name, guild.id)


@bot.event
async def on_ready():

    log.info(
        "Logged in as %s (%s)",
        bot.user,
        bot.user.id
    )

    log.info(
        "InstaMonitor is ONLINE."
    )


# =========================================================
# RENDER HEALTH SERVER
# =========================================================

async def health_handler(request):
    return web.json_response({
        "status": "ok",
        "service": "instawatch",
        "discord": bot.is_ready(),
    })


async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    log.info("Render health server listening on 0.0.0.0:%s", PORT)
    return runner


# =========================================================
# START BOT
# =========================================================

async def run_bot():
    health_runner = await start_health_server()
    try:
        await bot.start(TOKEN)
    finally:
        await health_runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        log.info("Bot stopped by user.")
    except Exception:
        log.exception("Fatal bot error")
