import random
import logging
from datetime import date
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ParseMode, ChatType

from database.db import Database
from utils.keyboards import back_menu_kb

logger = logging.getLogger(__name__)


def register(app: Client, db: Database):

    async def _do_checkin(client, source):
        is_cb = isinstance(source, CallbackQuery)
        is_private = is_cb or (
            isinstance(source, Message) and source.chat.type == ChatType.PRIVATE
        )
        user = source.from_user

        db_user = await db.get_user(user.id)
        if not db_user:
            msg = "请先私聊机器人发送 /start 注册后再签到。"
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

        today = date.today().isoformat()
        custom_buttons = await db.get_custom_buttons()
        kb = back_menu_kb(custom_buttons) if is_private else None

        if db_user.get("last_checkin") == today:
            text = (
                f"⏰ <b>您今天已经签到过了！</b>\n\n"
                f"💰 当前积分：<b>{db_user['points']}</b> 分\n"
                f"📅 累计签到：<b>{db_user['checkin_count']}</b> 次\n\n"
                f"明天再来吧～"
            )
            if is_cb:
                await source.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
                await source.answer("今天已签到！", show_alert=True)
            else:
                await source.reply(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return

        reward_min = int(await db.get_setting("reward_min", "5"))
        reward_max = int(await db.get_setting("reward_max", "20"))
        points = random.randint(reward_min, reward_max)

        success = await db.do_checkin(user.id, points)
        if not success:
            msg = "⏰ 您今天已经签到过了，明天再来！"
            if is_cb:
                await source.answer(msg, show_alert=True)
            else:
                await source.reply(msg)
            return

        # 首次签到 → 触发邀请奖励
        if db_user.get("checkin_count", 0) == 0:
            inviter_id = await db.try_give_invite_reward(user.id)
            if inviter_id:
                invite_pts = int(await db.get_setting("invite_reward", "20"))
                try:
                    await client.send_message(
                        inviter_id,
                        f"🎉 您邀请的好友 "
                        f"<a href='tg://user?id={user.id}'>"
                        f"{user.first_name or '新用户'}</a> "
                        f"已完成首次签到！\n"
                        f"💰 奖励积分：<b>+{invite_pts}</b>",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass

        db_user = await db.get_user(user.id)
        text = (
            f"✅ <b>签到成功！</b>\n\n"
            f"🎁 本次获得：<b>+{points}</b> 积分\n"
            f"💰 当前总积分：<b>{db_user['points']}</b> 分\n"
            f"📅 累计签到：<b>{db_user['checkin_count']}</b> 次\n\n"
            f"明天继续来签到哦～"
        )
        if is_cb:
            await source.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            await source.answer(f"签到成功！获得 {points} 积分 🎉")
        else:
            await source.reply(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    # 群内和私聊都支持
    @app.on_message(filters.command("checkin") | filters.regex(r"^签到$"))
    async def checkin_cmd(client: Client, message: Message):
        await _do_checkin(client, message)

    @app.on_callback_query(filters.regex(r"^checkin$"))
    async def checkin_cb(client: Client, query: CallbackQuery):
        await _do_checkin(client, query)
