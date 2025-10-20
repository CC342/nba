# 🏀 NBA Live Stream（实时比赛推送）

本项目可以实时抓取 NBA 比赛信息，并通过 **Telegram Bot** 或 **企业微信应用** 推送通知。  
核心抓取逻辑在 `nba.py`，Bot 仅用于远程接收 `"nba"` 命令并触发抓取。

---

## ⚡ 功能

- 📊 **抓取比赛信息**：执行 `nba.py` 获取比赛列表、比分及直播状态  
- 📱 **推送通知**：支持 Telegram 和企业微信应用  
- 🌐 **远程触发**：可通过 Telegram Bot 或企业微信应用发送命令执行抓取  

---

## 🔄 使用流程

1. 用户通过 Telegram 或企业微信应用发送命令  
2. Bot 远程触发执行 `nba.py`  
3. 抓取比赛列表、直播地址、比赛结果  
4. 自动推送到 Telegram 或企业微信  

> ⚠️ 如果不使用 Bot 功能，可以直接执行 `nba.py`，同样可抓取比赛信息。

---

## 🛠 使用场景

- 实时获取 NBA 比赛动态  
- 远程抓取比赛信息并推送  

---

## 📦 项目结构

```text
nba/
├── pyproject.toml
├── README.md
├── nba.sh                  # 起停管理脚本
├── .env                     # 配置文件，填写微信/Telegram信息
├── .venv/                  # uv 创建的虚拟环境
└── src/
    └── nba/
        ├── __init__.py
        ├── nba.py           # 核心抓取逻辑
        ├── tg/
        │   ├── __init__.py
        │   └── nbabot.py    # Telegram Bot：添加 nba 命令并触发 nba.py
        └── wx/
            ├── __init__.py
            ├── wx.py        # 企业微信 Bot：添加 nba 命令并触发 nba.py
            ├── WXBizMsgCrypt.py
            └── ierror.py
````

---

## 🛠 安装步骤

### 1️⃣ 克隆仓库

```bash
git clone https://github.com/CC342/nba.git
cd nba
```

### 2️⃣ 使用 uv 创建虚拟环境并安装依赖

```bash
uv init
```

✅ uv 会自动解析 `pyproject.toml`，创建 `.venv` 并安装依赖：

* beautifulsoup4
* loguru
* lxml
* m3u8
* playwright
* pycryptodome
* python-dotenv
* python-telegram-bot
* requests

💡 **无需手动 pip 安装**，所有依赖在虚拟环境内统一管理。

---

### 3️⃣ 配置 `.env`

```text
# 代理配置（可选）
# 填写域名+端口，例如：https://example.com:5000
# 或者在 Nginx 做反向代理后直接填域名
PROXY_HOST="你的代理地址"

# Telegram 配置
TELEGRAM_BOT_TOKEN="你的token"
TELEGRAM_CHAT_ID="聊天id"

# 企业微信配置
WX_CORP_ID="企业微信id"
WX_AGENT_ID="应用id"
WX_SECRET="密钥"
WX_TOKEN="企业微信应用——接收消息——启用api"
WX_ENCODING_AES_KEY="企业微信应用——接收消息——启用api"
```

---

### 4️⃣ 安装 `nba.sh` 到全局

```bash
sudo cp nba.sh /usr/local/bin/nba.sh
sudo chmod +x /usr/local/bin/nba.sh
```

✅ 安装完成后，可在任何路径直接执行：

```bash
nba.sh
```

---

## 🏃‍♂️ 启动方式

### 方式 1：通过管理脚本启动 Bot

```bash
nba.sh
```

菜单选择：

* **启动微信 Bot** → 添加 `nba` 命令，可接收企业微信触发
* **启动 Telegram Bot** → 添加 `nba` 命令，可接收 Telegram 触发

> Bot 功能主要作用：远程触发 `nba.py`，并将比赛信息推送到对应平台。
> 开关与否只影响 Bot 接收命令，`nba.py` 本身的抓取逻辑不依赖 Bot。

### 方式 2：直接执行核心抓取脚本

```bash
cd src/nba
python3 nba.py
```

✅ 无需启动 Bot，也可以直接获取并输出比赛信息。

---

## 📄 日志文件

| 文件              | 说明              |
| --------------- | --------------- |
| `wx.py.log`     | 企业微信 Bot 日志     |
| `nbabot.py.log` | Telegram Bot 日志 |

示例日志：

```text
INFO:root:收到文本消息: nba
INFO:root:已触发 nba.py 执行
```

---

## 🎯 总结

* 核心抓取逻辑在 `nba.py`，可单独运行
* Bot (`wx.py` / `nbabot.py`) 仅用于远程触发 `nba.py`
* uv 管理依赖，避免系统 Python 冲突
* 配置统一在 `.env`，无需修改源码
* 支持直接运行或通过 Bot 远程触发

```

