from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict


def _ad_rows(custom_buttons: List[Dict]) -> List[List[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(b["text"], url=b["url"])]
        for b in (custom_buttons or [])
    ]


def main_menu_kb(custom_buttons: List[Dict] = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📅 每日签到", callback_data="checkin"),
            InlineKeyboardButton("🛍️ 积分商城", callback_data="shop"),
        ],
        [InlineKeyboardButton("👤 个人中心", callback_data="profile")],
    ]
    rows.extend(_ad_rows(custom_buttons))
    return InlineKeyboardMarkup(rows)


def join_channels_kb(channels: List[Dict],
                     folder_link: str = "") -> InlineKeyboardMarkup:
    rows = []
    if folder_link:
        rows.append(
            [InlineKeyboardButton("📁 一键加入所有频道", url=folder_link)]
        )
    for ch in channels:
        rows.append(
            [InlineKeyboardButton(f"➡️ {ch['channel_name']}", url=ch["channel_url"])]
        )
    rows.append(
        [InlineKeyboardButton("✅ 我已加入", callback_data="verify_join")]
    )
    return InlineKeyboardMarkup(rows)


def shop_kb(products: List[Dict],
            custom_buttons: List[Dict] = None) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        stock_label = f"({p['stock']}件)" if p["stock"] > 0 else "(缺货)"
        rows.append([
            InlineKeyboardButton(
                f"🎁 {p['name']}  {p['points_cost']}积分 {stock_label}",
                callback_data=f"product_{p['id']}",
            )
        ])
    rows.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")])
    rows.extend(_ad_rows(custom_buttons))
    return InlineKeyboardMarkup(rows)


def product_kb(product_id: int, can_redeem: bool,
               custom_buttons: List[Dict] = None) -> InlineKeyboardMarkup:
    if can_redeem:
        action_row = [InlineKeyboardButton("✅ 确认兑换", callback_data=f"redeem_{product_id}")]
    else:
        action_row = [InlineKeyboardButton("❌ 无法兑换", callback_data="redeem_blocked")]
    rows = [action_row,
            [InlineKeyboardButton("🔙 返回商城", callback_data="shop")]]
    rows.extend(_ad_rows(custom_buttons))
    return InlineKeyboardMarkup(rows)


def profile_kb(custom_buttons: List[Dict] = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📋 兑换记录", callback_data="order_history")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")],
    ]
    rows.extend(_ad_rows(custom_buttons))
    return InlineKeyboardMarkup(rows)


def group_announce_kb(bot_username: str, order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🎁 点击领取卡密",
            url=f"https://t.me/{bot_username}?start=order_{order_id}",
        )
    ]])


def back_menu_kb(custom_buttons: List[Dict] = None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="main_menu")]]
    rows.extend(_ad_rows(custom_buttons))
    return InlineKeyboardMarkup(rows)
