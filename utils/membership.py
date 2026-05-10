import logging
from pyrogram import Client
from pyrogram.enums import ChatMemberStatus, ParseMode
from pyrogram.errors import UserNotParticipant, PeerIdInvalid, ChatAdminRequired
from pyrogram.types import Message, CallbackQuery

from database.db import Database
from utils.keyboards import join_channels_kb

logger = logging.getLogger(__name__)
_NOT_IN = {ChatMemberStatus.LEFT, ChatMemberStatus.BANNED}


async def check_membership(client: Client, db: Database, source) -> bool:
    """
    Returns True if user passes all checks (registered, not banned, in all channels).
    Sends the appropriate error message and returns False otherwise.
    """
    is_cb = isinstance(source, CallbackQuery)
    user = source.from_user

    db_user = await db.get_user(user.id)
    if not db_user:
        msg = "请先私聊机器人发送 /start 注册。"
        if is_cb:
            await source.answer(msg, show_alert=True)
        else:
            await source.reply(msg)
        return False

    if db_user["is_banned"]:
        msg = "⛔ 您已被封禁，无法使用此功能。"
        if is_cb:
            await source.answer(msg, show_alert=True)
        else:
            await source.reply(msg)
        return False

    channels = await db.get_channels()
    if not channels:
        return True

    missing = []
    for ch in channels:
        try:
            member = await client.get_chat_member(ch["channel_id"], user.id)
            if member.status in _NOT_IN:
                missing.append(ch)
        except UserNotParticipant:
            missing.append(ch)
        except Exception as e:
            # 无法检查时保守处理：视为未加入
            logger.warning("Cannot check channel %s: %s — treating as not joined", ch["channel_id"], e)
            missing.append(ch)

    if missing:
        names = "、".join(ch["channel_name"] for ch in missing)
        folder_link = await db.get_setting("folder_link", "")
        text = (
            f"⚠️ <b>请先加入以下频道才能使用此功能</b>\n\n"
            f"未加入：{names}\n\n"
            f"加入后点击「✅ 我已加入」按钮。"
        )
        kb = join_channels_kb(missing, folder_link)
        if is_cb:
            try:
                await source.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            except Exception:
                pass
            await source.answer("❌ 请先加入所有频道！", show_alert=True)
        else:
            await source.reply(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return False

    return True
