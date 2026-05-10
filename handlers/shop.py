import logging
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.enums import ChatType, ParseMode

from database.db import Database
from utils.keyboards import (
    shop_kb, product_kb, group_announce_kb, back_menu_kb
)

logger = logging.getLogger(__name__)


def register(app: Client, db: Database):

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _bot_username(client: Client) -> str:
        username = await db.get_setting("bot_username")
        if not username:
            me = await client.get_me()
            username = me.username or ""
            await db.set_setting("bot_username", username)
        return username

    async def _show_shop(client, source):
        is_cb = isinstance(source, CallbackQuery)
        products = await db.get_products(active_only=True)
        custom_buttons = await db.get_custom_buttons()

        if not products:
            text = "🛒 <b>积分商城</b>\n\n暂无上架商品，请稍后再来。"
            kb = back_menu_kb(custom_buttons)
        else:
            text = "🛒 <b>积分商城</b>\n\n以下是当前可兑换的商品，点击查看详情："
            kb = shop_kb(products, custom_buttons)

        if is_cb:
            await source.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            await source.answer()
        else:
            await source.reply(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    # ── /shop command (works in group or private) ─────────────────────────────

    @app.on_message(filters.command("shop") | filters.regex(r"^兑换$"))
    async def shop_cmd(client: Client, message: Message):
        db_user = await db.get_user(message.from_user.id)
        if not db_user:
            await message.reply("请先私聊机器人发送 /start 注册。")
            return
        if db_user["is_banned"]:
            await message.reply("⛔ 您已被封禁，无法使用此功能。")
            return
        await _show_shop(client, message)

    @app.on_callback_query(filters.regex(r"^shop$"))
    async def shop_cb(client: Client, query: CallbackQuery):
        db_user = await db.get_user(query.from_user.id)
        if not db_user or db_user["is_banned"]:
            await query.answer("⛔ 无权访问", show_alert=True)
            return
        await _show_shop(client, query)

    # ── product detail ────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^product_(\d+)$"))
    async def product_detail_cb(client: Client, query: CallbackQuery):
        product_id = int(query.matches[0].group(1))
        db_user = await db.get_user(query.from_user.id)
        if not db_user or db_user["is_banned"]:
            await query.answer("⛔ 无权访问", show_alert=True)
            return

        product = await db.get_product(product_id)
        if not product:
            await query.answer("商品不存在", show_alert=True)
            return

        custom_buttons = await db.get_custom_buttons()
        has_stock = product["stock"] > 0
        can_afford = db_user["points"] >= product["points_cost"]

        stock_text = (
            f"📦 库存：<b>{product['stock']}</b> 件"
            if has_stock
            else "📦 库存：<b>已售罄</b>"
        )
        afford_note = ""
        if has_stock and not can_afford:
            afford_note = (
                f"\n\n⚠️ 积分不足（需要 {product['points_cost']} 分，"
                f"您目前有 {db_user['points']} 分）"
            )

        text = (
            f"🎁 <b>{product['name']}</b>\n\n"
            f"📝 {product['description'] or '暂无描述'}\n\n"
            f"💎 分类：{product['category']}\n"
            f"💰 所需积分：<b>{product['points_cost']}</b> 分\n"
            f"{stock_text}"
            f"{afford_note}"
        )
        can_redeem = has_stock and can_afford
        await query.message.edit_text(
            text,
            reply_markup=product_kb(product_id, can_redeem, custom_buttons),
            parse_mode=ParseMode.HTML,
        )
        await query.answer()

    # ── redeem ────────────────────────────────────────────────────────────────

    @app.on_callback_query(filters.regex(r"^redeem_(\d+)$"))
    async def redeem_cb(client: Client, query: CallbackQuery):
        product_id = int(query.matches[0].group(1))
        user = query.from_user

        db_user = await db.get_user(user.id)
        if not db_user or db_user["is_banned"]:
            await query.answer("⛔ 无权访问", show_alert=True)
            return

        product = await db.get_product(product_id)
        if not product:
            await query.answer("商品不存在", show_alert=True)
            return
        if product["stock"] <= 0:
            await query.answer("❌ 库存不足！", show_alert=True)
            return
        if db_user["points"] < product["points_cost"]:
            await query.answer(
                f"❌ 积分不足！需要 {product['points_cost']} 分，"
                f"您只有 {db_user['points']} 分",
                show_alert=True,
            )
            return

        # Reserve key (race-safe: one key per call, DB is file-based)
        key = await db.get_available_key(product_id)
        if not key:
            await query.answer("❌ 库存刚刚售罄！", show_alert=True)
            return

        # Deduct points and mark key
        await db.update_points(user.id, -product["points_cost"])
        await db.use_key(key["id"], user.id)

        # Create order
        order_id = await db.create_order(user.id, product_id, key["id"])

        bot_username = await _bot_username(client)
        group_id_str = await db.get_setting("group_id", "0")
        group_msg_id = None

        user_name = user.first_name or user.username or f"用户{user.id}"
        announce_text = (
            f"🎉 <b>兑换公告</b>\n\n"
            f"👤 用户：<a href='tg://user?id={user.id}'>{user_name}</a>\n"
            f"🎁 商品：<b>{product['name']}</b>\n"
            f"💰 消耗积分：<b>{product['points_cost']}</b>\n\n"
            f"恭喜兑换成功！点击下方按钮领取卡密 👇"
        )
        announce_kb = group_announce_kb(bot_username, order_id)

        # Post in announcement group
        if group_id_str and group_id_str != "0":
            try:
                msg = await client.send_message(
                    int(group_id_str),
                    announce_text,
                    reply_markup=announce_kb,
                    parse_mode=ParseMode.HTML,
                )
                group_msg_id = msg.id
            except Exception as e:
                logger.error("Failed to post announcement: %s", e)

        await db.complete_order(order_id, group_msg_id)

        updated_user = await db.get_user(user.id)
        custom_buttons = await db.get_custom_buttons()

        # If in private chat → deliver key directly
        if query.message.chat.type == ChatType.PRIVATE:
            await query.message.edit_text(
                f"✅ <b>兑换成功！</b>\n\n"
                f"🎁 商品：<b>{product['name']}</b>\n"
                f"💰 消耗积分：<b>{product['points_cost']}</b>\n"
                f"💳 剩余积分：<b>{updated_user['points']}</b>\n\n"
                f"🔑 您的卡密：\n"
                f"<code>{key['key_value']}</code>\n\n"
                f"请妥善保管，切勿泄露。",
                reply_markup=back_menu_kb(custom_buttons),
                parse_mode=ParseMode.HTML,
            )
        else:
            # In group → post compact success and direct user to private
            await query.message.reply(
                f"✅ <b>{user_name}</b> 兑换成功！\n\n"
                f"💳 剩余积分：<b>{updated_user['points']}</b>\n\n"
                f"请点击下方按钮前往私聊领取卡密：",
                reply_markup=announce_kb,
                parse_mode=ParseMode.HTML,
            )

        await query.answer("兑换成功！🎉")

    @app.on_callback_query(filters.regex(r"^redeem_blocked$"))
    async def redeem_blocked_cb(client: Client, query: CallbackQuery):
        await query.answer("积分不足或库存售罄，无法兑换！", show_alert=True)
