import logging
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ParseMode

from database.db import Database
from utils.keyboards import profile_kb, back_menu_kb

logger = logging.getLogger(__name__)


def register(app: Client, db: Database):

    async def _show_profile(client, source):
        is_cb = isinstance(source, CallbackQuery)
        user = source.from_user

        db_user = await db.get_user(user.id)
        if not db_user:
            msg = "请先发送 /start 开始使用。"
            if is_cb:
                await source.answer(msg, show_alert=True)
            else:
                await source.reply(msg)
            return
        if db_user["is_banned"]:
            msg = "⛔ 您已被封禁，无法使用此功能。"
            if is_cb:
                await source.answer(msg, show_alert=True)
            else:
                await source.reply(msg)
            return

        custom_buttons = await db.get_custom_buttons()
        full_name = " ".join(
            filter(None, [db_user.get("first_name", ""), db_user.get("last_name", "")])
        ).strip() or "未设置"
        username_text = (
            f"@{db_user['username']}" if db_user.get("username") else "未设置"
        )
        joined = str(db_user.get("joined_at", ""))[:10] or "未知"

        text = (
            f"👤 <b>个人中心</b>\n\n"
            f"🆔 用户ID：<code>{db_user['user_id']}</code>\n"
            f"👤 用户名：{username_text}\n"
            f"📄 昵称：{full_name}\n"
            f"🔢 积分余额：<b>{db_user['points']}</b> 分\n"
            f"🎟 累计签到：<b>{db_user['checkin_count']}</b> 次\n"
            f"📅 上次签到：{db_user.get('last_checkin') or '从未签到'}\n"
            f"⏰ 注册时间：{joined}"
        )
        if is_cb:
            await source.message.edit_text(
                text, reply_markup=profile_kb(custom_buttons), parse_mode=ParseMode.HTML
            )
            await source.answer()
        else:
            await source.reply(
                text, reply_markup=profile_kb(custom_buttons), parse_mode=ParseMode.HTML
            )

    async def _show_orders(client, query: CallbackQuery):
        user = query.from_user
        orders = await db.get_user_orders(user.id)
        custom_buttons = await db.get_custom_buttons()

        if not orders:
            text = "📋 <b>兑换记录</b>\n\n暂无兑换记录。"
        else:
            text = "📋 <b>兑换记录（最近10条）</b>\n\n"
            for i, o in enumerate(orders, 1):
                text += (
                    f"{i}. 🎁 {o['product_name']}\n"
                    f"   📅 {str(o['created_at'])[:10]}\n"
                    f"   🆔 <code>{o['order_id']}</code>\n\n"
                )

        await query.message.edit_text(
            text, reply_markup=back_menu_kb(custom_buttons), parse_mode=ParseMode.HTML
        )
        await query.answer()

    @app.on_message(filters.command(["profile", "me"]) & filters.private)
    async def profile_cmd(client: Client, message: Message):
        await _show_profile(client, message)

    # 群内查积分：/points
    @app.on_message(filters.command("points") | filters.regex(r"^我的积分$"))
    async def points_cmd(client: Client, message: Message):
        user = message.from_user
        db_user = await db.get_user(user.id)
        if not db_user:
            await message.reply("请先私聊机器人发送 /start 注册。")
            return
        if db_user["is_banned"]:
            await message.reply("⛔ 您已被封禁。")
            return
        name = user.first_name or user.username or "用户"
        await message.reply(
            f"👤 <b>{name}</b>\n"
            f"💰 积分余额：<b>{db_user['points']}</b> 分\n"
            f"📅 累计签到：<b>{db_user['checkin_count']}</b> 次",
            parse_mode=ParseMode.HTML,
        )

    @app.on_callback_query(filters.regex(r"^profile$"))
    async def profile_cb(client: Client, query: CallbackQuery):
        await _show_profile(client, query)

    @app.on_callback_query(filters.regex(r"^order_history$"))
    async def order_history_cb(client: Client, query: CallbackQuery):
        await _show_orders(client, query)
