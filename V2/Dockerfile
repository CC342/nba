FROM python:3.9-slim

# 1. 安装系统依赖 (Xvfb 和 常用工具)
RUN apt-get update && apt-get install -y \
    xvfb \
    procps \
    curl \
    gnupg \
    wget \
    && rm -rf /var/lib/apt/lists/*

# 2. 设置工作目录
WORKDIR /main

# 3. 复制 Python 依赖并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 安装 Playwright 浏览器
RUN playwright install chromium
RUN playwright install-deps chromium

# 5. 复制所有代码文件
COPY . .

# 6. 设置环境变量 (确保日志实时打印)
ENV PYTHONUNBUFFERED=1

# 7. ★★★ 直接启动 Flask ★★★
CMD ["python3", "main.py"]
