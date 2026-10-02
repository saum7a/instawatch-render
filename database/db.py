import aiosqlite
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path):
        self.path = path
        self.conn = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row

    async def initialize(self):
        await self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            discord_user_id INTEGER PRIMARY KEY,
            plan TEXT NOT NULL DEFAULT 'basic',
            starts_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            price_usd REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'UNKNOWN',
            previous_status TEXT NOT NULL DEFAULT 'UNKNOWN',
            first_seen_at TEXT NOT NULL,
            last_checked_at TEXT,
            last_changed_at TEXT,
            unavailable_since TEXT,
            restored_at TEXT,
            UNIQUE(owner_id, username)
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            event_type TEXT NOT NULL,
            old_status TEXT NOT NULL,
            new_status TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            duration_seconds INTEGER,
            revenue_usd REAL NOT NULL DEFAULT 0,
            screenshot_path TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_events_detected
        ON events(detected_at);

        CREATE INDEX IF NOT EXISTS idx_accounts_owner
        ON accounts(owner_id);

        CREATE TABLE IF NOT EXISTS notification_channels (
            owner_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_notification_channels_guild
        ON notification_channels(guild_id);
        """)

        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def add_account(self, owner_id, username, price):
        username = username.strip().lstrip("@").lower()
        now = utcnow()

        await self.conn.execute(
            """
            INSERT INTO accounts
            (owner_id, username, price_usd, first_seen_at)
            VALUES (?, ?, ?, ?)
            """,
            (owner_id, username, price, now),
        )

        await self.conn.commit()

        return await self.get_account(owner_id, username)

    async def remove_account(self, owner_id, username):
        username = username.strip().lstrip("@").lower()

        cur = await self.conn.execute(
            """
            DELETE FROM accounts
            WHERE owner_id=? AND username=?
            """,
            (owner_id, username),
        )

        await self.conn.commit()

        return cur.rowcount > 0

    async def get_account(self, owner_id, username):
        username = username.strip().lstrip("@").lower()

        cur = await self.conn.execute(
            """
            SELECT *
            FROM accounts
            WHERE owner_id=? AND username=?
            """,
            (owner_id, username),
        )

        return await cur.fetchone()

    async def list_accounts(self, owner_id):
        cur = await self.conn.execute(
            """
            SELECT *
            FROM accounts
            WHERE owner_id=?
            ORDER BY username
            """,
            (owner_id,),
        )

        return await cur.fetchall()

    async def all_accounts(self):
        cur = await self.conn.execute(
            """
            SELECT *
            FROM accounts
            ORDER BY id
            """
        )

        return await cur.fetchall()

    async def update_check(self, account_id, new_status):
        """
        Update the result of a monitoring check.

        UNKNOWN is treated as an inconclusive check and does NOT
        overwrite the last confirmed status.

        Example:

            ACTIVE -> UNKNOWN
            stays ACTIVE

            UNAVAILABLE -> UNKNOWN
            stays UNAVAILABLE

        Only ACTIVE and UNAVAILABLE can change the stored status.
        """

        now = utcnow()

        cur = await self.conn.execute(
            """
            SELECT *
            FROM accounts
            WHERE id=?
            """,
            (account_id,),
        )

        account = await cur.fetchone()

        if not account:
            return None

        old_status = account["status"]

        # UNKNOWN means this check wasn't reliable.
        # Keep the previously confirmed state.
        if new_status == "UNKNOWN":
            await self.conn.execute(
                """
                UPDATE accounts
                SET last_checked_at=?
                WHERE id=?
                """,
                (now, account_id),
            )

            await self.conn.commit()

            return (
                account,
                old_status,
                old_status,
                now,
            )

        # Only confirmed statuses update the stored status.
        await self.conn.execute(
            """
            UPDATE accounts
            SET previous_status=?,
                status=?,
                last_checked_at=?
            WHERE id=?
            """,
            (
                old_status,
                new_status,
                now,
                account_id,
            ),
        )

        await self.conn.commit()

        return (
            account,
            old_status,
            new_status,
            now,
        )

    async def mark_unavailable(self, account_id, when):
        await self.conn.execute(
            """
            UPDATE accounts
            SET unavailable_since=?,
                last_changed_at=?
            WHERE id=?
            """,
            (
                when,
                when,
                account_id,
            ),
        )

        await self.conn.commit()

    async def mark_restored(self, account_id, when):
        await self.conn.execute(
            """
            UPDATE accounts
            SET restored_at=?,
                last_changed_at=?
            WHERE id=?
            """,
            (
                when,
                when,
                account_id,
            ),
        )

        await self.conn.commit()

    async def add_event(
        self,
        account,
        event_type,
        old_status,
        new_status,
        detected_at,
        duration_seconds=None,
        screenshot_path=None,
    ):
        await self.conn.execute(
            """
            INSERT INTO events
            (
                account_id,
                owner_id,
                username,
                event_type,
                old_status,
                new_status,
                detected_at,
                duration_seconds,
                revenue_usd,
                screenshot_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account["id"],
                account["owner_id"],
                account["username"],
                event_type,
                old_status,
                new_status,
                detected_at,
                duration_seconds,
                account["price_usd"],
                screenshot_path,
            ),
        )

        await self.conn.commit()

    async def history(self, owner_id, username, limit=20):
        username = username.strip().lstrip("@").lower()

        cur = await self.conn.execute(
            """
            SELECT *
            FROM events
            WHERE owner_id=? AND username=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                owner_id,
                username,
                limit,
            ),
        )

        return await cur.fetchall()

    async def report(self, owner_id, start_iso):
        cur = await self.conn.execute(
            """
            SELECT
                COUNT(*) AS events,

                SUM(
                    CASE
                        WHEN event_type='BAN_LIKE'
                        THEN 1
                        ELSE 0
                    END
                ) AS bans,

                SUM(
                    CASE
                        WHEN event_type='UNBAN_LIKE'
                        THEN 1
                        ELSE 0
                    END
                ) AS unbans,

                COALESCE(
                    SUM(
                        CASE
                            WHEN event_type='UNBAN_LIKE'
                            THEN revenue_usd
                            ELSE 0
                        END
                    ),
                    0
                ) AS revenue

            FROM events
            WHERE owner_id=?
            AND detected_at>=?
            """,
            (
                owner_id,
                start_iso,
            ),
        )

        return await cur.fetchone()

    async def subscription(self, user_id):
        cur = await self.conn.execute(
            """
            SELECT *
            FROM subscriptions
            WHERE discord_user_id=?
            """,
            (user_id,),
        )

        return await cur.fetchone()

    async def set_subscription(
        self,
        user_id,
        plan,
        starts_at,
        expires_at,
    ):
        await self.conn.execute(
            """
            INSERT INTO subscriptions
            (
                discord_user_id,
                plan,
                starts_at,
                expires_at,
                active
            )
            VALUES (?, ?, ?, ?, 1)

            ON CONFLICT(discord_user_id)
            DO UPDATE SET
                plan=excluded.plan,
                starts_at=excluded.starts_at,
                expires_at=excluded.expires_at,
                active=1
            """,
            (
                user_id,
                plan,
                starts_at,
                expires_at,
            ),
        )

        await self.conn.commit()

    async def set_notification_channel(self, owner_id, guild_id, channel_id):
        await self.conn.execute(
            """
            INSERT INTO notification_channels
                (owner_id, guild_id, channel_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(owner_id) DO UPDATE SET
                guild_id=excluded.guild_id,
                channel_id=excluded.channel_id,
                updated_at=excluded.updated_at
            """,
            (owner_id, guild_id, channel_id, utcnow()),
        )
        await self.conn.commit()

    async def get_notification_channel(self, owner_id):
        cur = await self.conn.execute(
            """
            SELECT guild_id, channel_id, updated_at
            FROM notification_channels
            WHERE owner_id=?
            """,
            (owner_id,),
        )
        return await cur.fetchone()

    async def deactivate_expired(self):
        now = utcnow()

        await self.conn.execute(
            """
            UPDATE subscriptions
            SET active=0
            WHERE expires_at<=?
            """,
            (now,),
        )

        await self.conn.commit()