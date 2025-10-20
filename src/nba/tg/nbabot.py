import subprocess
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv
import sys
import os

# 虚拟环境路径
VENV_PATH = "/home/nba/.venv"

# 激活虚拟环境
activate_this = os.path.join(VENV_PATH, "bin/activate_this.py")
if os.path.exists(activate_this):
    with open(activate_this) as f:
        exec(f.read(), dict(__file__=activate_this))
else:
    print(f"警告: 找不到虚拟环境: {VENV_PATH}", file=sys.stderr)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


# ======== 主要命令处理函数 ========
async def run_nba(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sup，开始执行 nba.py ...")
    try:
        # ✅ 只触发执行 nba.py，不捕获输出
        subprocess.Popen(["python3", "/home/nba/src/nba/nba.py"])
        await update.message.reply_text("已触发 nba.py 执行！")
    except Exception as e:
        await update.message.reply_text(f"执行 nba.py 失败: {e}")

# ======== 启动 Bot ========
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("nba", run_nba))
    print("✅ Telegram Bot 已启动，等待命令 /nba ...")
    app.run_polling()

if __name__ == "__main__":
    main()
