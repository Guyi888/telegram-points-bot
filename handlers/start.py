import logging
import random
import time
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
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
_NOT_IN = {ChatMemberStatus.LEFT, ChatMemberStatus.BANNED}

# captcha state: user_id -> {answer, expires, param}
_captcha: dict[int, dict] = {}
_CAPTCHA_TTL = 120  # seconds


def _make_captcha() -> tuple[str, int, list[int]]:
    """Return (question_text, correct_answer, [4 shuffled choices])."""
    ops = [
        ("+", lambda a, b: a + b),
        ("-", lambda a, b: a - b),
        ("×", lambda a, b: a * b),
    ]
    op_sym, op_fn = random.choice(ops)
    if op_sym == "×":
        a, b = random.randint(2, 9), random.randint(2, 9)
    elif op_sym == "-":
        a, b = random.randint(5, 20), random.randint(1, 5)
    else:
        a, b = random.randint(1, 15), random.randint(1, 15)
    answer = op_fn(a, b)
    question = f"{a} {op_sym} {b} = ?"
    # 3 wrong answers (unique, different from correct)
    wrongs = set()
    while len(wrongs) < 3:
        delta = random.choice([-3, -2, -1, 1, 2, 3])
        w = answer + delta
        if w != answer and w >= 0:
            wrongs.add(w)
    choices = list(wrongs) + [answer]
    random.shuffle(choices)
    return question, answer, choices


def _captcha_kb(choices: list[int]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(str(c), callback_data=f"cap_{c}")
        for c in choices
    ]])


def register(app: Client, db: Database):

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _check_channels(client, user_id, channels):
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

    async def _show_main_menu(client, source, db_user):
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

    async def _show_join_prompt(client, source, channels):
        is_cb = isinstance(source, CallbackQuery)
        welcome_text = await db.get_setting("welcome_text", "请加入以下所有频道后继续使用。")
        folder_link = await db.get_setting("folder_link", "")
        text = _NEED_JOIN.format(welcome_text=welcome_text)
        kb = join_channels_kb(channels, folder_link)
        if is_cb:
            await source.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            await source.answer("请先加入所有频道！", show_alert=True)
        else:
            await source.reply(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    async def _entry(client, source, user_id):
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
            db_user = await db.get_user(user_id)
            await _show_main_menu(client, source, db_user)

    async def _send_captcha(message: Message, param: str = ""):
        """Send math captcha to new user. param = deep-link payload to resume after."""
        user_id = message.from_user.id
        question, answer, choices = _make_captcha()
        _captcha[user_id] = {
            "answer": answer,
            "expires": time.time() + _CAPTCHA_TTL,
            "param": param,
        }
        await message.reply(
            f"🤖 <b>请完成验证</b>\n\n"
            f"请点击正确答案：\n\n"
            f"<b>{question}</b>\n\n"
            f"⏳ 请在 {_CAPTCHA_TTL} 秒内完成",
            reply_markup=_captcha_kb(choices),
            parse_mode=ParseMode.HTML,
        )

    # ── /start ───────────────────────────────────────────────────────────────

    @app.on_message(filters.command("start") & filters.private)
    async def start_handler(client: Client, message: Message):
        user = message.from_user
        parts = message.text.split(maxsplit=1)
        param = parts[1] if len(parts) > 1 else ""

        existing = await db.get_user(user.id)

        # Already registered → skip captcha
        if existing:
            if param.startswith("order_"):
                await _deliver_key(client, message, param[6:], user.id)
                return
            # Still record inviter if not already set
            if param.startswith("ref_"):
                inviter_id_str = param[4:]
                if inviter_id_str.isdigit():
                    inviter_id = int(inviter_id_str)
                    if inviter_id != user.id:
                        await db.set_inviter(user.id, inviter_id)
            await _entry(client, message, user.id)
            return

        # New user → captcha first
        await _send_captcha(message, param)

    # ── captcha callback ──────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^cap_(-?\d+)$"))
    async def captcha_cb(client: Client, query: CallbackQuery):
        user = query.from_user
        state = _captcha.get(user.id)

        if not state:
            await query.answer("验证已过期，请重新发送 /start", show_alert=True)
            return

        if time.time() > state["expires"]:
            del _captcha[user.id]
            await query.answer("验证超时，请重新发送 /start", show_alert=True)
            await query.message.delete()
            return

        chosen = int(query.matches[0].group(1))

        if chosen != state["answer"]:
            # Wrong — regenerate question
            question, answer, choices = _make_captcha()
            _captcha[user.id]["answer"] = answer
            _captcha[user.id]["expires"] = time.time() + _CAPTCHA_TTL
            await query.answer("❌ 答案错误，请重试！", show_alert=True)
            await query.message.edit_text(
                f"🤖 <b>请完成验证</b>\n\n"
                f"请点击正确答案：\n\n"
                f"<b>{question}</b>\n\n"
                f"⏳ 请在 {_CAPTCHA_TTL} 秒内完成",
                reply_markup=_captcha_kb(choices),
                parse_mode=ParseMode.HTML,
            )
            return

        # Correct — register user and continue
        del _captcha[user.id]
        param = state.get("param", "")

        await db.upsert_user(
            user.id,
            user.username or "",
            user.first_name or "",
            user.last_name or "",
        )

        # Handle ref deep-link
        if param.startswith("ref_"):
            inviter_id_str = param[4:]
            if inviter_id_str.isdigit():
                inviter_id = int(inviter_id_str)
                if inviter_id != user.id:
                    await db.set_inviter(user.id, inviter_id)

        await query.answer("✅ 验证通过！", show_alert=False)
        await query.message.delete()

        # Send fresh message — cannot edit deleted captcha message
        if param.startswith("order_"):
            await _deliver_key_new(client, user.id, param[6:])
            return
        await _entry_new(client, user.id)

    # ── post-captcha: send brand-new messages ────────────────────────────────

    async def _entry_new(client: Client, user_id: int):
        """Used after captcha: send main menu or join prompt as a new message."""
        db_user = await db.get_user(user_id)
        if not db_user:
            return
        channels = await db.get_channels()
        missing = await _check_channels(client, user_id, channels) if channels else []
        if missing:
            welcome_text = await db.get_setting("welcome_text", "请加入以下所有频道后继续使用。")
            folder_link = await db.get_setting("folder_link", "")
            text = _NEED_JOIN.format(welcome_text=welcome_text)
            kb = join_channels_kb(missing, folder_link)
        else:
            db_user = await db.get_user(user_id)
            custom_buttons = await db.get_custom_buttons()
            name = db_user.get("first_name") or "用户"
            text = _MAIN_MENU.format(name=name, points=db_user["points"])
            kb = main_menu_kb(custom_buttons)
        await client.send_message(user_id, text, reply_markup=kb, parse_mode=ParseMode.HTML)

    async def _deliver_key_new(client: Client, user_id: int, order_id: str):
        """Used after captcha: deliver key via new message."""
        order = await db.get_order(order_id)
        if not order:
            await client.send_message(user_id, "❌ 订单不存在或已失效。")
            return
        if order["user_id"] != user_id:
            await client.send_message(user_id, "❌ 此链接不属于您的订单，无法领取。")
            return
        custom_buttons = await db.get_custom_buttons()
        await client.send_message(
            user_id,
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

    # ── key delivery ──────────────────────────────────────────────────────────

    async def _deliver_key(client, source, order_id, user_id):
        order = await db.get_order(order_id)
        if not order:
            text = "❌ 订单不存在或已失效。"
            if isinstance(source, CallbackQuery):
                await source.message.reply(text)
            else:
                await source.reply(text)
            return
        if order["user_id"] != user_id:
            text = "❌ 此链接不属于您的订单，无法领取。"
            if isinstance(source, CallbackQuery):
                await source.message.reply(text)
            else:
                await source.reply(text)
            return

        custom_buttons = await db.get_custom_buttons()
        msg_source = source.message if isinstance(source, CallbackQuery) else source
        await msg_source.reply(
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

    # ── other callbacks ───────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^verify_join$"))
    async def verify_join_cb(client: Client, query: CallbackQuery):
        user = query.from_user
        await db.upsert_user(
            user.id, user.username or "", user.first_name or "", user.last_name or ""
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
