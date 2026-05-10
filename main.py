import asyncio
import logging
from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN
from database.db import Database
from handlers import start, checkin, shop, profile, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-20s  %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    if not BOT_TOKEN or not API_ID or not API_HASH:
        raise SystemExit(
            "Missing required env vars. Copy .env.example to .env and fill it in."
        )

    db = Database()
    await db.init()
    logger.info("Database initialised")

    app = Client(
        "bot_session",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
    )

    start.register(app, db)
    checkin.register(app, db)
    shop.register(app, db)
    profile.register(app, db)
    admin.register(app, db)

    await app.start()
    me = await app.get_me()
    # Cache bot username on startup
    await db.set_setting("bot_username", me.username or "")
    logger.info("Bot started: @%s (id=%d)", me.username, me.id)

    await idle()
    await app.stop()
    logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
