import logging
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ChatMemberStatus, ParseMode
from pyrogram.errors import UserNotParticipant, PeerIdInvalid, ChatAdminRequired

from database.db import Database
from utils.keyboards import main_menu_kb, join_channels_kb, back_menu_kb

logger = logging.getLogger(__name__)

_MAIN_MENU = (
    "🏠 <b>主菜单</b>\n\n"
    "欢迎回来，{name}！\n"
    "💰 当前积分：<b>{points}</b> 分\n\n"
    "请选择功能："
)

_NEED_JOIN = (
    "⚠️ <b>请先加入以下所有频道</b>\n\n"
    "{welcome_text}\n\n"
    "加入完成后点击「✅ 我已加入」按钮。"
)

_BANNED = "⛔ 您已被封禁，无法使用本机器人。"

# Statuses that mean "not in channel"
_NOT_IN = {ChatMemberStatus.LEFT, ChatMemberStatus.BANNED}


def register(app: Client, db: Database):

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _bot_username(client: Client) -> str:
        username = await db.get_setting("bot_username")
        if not username:
            me = await client.get_me()
            username = me.username or ""
            await db.set_setting("bot_username", username)
        return username

    async def _check_channels(client: Client, user_id: int,
                               channels: list) -> list:
        """Return list of channels the user has NOT joined."""
        missing = []
        for ch in channels:
            try:
                member = await client.get_chat_member(ch["channel_id"], user_id)
                if member.status in _NOT_IN:
                    missing.append(ch)
            except UserNotParticipant:
                missing.append(ch)
            except (PeerIdInvalid, ChatAdminRequired) as e:
                logger.warning("Cannot check channel %s: %s", ch["channel_id"], e)
            except Exception as e:
                logger.error("Unexpected error for channel %s: %s", ch["channel_id"], e)
        return missing

    async def _show_main_menu(client, source, db_user: dict):
        is_cb = isinstance(source, CallbackQuery)
        custom_buttons = await db.get_custom_buttons()
        name = db_user.get("first_name") or "用户"
        text = _MAIN_MENU.format(name=name, points=db_user["points"])
        kb = main_menu_kb(custom_buttons)
        if is_cb:
            await source.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            await source.answer()
        else:
            await source.reply(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    async def _show_join_prompt(client, source, channels: list):
        is_cb = isinstance(source, CallbackQuery)
        welcome_text = await db.get_setting(
            "welcome_text", "请加入以下所有频道后继续使用。"
        )
        folder_link = await db.get_setting("folder_link", "")
        text = _NEED_JOIN.format(welcome_text=welcome_text)
        kb = join_channels_kb(channels, folder_link)
        if is_cb:
            await source.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            await source.answer("请先加入所有频道！", show_alert=True)
        else:
            await source.reply(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    async def _entry(client: Client, source, user_id: int):
        """Verify channels then show menu or join prompt."""
        db_user = await db.get_user(user_id)
        if not db_user:
            return
        if db_user["is_banned"]:
            is_cb = isinstance(source, CallbackQuery)
            if is_cb:
                await source.answer(_BANNED, show_alert=True)
            else:
                await source.reply(_BANNED)
            return
        channels = await db.get_channels()
        missing = await _check_channels(client, user_id, channels) if channels else []
        if missing:
            await _show_join_prompt(client, source, missing)
        else:
            # Refresh points before showing menu
            db_user = await db.get_user(user_id)
            await _show_main_menu(client, source, db_user)

    # ── /start ───────────────────────────────────────────────────────────────

    @app.on_message(filters.command("start") & filters.private)
    async def start_handler(client: Client, message: Message):
        user = message.from_user
        await db.upsert_user(
            user.id,
            user.username or "",
            user.first_name or "",
            user.last_name or "",
        )

        # Deep-link: /start order_<order_id>
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith("order_"):
            order_id = parts[1][6:]
            await _deliver_key(client, message, order_id, user.id)
            return

        await _entry(client, message, user.id)

    # ── key delivery (deep link) ──────────────────────────────────────────────

    async def _deliver_key(client: Client, message: Message,
                           order_id: str, user_id: int):
        order = await db.get_order(order_id)
        if not order:
            await message.reply("❌ 订单不存在或已失效。")
            return
        if order["user_id"] != user_id:
            await message.reply("❌ 此链接不属于您的订单，无法领取。")
            return

        custom_buttons = await db.get_custom_buttons()
        await message.reply(
            f"🎉 <b>卡密领取成功！</b>\n\n"
            f"📦 商品：<b>{order['product_name']}</b>\n"
            f"🕐 兑换时间：{str(order['created_at'])[:16]}\n\n"
            f"🔑 您的卡密：\n"
            f"<code>{order['key_value']}</code>\n\n"
            f"请妥善保管，切勿泄露。",
            reply_markup=back_menu_kb(custom_buttons),
            parse_mode=ParseMode.HTML,
        )
        if order["status"] == "pending":
            await db.complete_order(order_id)

    # ── callbacks ─────────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^verify_join$"))
    async def verify_join_cb(client: Client, query: CallbackQuery):
        user = query.from_user
        await db.upsert_user(
            user.id,
            user.username or "",
            user.first_name or "",
            user.last_name or "",
        )
        await _entry(client, query, user.id)

    @app.on_callback_query(filters.regex(r"^main_menu$"))
    async def main_menu_cb(client: Client, query: CallbackQuery):
        user = query.from_user
        db_user = await db.get_user(user.id)
        if not db_user:
            await query.answer("请先发送 /start", show_alert=True)
            return
        await _entry(client, query, user.id)
