#!/usr/bin/env python3
import time
import sys
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ------------------- 配置 -------------------
TARGET_URL = "https://gamestrend.net/u10-toronto-blue-jays-vs-seattle-mariners/"
MAX_WAIT = 3.5       # 总等待时间
POLL_INTERVAL = 0.1  # 轮询间隔
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
)
# 代理地址（域名+端口+proxy路径）
PROXY_HOST = "https://imeet.eu.org:5000"
PROXY_PREFIX = f"{PROXY_HOST}/proxy?url="
# -------------------------------------------

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 768},
            java_script_enabled=True,
        )
        context.set_extra_http_headers({"Referer": TARGET_URL})
        page = context.new_page()

        m3u8_urls = set()
        found_first = False

        # 捕获 m3u8 请求/响应
        def capture_m3u8(req_or_resp):
            url = getattr(req_or_resp, 'url', None)
            if url and ".m3u8" in url and "embedsports.top" in url:
                m3u8_urls.add((url, "request/response"))
                return True
            return False

        page.on("request", lambda r: capture_m3u8(r))
        page.on("response", lambda r: capture_m3u8(r))

        print("打开页面:", TARGET_URL)
        try:
            page.goto(TARGET_URL, wait_until="load", timeout=15000)
        except PlaywrightTimeoutError:
            print("page.goto 超时，但继续执行...")

        start_ts = time.time()
        while (time.time() - start_ts) < MAX_WAIT and not found_first:
            # 检查 embedsports.top iframe
            for f in page.frames:
                if "embedsports.top" in f.url:
                    try:
                        content = f.content()
                        for found in re.findall(r"https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*", content):
                            if found not in [u[0] for u in m3u8_urls]:
                                print(f"[抓到] iframe {f.url} ->", found)
                                m3u8_urls.add((found, "iframe源码"))
                                found_first = True
                                break
                    except Exception:
                        pass
                if found_first:
                    break

            # 检查主页面源码
            if not found_first:
                content = page.content()
                for found in re.findall(r"https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*", content):
                    if found not in [u[0] for u in m3u8_urls]:
                        print("[抓到] 页面源码 ->", found)
                        m3u8_urls.add((found, "page源码"))
                        found_first = True
                        break

            if found_first:
                break

            time.sleep(POLL_INTERVAL)

        # 关闭浏览器
        try:
            context.close()
            browser.close()
        except Exception:
            pass

        print("\n=== 抓取和代理结果 ===")
        if m3u8_urls:
            for url, source in sorted(m3u8_urls):
                # 直接生成代理 URL，保持原始 index.m3u8
                proxy_url = PROXY_PREFIX + url
                print(f"[{source}] 原始: {url}")
                print(f"[{source}] 代理: {proxy_url}\n")
        else:
            print("未抓取到 m3u8 地址，可能页面加载慢或需要额外 headers/代理。")

        sys.exit(0 if m3u8_urls else 2)


if __name__ == "__main__":
    main()
