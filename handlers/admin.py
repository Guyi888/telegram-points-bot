import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

from database.db import Database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)

# In-memory state: admin user_id -> product_id awaiting key file
_pending_import: dict[int, int] = {}


def _admin(flt, client, message: Message):
    return bool(message.from_user and message.from_user.id in ADMIN_IDS)


admin_only = filters.create(_admin)


def register(app: Client, db: Database):

    # ── panel ────────────────────────────────────────────────────────────────

    @app.on_message(filters.command("admin") & filters.private & admin_only)
    async def admin_panel(client: Client, message: Message):
        await message.reply(
            "⚙️ <b>管理员面板</b>\n\n"
            "<b>📦 商品管理</b>\n"
            "/addproduct &lt;名称&gt; &lt;积分&gt; &lt;分类&gt; [描述]\n"
            "/products — 商品列表\n"
            "/importkeys &lt;商品ID&gt; — 导入卡密（发送.txt文件）\n\n"
            "<b>👥 用户管理</b>\n"
            "/addpoints &lt;用户ID&gt; &lt;积分&gt;\n"
            "/deductpoints &lt;用户ID&gt; &lt;积分&gt;\n"
            "/setpoints &lt;用户ID&gt; &lt;积分&gt;\n"
            "/ban &lt;用户ID&gt; / /unban &lt;用户ID&gt;\n"
            "/userinfo &lt;用户ID&gt;\n\n"
            "<b>📢 频道管理</b>\n"
            "/addchannel &lt;频道ID&gt; &lt;名称&gt; &lt;链接&gt;\n"
            "/removechannel &lt;频道ID&gt;\n"
            "/channels — 频道列表\n\n"
            "<b>⚙️ 系统设置</b>\n"
            "/setreward &lt;最小值&gt; &lt;最大值&gt;\n"
            "/setgroup &lt;群组ID&gt; — 设置公告群\n"
            "/setfolder &lt;链接&gt; — 频道文件夹链接\n"
            "/addbutton &lt;文字&gt; &lt;链接&gt;\n"
            "/removebutton &lt;ID&gt;\n"
            "/buttons — 按钮列表\n\n"
            "<b>📊 统计</b>\n"
            "/stats",
            parse_mode=ParseMode.HTML,
        )

    # ── products ─────────────────────────────────────────────────────────────

    @app.on_message(filters.command("addproduct") & filters.private & admin_only)
    async def add_product(client: Client, message: Message):
        # /addproduct <name> <cost> <category> [description]
        parts = message.text.split(maxsplit=4)
        if len(parts) < 4:
            await message.reply(
                "用法：/addproduct &lt;名称&gt; &lt;积分&gt; &lt;分类&gt; [描述]\n"
                "示例：/addproduct 月卡VIP 100 会员 高级月卡一张",
                parse_mode=ParseMode.HTML,
            )
            return
        name, cost_str, category = parts[1], parts[2], parts[3]
        description = parts[4] if len(parts) > 4 else ""
        if not cost_str.isdigit():
            await message.reply("❌ 积分必须是正整数")
            return
        product_id = await db.add_product(name, description, int(cost_str), category)
        await message.reply(
            f"✅ 商品添加成功！\n\n"
            f"🆔 商品ID：<code>{product_id}</code>\n"
            f"📦 名称：{name}\n"
            f"💰 积分：{cost_str}\n"
            f"🏷️ 分类：{category}\n\n"
            f"使用 /importkeys {product_id} 导入卡密",
            parse_mode=ParseMode.HTML,
        )

    @app.on_message(filters.command("products") & filters.private & admin_only)
    async def list_products(client: Client, message: Message):
        products = await db.get_products(active_only=False)
        if not products:
            await message.reply("暂无商品。")
            return
        lines = ["📦 <b>商品列表</b>\n"]
        for p in products:
            status = "✅ 上架" if p["is_active"] else "❌ 下架"
            lines.append(
                f"ID <code>{p['id']}</code>  {status}\n"
                f"  {p['name']} ({p['category']})\n"
                f"  💰 {p['points_cost']}积分  📦 库存 {p['stock']}\n"
            )
        await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)

    @app.on_message(filters.command("importkeys") & filters.private & admin_only)
    async def import_keys_start(client: Client, message: Message):
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.reply("用法：/importkeys &lt;商品ID&gt;", parse_mode=ParseMode.HTML)
            return
        product_id = int(parts[1])
        product = await db.get_product(product_id)
        if not product:
            await message.reply("❌ 商品不存在")
            return
        _pending_import[message.from_user.id] = product_id
        await message.reply(
            f"✅ 准备为商品 <b>{product['name']}</b> (ID:{product_id}) 导入卡密\n\n"
            f"请发送一个 .txt 文件，每行一个卡密。",
            parse_mode=ParseMode.HTML,
        )

    @app.on_message(filters.document & filters.private & admin_only)
    async def handle_key_file(client: Client, message: Message):
        uid = message.from_user.id
        if uid not in _pending_import:
            return
        product_id = _pending_import[uid]
        doc = message.document
        if not (doc.file_name or "").lower().endswith(".txt"):
            await message.reply("❌ 请发送 .txt 格式的文件")
            return
        if doc.file_size > 5 * 1024 * 1024:
            await message.reply("❌ 文件过大（上限 5 MB）")
            return

        file_io = await client.download_media(message, in_memory=True)
        try:
            content = file_io.getvalue().decode("utf-8")
        except UnicodeDecodeError:
            try:
                content = file_io.getvalue().decode("gbk")
            except Exception:
                await message.reply("❌ 文件编码不支持，请使用 UTF-8 或 GBK")
                return

        keys = [ln.strip() for ln in content.splitlines() if ln.strip()]
        if not keys:
            await message.reply("❌ 文件中没有有效卡密")
            return

        product = await db.get_product(product_id)
        count = await db.import_keys(product_id, keys)
        del _pending_import[uid]
        await message.reply(
            f"✅ 卡密导入成功！\n\n"
            f"📦 商品：{product['name']}\n"
            f"📥 导入数量：<b>{count}</b> 个",
            parse_mode=ParseMode.HTML,
        )

    # ── user management ───────────────────────────────────────────────────────

    async def _require_user(message: Message, parts: list, min_args: int,
                            usage: str) -> tuple:
        if len(parts) < min_args:
            await message.reply(usage, parse_mode=ParseMode.HTML)
            return None, None
        try:
            target_id = int(parts[1])
        except ValueError:
            await message.reply("❌ 用户ID必须是整数")
            return None, None
        user = await db.get_user(target_id)
        if not user:
            await message.reply("❌ 用户不存在（用户需先发过 /start）")
            return None, None
        return target_id, user

    @app.on_message(filters.command("addpoints") & filters.private & admin_only)
    async def add_points(client: Client, message: Message):
        parts = message.text.split()
        target_id, user = await _require_user(
            message, parts, 3, "用法：/addpoints &lt;用户ID&gt; &lt;积分&gt;"
        )
        if not target_id:
            return
        if not parts[2].lstrip("-").isdigit():
            await message.reply("❌ 积分必须是整数")
            return
        amount = int(parts[2])
        if amount <= 0:
            await message.reply("❌ 积分数量必须大于 0")
            return
        new_pts = await db.update_points(target_id, amount)
        await message.reply(
            f"✅ 已为用户 <code>{target_id}</code> 增加 <b>+{amount}</b> 积分\n"
            f"当前积分：<b>{new_pts}</b>",
            parse_mode=ParseMode.HTML,
        )

    @app.on_message(filters.command("deductpoints") & filters.private & admin_only)
    async def deduct_points(client: Client, message: Message):
        parts = message.text.split()
        target_id, user = await _require_user(
            message, parts, 3, "用法：/deductpoints &lt;用户ID&gt; &lt;积分&gt;"
        )
        if not target_id:
            return
        if not parts[2].lstrip("-").isdigit():
            await message.reply("❌ 积分必须是整数")
            return
        amount = int(parts[2])
        if amount <= 0:
            await message.reply("❌ 积分数量必须大于 0")
            return
        new_pts = await db.update_points(target_id, -amount)
        await message.reply(
            f"✅ 已从用户 <code>{target_id}</code> 扣除 <b>{amount}</b> 积分\n"
            f"当前积分：<b>{new_pts}</b>",
            parse_mode=ParseMode.HTML,
        )

    @app.on_message(filters.command("setpoints") & filters.private & admin_only)
    async def set_points_cmd(client: Client, message: Message):
        parts = message.text.split()
        target_id, user = await _require_user(
            message, parts, 3, "用法：/setpoints &lt;用户ID&gt; &lt;积分&gt;"
        )
        if not target_id:
            return
        if not parts[2].isdigit():
            await message.reply("❌ 积分必须是非负整数")
            return
        amount = int(parts[2])
        await db.set_points(target_id, amount)
        await message.reply(
            f"✅ 已将用户 <code>{target_id}</code> 积分设置为 <b>{amount}</b>",
            parse_mode=ParseMode.HTML,
        )

    @app.on_message(filters.command("ban") & filters.private & admin_only)
    async def ban_user_cmd(client: Client, message: Message):
        parts = message.text.split()
        target_id, user = await _require_user(
            message, parts, 2, "用法：/ban &lt;用户ID&gt;"
        )
        if not target_id:
            return
        if target_id in ADMIN_IDS:
            await message.reply("❌ 不能封禁管理员")
            return
        await db.ban_user(target_id)
        await message.reply(f"✅ 已封禁用户 <code>{target_id}</code>", parse_mode=ParseMode.HTML)

    @app.on_message(filters.command("unban") & filters.private & admin_only)
    async def unban_user_cmd(client: Client, message: Message):
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
            await message.reply("用法：/unban &lt;用户ID&gt;", parse_mode=ParseMode.HTML)
            return
        target_id = int(parts[1])
        await db.unban_user(target_id)
        await message.reply(f"✅ 已解封用户 <code>{target_id}</code>", parse_mode=ParseMode.HTML)

    @app.on_message(filters.command("userinfo") & filters.private & admin_only)
    async def user_info(client: Client, message: Message):
        parts = message.text.split()
        target_id, user = await _require_user(
            message, parts, 2, "用法：/userinfo &lt;用户ID&gt;"
        )
        if not target_id:
            return
        orders = await db.get_user_orders(target_id)
        status = "⛔ 已封禁" if user["is_banned"] else "✅ 正常"
        await message.reply(
            f"👤 <b>用户信息</b>\n\n"
            f"🆔 ID：<code>{user['user_id']}</code>\n"
            f"👤 用户名：@{user.get('username') or '未设置'}\n"
            f"📄 昵称：{user.get('first_name','')} {user.get('last_name','')}\n"
            f"💰 积分：<b>{user['points']}</b>\n"
            f"📅 签到次数：{user['checkin_count']}\n"
            f"🕐 最后签到：{user.get('last_checkin') or '无'}\n"
            f"🎟 兑换次数：{len(orders)}\n"
            f"🚦 状态：{status}\n"
            f"⏰ 注册：{str(user.get('joined_at',''))[:10]}",
            parse_mode=ParseMode.HTML,
        )

    # ── channels ─────────────────────────────────────────────────────────────

    @app.on_message(filters.command("addchannel") & filters.private & admin_only)
    async def add_channel(client: Client, message: Message):
        parts = message.text.split(maxsplit=3)
        if len(parts) < 4:
            await message.reply(
                "用法：/addchannel &lt;频道ID&gt; &lt;名称&gt; &lt;链接&gt;\n"
                "示例：/addchannel @mychannel 我的频道 https://t.me/mychannel",
                parse_mode=ParseMode.HTML,
            )
            return
        await db.add_channel(parts[1], parts[2], parts[3])
        await message.reply(f"✅ 已添加频道：{parts[2]} (<code>{parts[1]}</code>)",
                            parse_mode=ParseMode.HTML)

    @app.on_message(filters.command("removechannel") & filters.private & admin_only)
    async def remove_channel(client: Client, message: Message):
        parts = message.text.split()
        if len(parts) < 2:
            await message.reply("用法：/removechannel &lt;频道ID&gt;", parse_mode=ParseMode.HTML)
            return
        await db.remove_channel(parts[1])
        await message.reply(f"✅ 已移除频道：{parts[1]}")

    @app.on_message(filters.command("channels") & filters.private & admin_only)
    async def list_channels(client: Client, message: Message):
        channels = await db.get_channels()
        if not channels:
            await message.reply("暂无强制关注频道。")
            return
        lines = ["📢 <b>频道列表</b>\n"]
        for ch in channels:
            lines.append(
                f"• {ch['channel_name']}  <code>{ch['channel_id']}</code>\n"
                f"  {ch['channel_url']}\n"
            )
        await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)

    # ── settings ─────────────────────────────────────────────────────────────

    @app.on_message(filters.command("setreward") & filters.private & admin_only)
    async def set_reward(client: Client, message: Message):
        parts = message.text.split()
        if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
            await message.reply(
                "用法：/setreward &lt;最小值&gt; &lt;最大值&gt;\n示例：/setreward 5 30",
                parse_mode=ParseMode.HTML,
            )
            return
        mn, mx = int(parts[1]), int(parts[2])
        if mn < 1 or mx < mn:
            await message.reply("❌ 最小值需 ≥ 1，且最大值需 ≥ 最小值")
            return
        await db.set_setting("reward_min", str(mn))
        await db.set_setting("reward_max", str(mx))
        await message.reply(f"✅ 签到奖励范围已设置为 <b>{mn} ~ {mx}</b> 积分",
                            parse_mode=ParseMode.HTML)

    @app.on_message(filters.command("setgroup") & filters.private & admin_only)
    async def set_group(client: Client, message: Message):
        parts = message.text.split()
        if len(parts) < 2:
            await message.reply("用法：/setgroup &lt;群组ID&gt;", parse_mode=ParseMode.HTML)
            return
        await db.set_setting("group_id", parts[1])
        await message.reply(f"✅ 兑换公告群已设置为：<code>{parts[1]}</code>",
                            parse_mode=ParseMode.HTML)

    @app.on_message(filters.command("setfolder") & filters.private & admin_only)
    async def set_folder(client: Client, message: Message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.reply("用法：/setfolder &lt;文件夹链接&gt;", parse_mode=ParseMode.HTML)
            return
        await db.set_setting("folder_link", parts[1].strip())
        await message.reply("✅ 频道文件夹链接已设置")

    @app.on_message(filters.command("setinvite") & filters.private & admin_only)
    async def set_invite_reward(client: Client, message: Message):
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.reply("用法：/setinvite &lt;积分&gt;\n示例：/setinvite 20", parse_mode=ParseMode.HTML)
            return
        await db.set_setting("invite_reward", parts[1])
        await message.reply(f"✅ 邀请奖励已设置为 <b>{parts[1]}</b> 积分", parse_mode=ParseMode.HTML)

    @app.on_message(filters.command("setwelcome") & filters.private & admin_only)
    async def set_welcome(client: Client, message: Message):
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await message.reply("用法：/setwelcome &lt;欢迎语文字&gt;", parse_mode=ParseMode.HTML)
            return
        await db.set_setting("welcome_text", parts[1].strip())
        await message.reply("✅ 欢迎语已更新")

    # ── custom buttons ────────────────────────────────────────────────────────

    @app.on_message(filters.command("addbutton") & filters.private & admin_only)
    async def add_button(client: Client, message: Message):
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.reply(
                "用法：/addbutton &lt;按钮文字&gt; &lt;链接&gt;\n"
                "示例：/addbutton 官网 https://example.com",
                parse_mode=ParseMode.HTML,
            )
            return
        btn_id = await db.add_custom_button(parts[1], parts[2])
        await message.reply(
            f"✅ 已添加自定义按钮（ID: <code>{btn_id}</code>）\n{parts[1]} → {parts[2]}",
            parse_mode=ParseMode.HTML,
        )

    @app.on_message(filters.command("removebutton") & filters.private & admin_only)
    async def remove_button(client: Client, message: Message):
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            await message.reply("用法：/removebutton &lt;ID&gt;", parse_mode=ParseMode.HTML)
            return
        await db.remove_custom_button(int(parts[1]))
        await message.reply(f"✅ 已删除自定义按钮 ID: {parts[1]}")

    @app.on_message(filters.command("buttons") & filters.private & admin_only)
    async def list_buttons(client: Client, message: Message):
        buttons = await db.get_custom_buttons()
        if not buttons:
            await message.reply("暂无自定义按钮。")
            return
        lines = ["🔘 <b>自定义按钮列表</b>\n"]
        for b in buttons:
            lines.append(f"ID <code>{b['id']}</code>  {b['text']}\n  {b['url']}\n")
        await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)

    # ── stats ─────────────────────────────────────────────────────────────────

    @app.on_message(filters.command("stats") & filters.private & admin_only)
    async def show_stats(client: Client, message: Message):
        stats = await db.get_stats()
        reward_min = await db.get_setting("reward_min", "5")
        reward_max = await db.get_setting("reward_max", "20")
        group_id = await db.get_setting("group_id", "未设置")

        await message.reply(
            f"📊 <b>机器人统计</b>\n\n"
            f"👥 总用户数：<b>{stats['total_users']}</b>\n"
            f"✅ 正常用户：<b>{stats['active_users']}</b>\n"
            f"⛔ 封禁用户：<b>{stats['banned_users']}</b>\n"
            f"📅 今日签到：<b>{stats['today_checkins']}</b>\n"
            f"🛍️ 累计兑换：<b>{stats['total_orders']}</b>\n"
            f"🔑 剩余卡密：<b>{stats['available_keys']}</b>\n\n"
            f"⚙️ 签到奖励：{reward_min} ~ {reward_max} 积分\n"
            f"📢 公告群ID：{group_id}",
            parse_mode=ParseMode.HTML,
        )
