#!/usr/bin/env python3
import time
import sys
import re
from playwright.sync_api import sync_playwright
from pyvirtualdisplay import Display

RED = "\033[1;91m"
RESET = "\033[0m"
TARGET_URL = "https://fox.app"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
PROXY_PREFIX = "https://xxxx.eu.com:99900/proxy?url="

def main():
    display = Display(visible=0, size=(1280, 720))
    display.start()
    
    captured_urls = []
    
    print("==================================================")
    print(f"[*] 开始测试目标: {TARGET_URL}")
    print("==================================================")
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    '--disable-blink-features=AutomationControlled', 
                    '--no-sandbox', 
                    '--autoplay-policy=no-user-gesture-required',
                    '--disable-web-security'
                ]
            )
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            
            def handle_request(request):
                try:
                    u = request.url
                    if ".m3u8" in u and "http" in u:
                        if "google" not in u and "favicon" not in u:
                            captured_urls.append(u)
                            print(f"      [发现流] -> {u[:80]}...")
                except: pass
            
            page.on("request", handle_request)
            
            # 1. 停留在原网页，绝对不跳转！
            print("[*] 1. 正在访问详情页，等待合法 iframe 加载...")
            try:
                page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(4000) 
            except: pass

            print("[*] 2. 模拟点击激活播放源...")
            try:
                # 尝试点击那个高亮的按钮，确保 iframe 刷新
                channel_btn = page.locator("a.sr-on").first
                if channel_btn.count() > 0:
                    channel_btn.click(timeout=3000)
                    page.wait_for_timeout(2000)
            except: pass

            print("[*] 3. 暴力点击屏幕中心 (破坏广告遮罩并激活播放器)...")
            try:
                # 连点两次屏幕中心，第一下点掉假弹窗，第二下点开播放器
                page.mouse.click(640, 360)
                page.wait_for_timeout(1000)
                page.mouse.click(640, 360)
            except: pass

            print("[*] 4. 执行原汁原味的多重提取 (最多等 20 秒)...")
            start_time = time.time()
            found_url = None
            
            while time.time() - start_time < 20:
                # 方案 A: 网络抓包
                valid_urls = [u for u in captured_urls if "secure" in u or "mono" in u or "playlist" in u]
                if valid_urls:
                    found_url = valid_urls[-1]
                    print("    -> [命中] 通过网络抓包获取到 M3U8！")
                    break
                
                # 方案 B: 遍历所有合法的嵌套 iframe，强读内存变量
                try:
                    for frame in page.frames:
                        res = frame.evaluate("""() => {
                            try {
                                if (window.jwplayer) return window.jwplayer(0).getConfig().file;
                                if (window.player && window.player.options) return window.player.options.source;
                                if (window.config && window.config.file) return window.config.file;
                                for (let k in window) {
                                    if (typeof window[k] === 'string' && window[k].includes('.m3u8')) return window[k];
                                }
                            } catch(e) {}
                            return null;
                        }""")
                        if res and ".m3u8" in res:
                            found_url = res
                            captured_urls.append(res)
                            break
                    if found_url:
                        print("    -> [命中] 成功入侵 JS 变量，提取到 M3U8！")
                        break
                except: pass
                
                # 继续点击保持活跃
                try: page.mouse.click(640, 360)
                except: pass
                page.wait_for_timeout(1000)

            # 最终回溯
            if not found_url and captured_urls:
                for u in reversed(captured_urls):
                    if "playlist.m3u8" in u or "index.m3u8" in u or "master.m3u8" in u or "secure" in u:
                        found_url = u
                        break
                if not found_url:
                    found_url = captured_urls[-1]
                
            browser.close()
    except Exception as e:
        print(f"[!] 运行异常: {e}")
    finally:
        display.stop()

    print("\n=== 🎯 最终测试结果 ===")
    if found_url:
        proxy_url = PROXY_PREFIX + found_url
        print(f"[原始直链] {found_url}")
        print(f"[代理链接] {proxy_url}\n")
    else:
        print(f"[{RED}失败{RESET}] 未抓取到任何 m3u8 地址，这通常意味着该场比赛并未开始推流。")

if __name__ == "__main__":
    main()
