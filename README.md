# Telegram 积分签到与卡密自动分发机器人

集成「强制关注」「每日签到」「积分商城」「卡密分发」的 Telegram 机器人。

## 功能特性

- **强制入群**：用户必须加入指定频道才能使用，支持一键加入文件夹链接
- **每日签到**：群内发「签到」即可，管理员可动态设置积分奖励范围
- **积分商城**：群内发「兑换」浏览商品，支持库存管理
- **卡密分发**：兑换成功后群内公示，用户私聊机器人安全领取卡密
- **个人中心**：查询积分余额、签到记录、兑换历史
- **管理后台**：批量导入卡密、用户积分管理、封禁、广告按钮配置

## 技术栈

- Python 3.9+
- [Pyrogram](https://github.com/pyrogram/pyrogram) 2.0
- aiosqlite（SQLite 异步驱动）

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/Guyi888/telegram-points-bot.git
cd telegram-points-bot
```

### 2. 安装依赖

```bash
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入以下必填项：

| 变量 | 说明 | 获取方式 |
|------|------|---------|
| `API_ID` | Telegram API ID | [my.telegram.org/apps](https://my.telegram.org/apps) |
| `API_HASH` | Telegram API Hash | 同上 |
| `BOT_TOKEN` | 机器人 Token | [@BotFather](https://t.me/BotFather) |
| `ADMIN_IDS` | 管理员用户 ID（逗号分隔） | [@userinfobot](https://t.me/userinfobot) 查询 |

### 4. 启动

```bash
python main.py
```

## 群内关键词

| 发送 | 功能 |
|------|------|
| `签到` / `/checkin` | 每日签到领积分 |
| `兑换` / `/shop` | 打开积分商城 |
| `我的积分` / `/points` | 查看当前积分 |

## 管理员命令

发送 `/admin` 查看完整面板，常用命令如下：

### 初始化流程

```
/addchannel @频道ID 频道名 https://t.me/...   # 添加强制关注频道
/setgroup -1001234567890                      # 设置兑换公告群
/setreward 10 50                              # 签到奖励范围（积分）
/addproduct 月卡VIP 100 会员 高级会员一个月    # 添加商品
/importkeys 1                                 # 导入卡密（发完命令再发 .txt 文件）
```

### 用户管理

```
/addpoints <用户ID> <积分>      # 增加积分
/deductpoints <用户ID> <积分>   # 扣除积分
/setpoints <用户ID> <积分>      # 直接设置积分
/ban <用户ID>                   # 封禁用户
/unban <用户ID>                 # 解封用户
/userinfo <用户ID>              # 查看用户详情
```

### 系统设置

```
/setfolder <链接>     # 设置频道文件夹一键加入链接
/addbutton <文字> <链接>   # 添加广告按钮
/removebutton <ID>         # 删除广告按钮
/stats                     # 机器人统计数据
```

## 卡密导入格式

`.txt` 文件，每行一个卡密：

```
ABCD-1234-EFGH-5678
IJKL-9012-MNOP-3456
QRST-7890-UVWX-1234
```

## 兑换流程

```
用户群内发「兑换」
    ↓
选择商品并确认
    ↓
群内发布兑换公告（含「点击领取卡密」按钮）
    ↓
用户点击按钮跳转私聊
    ↓
机器人私聊发送卡密
```

## License

MIT
