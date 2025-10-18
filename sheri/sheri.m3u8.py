#!/usr/bin/env python3
import re
from playwright.sync_api import sync_playwright

TARGET_URL = "https://gamestrend.net/t23-portland-trail-blazers-vs-utah-jazz/"
WAIT_AFTER_LOAD_MS = 1000  # 等待1秒，让JS执行生成m3u8

def main():
    with sync_playwright() as p:
        # 无头模式启动，禁用沙箱，适合服务器环境
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context()
        page = context.new_page()

        print(f"打开页面: {TARGET_URL}")
        page.goto(TARGET_URL, timeout=30000)

        # 等待页面js执行
        page.wait_for_timeout(WAIT_AFTER_LOAD_MS)

        # 获取渲染后完整HTML内容
        content = page.content()

        # 正则匹配所有.m3u8链接
        m3u8_list = re.findall(r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*', content)

        if m3u8_list:
            print("找到m3u8链接:")
            for u in set(m3u8_list):
                print(u)
        else:
            print("页面源码中未找到m3u8链接")

        browser.close()

if __name__ == "__main__":
    main()

