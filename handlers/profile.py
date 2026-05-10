import logging
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ParseMode

from database.db import Database
from utils.keyboards import profile_kb, back_menu_kb
from utils.membership import check_membership

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

    # 邀请好友
    @app.on_message(filters.command("invite") | filters.regex(r"^邀请好友$"))
    async def invite_cmd(client: Client, message: Message):
        if not await check_membership(client, db, message):
            return
        user = message.from_user
        db_user = await db.get_user(user.id)
        bot_username = await db.get_setting("bot_username", "")
        invite_pts = await db.get_setting("invite_reward", "20")
        invite_count = await db.get_invite_count(user.id)
        link = f"https://t.me/{bot_username}?start=ref_{user.id}"
        await message.reply(
            f"👥 <b>邀请好友</b>\n\n"
            f"每成功邀请一位好友（对方需完成首次签到）\n"
            f"即可获得 <b>{invite_pts}</b> 积分奖励！\n\n"
            f"🔗 你的专属邀请链接：\n"
            f"<code>{link}</code>\n\n"
            f"📊 已成功邀请：<b>{invite_count}</b> 人",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    # 积分排行榜
    @app.on_message(filters.command("rank") | filters.regex(r"^积分排行$"))
    async def rank_cmd(client: Client, message: Message):
        if not await check_membership(client, db, message):
            return
        top = await db.get_leaderboard(10)
        if not top:
            await message.reply("暂无排行数据。")
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = ["🏆 <b>积分排行榜 TOP 10</b>\n"]
        for i, u in enumerate(top):
            icon = medals[i] if i < 3 else f"{i+1}."
            name = (u.get("first_name") or "") + (" " + u.get("last_name", "") if u.get("last_name") else "")
            name = name.strip() or u.get("username") or f"用户{u['user_id']}"
            lines.append(f"{icon} <a href='tg://user?id={u['user_id']}'>{name}</a>  <b>{u['points']}</b> 分")

        # 附上发消息者的排名
        if message.from_user:
            rank = await db.get_user_rank(message.from_user.id)
            db_user = await db.get_user(message.from_user.id)
            if db_user:
                lines.append(f"\n📍 你的排名：第 <b>{rank}</b> 名  {db_user['points']} 分")

        await message.reply("\n".join(lines), parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True)

    # 群内查积分：/points
    @app.on_message(filters.command("points") | filters.regex(r"^我的积分$"))
    async def points_cmd(client: Client, message: Message):
        if not await check_membership(client, db, message):
            return
        user = message.from_user
        db_user = await db.get_user(user.id)
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
