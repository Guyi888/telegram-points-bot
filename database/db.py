import uuid
import aiosqlite
from datetime import date
from typing import Optional, List, Dict
from config import DATABASE_URL

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER UNIQUE NOT NULL,
    username      TEXT,
    first_name    TEXT,
    last_name     TEXT,
    points        INTEGER DEFAULT 0,
    checkin_count INTEGER DEFAULT 0,
    last_checkin  TEXT,
    is_banned     INTEGER DEFAULT 0,
    invited_by    INTEGER DEFAULT NULL,
    invite_rewarded INTEGER DEFAULT 0,
    joined_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   TEXT UNIQUE NOT NULL,
    channel_name TEXT NOT NULL,
    channel_url  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    points_cost INTEGER NOT NULL,
    category    TEXT DEFAULT '默认',
    is_active   INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS card_keys (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    key_value  TEXT NOT NULL,
    status     INTEGER DEFAULT 0,
    user_id    INTEGER,
    used_at    TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id         TEXT UNIQUE NOT NULL,
    user_id          INTEGER NOT NULL,
    product_id       INTEGER NOT NULL,
    card_key_id      INTEGER,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status           TEXT DEFAULT 'pending',
    group_message_id INTEGER,
    FOREIGN KEY (product_id)  REFERENCES products(id),
    FOREIGN KEY (card_key_id) REFERENCES card_keys(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS custom_buttons (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    text     TEXT NOT NULL,
    url      TEXT NOT NULL,
    position INTEGER DEFAULT 0
);
"""

_DEFAULT_SETTINGS = [
    ("reward_min",    "5"),
    ("reward_max",    "20"),
    ("welcome_text",  "👋 欢迎！请先加入以下所有频道，然后点击「✅ 我已加入」。"),
    ("group_id",      "0"),
    ("folder_link",   ""),
    ("bot_username",  ""),
    ("invite_reward", "20"),
]


class Database:
    def __init__(self):
        self.path = DATABASE_URL

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(_SCHEMA)
            # migrations for existing databases
            for col, definition in [
                ("invited_by",       "INTEGER DEFAULT NULL"),
                ("invite_rewarded",  "INTEGER DEFAULT 0"),
            ]:
                try:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
                except Exception:
                    pass  # column already exists
            for k, v in _DEFAULT_SETTINGS:
                await db.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
                )
            await db.commit()

    # ── users ────────────────────────────────────────────────────────────────

    async def get_user(self, user_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as c:
                row = await c.fetchone()
                return dict(row) if row else None

    async def upsert_user(self, user_id: int, username: str,
                          first_name: str, last_name: str) -> Dict:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)"
                " VALUES (?, ?, ?, ?)",
                (user_id, username, first_name, last_name),
            )
            await db.execute(
                "UPDATE users SET username=?, first_name=?, last_name=? WHERE user_id=?",
                (username, first_name, last_name, user_id),
            )
            await db.commit()
        return await self.get_user(user_id)

    async def update_points(self, user_id: int, delta: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET points=MAX(0, points+?) WHERE user_id=?",
                (delta, user_id),
            )
            await db.commit()
        return (await self.get_user(user_id))["points"]

    async def set_points(self, user_id: int, points: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET points=? WHERE user_id=?", (max(0, points), user_id)
            )
            await db.commit()

    async def do_checkin(self, user_id: int, points: int) -> bool:
        today = date.today().isoformat()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT last_checkin FROM users WHERE user_id=?", (user_id,)
            ) as c:
                row = await c.fetchone()
            if row and row["last_checkin"] == today:
                return False
            await db.execute(
                """UPDATE users
                   SET points=points+?, checkin_count=checkin_count+1, last_checkin=?
                   WHERE user_id=?""",
                (points, today, user_id),
            )
            await db.commit()
            return True

    async def ban_user(self, user_id: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (user_id,))
            await db.commit()

    async def unban_user(self, user_id: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (user_id,))
            await db.commit()

    # ── channels ─────────────────────────────────────────────────────────────

    async def get_channels(self) -> List[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM channels ORDER BY id") as c:
                return [dict(r) for r in await c.fetchall()]

    async def add_channel(self, channel_id: str, name: str, url: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO channels (channel_id, channel_name, channel_url)"
                " VALUES (?,?,?)",
                (channel_id, name, url),
            )
            await db.commit()

    async def remove_channel(self, channel_id: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM channels WHERE channel_id=?", (channel_id,))
            await db.commit()

    # ── products ─────────────────────────────────────────────────────────────

    async def get_products(self, active_only: bool = True) -> List[Dict]:
        where = "WHERE p.is_active=1" if active_only else ""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""SELECT p.*,
                           COUNT(CASE WHEN ck.status=0 THEN 1 END) AS stock
                    FROM products p
                    LEFT JOIN card_keys ck ON p.id=ck.product_id
                    {where}
                    GROUP BY p.id ORDER BY p.id"""
            ) as c:
                return [dict(r) for r in await c.fetchall()]

    async def get_product(self, product_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT p.*,
                          COUNT(CASE WHEN ck.status=0 THEN 1 END) AS stock
                   FROM products p
                   LEFT JOIN card_keys ck ON p.id=ck.product_id
                   WHERE p.id=?
                   GROUP BY p.id""",
                (product_id,),
            ) as c:
                row = await c.fetchone()
                return dict(row) if row else None

    async def add_product(self, name: str, description: str,
                          points_cost: int, category: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            c = await db.execute(
                "INSERT INTO products (name, description, points_cost, category)"
                " VALUES (?,?,?,?)",
                (name, description, points_cost, category),
            )
            await db.commit()
            return c.lastrowid

    async def toggle_product(self, product_id: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE products SET is_active=1-is_active WHERE id=?", (product_id,)
            )
            await db.commit()

    # ── card keys ────────────────────────────────────────────────────────────

    async def import_keys(self, product_id: int, keys: List[str]) -> int:
        count = 0
        async with aiosqlite.connect(self.path) as db:
            for key in keys:
                key = key.strip()
                if key:
                    await db.execute(
                        "INSERT INTO card_keys (product_id, key_value) VALUES (?,?)",
                        (product_id, key),
                    )
                    count += 1
            await db.commit()
        return count

    async def get_available_key(self, product_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM card_keys WHERE product_id=? AND status=0 LIMIT 1",
                (product_id,),
            ) as c:
                row = await c.fetchone()
                return dict(row) if row else None

    async def use_key(self, key_id: int, user_id: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE card_keys SET status=1, user_id=?, used_at=CURRENT_TIMESTAMP"
                " WHERE id=?",
                (user_id, key_id),
            )
            await db.commit()

    # ── orders ───────────────────────────────────────────────────────────────

    async def create_order(self, user_id: int, product_id: int, key_id: int) -> str:
        order_id = uuid.uuid4().hex[:16]
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO orders (order_id, user_id, product_id, card_key_id)"
                " VALUES (?,?,?,?)",
                (order_id, user_id, product_id, key_id),
            )
            await db.commit()
        return order_id

    async def get_order(self, order_id: str) -> Optional[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT o.*, p.name AS product_name, ck.key_value,
                          u.username, u.first_name, u.last_name
                   FROM orders o
                   JOIN products p   ON o.product_id=p.id
                   JOIN card_keys ck ON o.card_key_id=ck.id
                   JOIN users u      ON o.user_id=u.user_id
                   WHERE o.order_id=?""",
                (order_id,),
            ) as c:
                row = await c.fetchone()
                return dict(row) if row else None

    async def complete_order(self, order_id: str, group_msg_id: int = None):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE orders SET status='completed', group_message_id=? WHERE order_id=?",
                (group_msg_id, order_id),
            )
            await db.commit()

    async def get_user_orders(self, user_id: int) -> List[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT o.*, p.name AS product_name
                   FROM orders o JOIN products p ON o.product_id=p.id
                   WHERE o.user_id=? AND o.status='completed'
                   ORDER BY o.created_at DESC LIMIT 10""",
                (user_id,),
            ) as c:
                return [dict(r) for r in await c.fetchall()]

    # ── settings ─────────────────────────────────────────────────────────────

    async def get_setting(self, key: str, default: str = "") -> str:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ) as c:
                row = await c.fetchone()
                return row[0] if row else default

    async def set_setting(self, key: str, value: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value)
            )
            await db.commit()

    # ── custom buttons ───────────────────────────────────────────────────────

    async def get_custom_buttons(self) -> List[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM custom_buttons ORDER BY position, id"
            ) as c:
                return [dict(r) for r in await c.fetchall()]

    async def add_custom_button(self, text: str, url: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            c = await db.execute(
                "INSERT INTO custom_buttons (text, url) VALUES (?,?)", (text, url)
            )
            await db.commit()
            return c.lastrowid

    async def remove_custom_button(self, btn_id: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM custom_buttons WHERE id=?", (btn_id,))
            await db.commit()

    # ── leaderboard ──────────────────────────────────────────────────────────

    async def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT user_id, first_name, last_name, username, points, checkin_count
                   FROM users WHERE is_banned=0
                   ORDER BY points DESC LIMIT ?""",
                (limit,),
            ) as c:
                return [dict(r) for r in await c.fetchall()]

    async def get_user_rank(self, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                """SELECT COUNT(*) FROM users
                   WHERE is_banned=0 AND points > (
                       SELECT points FROM users WHERE user_id=?
                   )""",
                (user_id,),
            ) as c:
                row = await c.fetchone()
                return (row[0] + 1) if row else 0

    # ── invite ───────────────────────────────────────────────────────────────

    async def set_inviter(self, user_id: int, inviter_id: int):
        """Record who invited this user (only if not already set)."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET invited_by=? WHERE user_id=? AND invited_by IS NULL",
                (inviter_id, user_id),
            )
            await db.commit()

    async def try_give_invite_reward(self, user_id: int) -> Optional[int]:
        """Call after user's first checkin. Returns inviter_id if reward was given."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT invited_by, invite_rewarded FROM users WHERE user_id=?",
                (user_id,),
            ) as c:
                row = await c.fetchone()
            if not row or not row["invited_by"] or row["invite_rewarded"]:
                return None
            inviter_id = row["invited_by"]
            reward = int(await self.get_setting("invite_reward", "20"))
            await db.execute(
                "UPDATE users SET points=points+? WHERE user_id=?",
                (reward, inviter_id),
            )
            await db.execute(
                "UPDATE users SET invite_rewarded=1 WHERE user_id=?",
                (user_id,),
            )
            await db.commit()
            return inviter_id

    async def get_invite_count(self, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE invited_by=? AND invite_rewarded=1",
                (user_id,),
            ) as c:
                row = await c.fetchone()
                return row[0] if row else 0

    # ── stats ────────────────────────────────────────────────────────────────

    async def get_stats(self) -> Dict:
        today = date.today().isoformat()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row

            async def scalar(sql, params=()):
                async with db.execute(sql, params) as c:
                    row = await c.fetchone()
                    return row[0] if row else 0

            return {
                "total_users":    await scalar("SELECT COUNT(*) FROM users"),
                "active_users":   await scalar("SELECT COUNT(*) FROM users WHERE is_banned=0"),
                "banned_users":   await scalar("SELECT COUNT(*) FROM users WHERE is_banned=1"),
                "total_orders":   await scalar("SELECT COUNT(*) FROM orders WHERE status='completed'"),
                "available_keys": await scalar("SELECT COUNT(*) FROM card_keys WHERE status=0"),
                "today_checkins": await scalar(
                    "SELECT COUNT(*) FROM users WHERE last_checkin=?", (today,)
                ),
            }
