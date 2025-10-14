import subprocess
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# === 替换成你的 Bot Token ===
TELEGRAM_BOT_TOKEN = "你的token"

# ======== 主要命令处理函数 ========
async def run_nba(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sup，开始执行 nba.py ...")
    try:
        # 执行 nba.py
        output = subprocess.check_output(["python3", "nba.py"], stderr=subprocess.STDOUT)
        result = output.decode("utf-8", errors="ignore")

        # ✅ 去掉颜色控制符（例如 \033[1;92m）
        result = re.sub(r'\x1B\[[0-9;]*[A-Za-z]', '', result)

        # ✅ 优化输出格式（去除多余空行）
        result = re.sub(r'\n{3,}', '\n\n', result).strip()

        # 发送消息（Telegram 单条消息有长度限制）
        MAX_LENGTH = 4000
        if len(result) > MAX_LENGTH:
            # 分段发送
            for i in range(0, len(result), MAX_LENGTH):
                await update.message.reply_text(result[i:i + MAX_LENGTH])
        else:
            await update.message.reply_text(f"执行结果:\n{result}")

    except subprocess.CalledProcessError as e:
        error_output = e.output.decode("utf-8", errors="ignore")
        await update.message.reply_text(f"执行 nba.py 出错:\n{error_output}")

# ======== 启动 Bot ========
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("nba", run_nba))
    print("✅ Telegram Bot 已启动，等待命令 /nba ...")
    app.run_polling()

if __name__ == "__main__":
    main()
