import time
import sys
import subprocess
import re
from pyvirtualdisplay import Display
from playwright.sync_api import sync_playwright

# 目标地址 (测试用)
TARGET_URL = "https://games.com" 

def force_cleanup():
    """清理残留进程"""
    try:
        subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "Xvfb"], stderr=subprocess.DEVNULL)
    except: pass

def fetch_m3u8_core(url):
    force_cleanup()
    print("[*] 启动环境 (Xvfb + Playwright)...")
    
    display = Display(visible=0, size=(1280, 720))
    display.start()
    
    captured_urls = []
    final_url = None

    try:
        with sync_playwright() as p:
            # 1. 启动浏览器
            browser = p.chromium.launch(
                headless=False,
                args=[
                    '--disable-blink-features=AutomationControlled', 
                    '--no-sandbox',
                    '--autoplay-policy=no-user-gesture-required',
                    '--ignore-certificate-errors'
                ]
            )
            
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 720},
                ignore_https_errors=True,
                accept_downloads=True
            )
            page = context.new_page()

            # ==========================================
            # 策略 A: 网络层监听 (最强方案)
            # ==========================================
            def handle_request(request):
                try:
                    u = request.url
                    if ".m3u8" in u and "http" in u:
                        if "google" not in u and "favicon" not in u:
                            print(f"[+] 网络捕获: {u[:60]}...")
                            captured_urls.append(u)
                except: pass

            page.on("request", handle_request)

            # 2. 访问页面
            print(f"[*] 正在访问: {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
            except: 
                print("    [!] 页面加载超时，继续尝试...")

            print("[*] 开始混合嗅探 (点击 + 扫描)...")
            start_time = time.time()
            
            # ==========================================
            # 策略 B & C: 循环点击与内存扫描
            # ==========================================
            # 尝试 4 轮，每轮间隔 5 秒
            for i in range(1, 5):
                if captured_urls: 
                    print("    -> 已通过网络监听到地址，停止操作。")
                    break

                print(f">>> 第 {i}/4 次尝试激活...")
                
                # B. 模拟点击 (激活懒加载播放器)
                try:
                    # 1. 尝试点击 iframe 内部的特定播放按钮
                    for frame in page.frames:
                        frame.evaluate("""() => {
                            const btns = document.querySelectorAll('.player-poster, .play-wrapper, button[aria-label="Play"]');
                            btns.forEach(b => b.click());
                        }""")
                    # 2. 尝试点击屏幕中心
                    page.mouse.click(640, 360)
                except: pass

                # 等待响应
                time.sleep(5)

                # C. 内存扫描 (兜底方案)
                if not captured_urls:
                    for frame in page.frames:
                        try:
                            res = frame.evaluate("""() => {
                                try {
                                    if (window.Clappr && window.Clappr.options) return window.Clappr.options.source;
                                    if (window.jwplayer) return window.jwplayer(0).getConfig().file;
                                    if (window.config && window.config.file) return window.config.file;
                                    if (window.player && window.player.options) return window.player.options.source;
                                    for (let k in window) {
                                        if (typeof window[k] === 'string' && window[k].includes('.m3u8') && window[k].includes('http')) return window[k];
                                    }
                                } catch(e) {}
                                return null;
                            }""")
                            if res:
                                print(f"[+] 内存捕获: {res[:60]}...")
                                captured_urls.append(res)
                                break
                        except: pass

            # 3. 结果输出
            if captured_urls:
                final_url = captured_urls[-1]
                print("\n" + "="*50)
                print("【 抓取成功 】")
                print(final_url)
                print("="*50 + "\n")
            else:
                print("[-] 抓取失败")

    except Exception as e:
        print(f"[X] 异常: {e}")
    finally:
        display.stop()
        force_cleanup()
        return final_url

if __name__ == "__main__":
    fetch_m3u8_core(TARGET_URL)
