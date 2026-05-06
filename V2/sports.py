import requests
import json
import time
import re
import os
import sys
import html
import subprocess
import warnings
import multiprocessing
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from pyvirtualdisplay import Display
from dotenv import load_dotenv

# 屏蔽无关报错
warnings.filterwarnings("ignore")

# ================= 配置区域 =================
load_dotenv()

PROXY_HOST = os.getenv("PROXY_HOST")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WX_CORP_ID = os.getenv("WX_CORP_ID")
WX_AGENT_ID = os.getenv("WX_AGENT_ID")
WX_SECRET = os.getenv("WX_SECRET")

# 独立项目：保存为 sports.json
DATA_FILE = "/home/nba/sports.json"
BASE_URL = "https://fox.co/"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

RED = "\033[1;91m"
GREEN = "\033[1;92m"
YELLOW = "\033[1;93m"
RESET = "\033[0m"

# ================= 体育图标映射字典 =================
SPORT_ICONS = {
    'football': '⚽',
    'basketball': '🏀',
    'american-football': '🏈',
    'hockey': '🏒',
    'baseball': '⚾',
    'motor-sports': '🏎️',
    'fight': '🥊',
    'tennis': '🎾',
    'rugby': '🏉',
    'golf': '⛳',
    'cricket': '🏏',
    'afl': '🏉',
    'darts': '🎯',
    'other': '📺'
}

# ================= 消息推送 =================

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.get(url, params={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception: pass

def send_wechat(msg):
    token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WX_CORP_ID}&corpsecret={WX_SECRET}"
    try:
        r = requests.get(token_url).json()
        access_token = r.get("access_token")
        if access_token:
            send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
            data = {"touser": "@all", "msgtype": "text", "agentid": int(WX_AGENT_ID), "text": {"content": msg}, "safe": 0}
            requests.post(send_url, json=data)
    except Exception: pass

# ================= 智能文本解析 =================

def parse_key_from_title(title_text):
    parts = re.split(r'\s+vs\.?\s+', title_text, flags=re.IGNORECASE)
    if len(parts) >= 2:
        t1 = re.sub(r'[^a-zA-Z0-9]', '', parts[0].split()[0]).lower()
        t2 = re.sub(r'[^a-zA-Z0-9]', '', parts[1].split()[0]).lower()
        return f"{t1}{t2}"
    else:
        words = title_text.split()
        if words:
            return "".join(re.sub(r'[^a-zA-Z0-9]', '', w).lower() for w in words[:2])
        return "unknown"

# ================= 【核心修复：点击展开与智能选源 + Emoji】 =================

def fetch_home_matches():
    match_started = []
    seen_urls = set()

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS['User-Agent'])
            page.goto(BASE_URL, timeout=15000, wait_until="domcontentloaded")
            
            # 等待网页初始渲染
            page.wait_for_timeout(3000) 
            
            # 主动点击 "See all live" 按钮，逼出所有被折叠的比赛
            try:
                live_btn = page.locator('a.see-all-live[data-live="1"]').first
                if live_btn.count() > 0:
                    live_btn.click(force=True, timeout=2000)
                    page.wait_for_timeout(2000) 
            except Exception:
                pass

            content = page.content()
            browser.close()
        except Exception as e: 
            print(f"Error fetching home: {e}")
            return [], [], []

    # 解析 DOM
    soup = BeautifulSoup(content, "html.parser")
    cards = soup.find_all('a', class_='watch')
    
    for card in cards:
        href = card.get('href', '')
        if not href: continue
        
        # 必须是直播状态
        is_live = False
        pill = card.find('span', class_='card-pill')
        if pill and 'live' in pill.get_text(strip=True).lower():
            is_live = True
            
        if not is_live: continue
        
        # 智能选源
        target_source = "admin" 
        src_raw = card.get('data-picker-src')
        if src_raw:
            try:
                clean_src = html.unescape(src_raw) 
                src_list = json.loads(clean_src)
                if isinstance(src_list, list) and len(src_list) > 0:
                    available_srcs = [s[0].lower() for s in src_list if isinstance(s, list) and len(s) > 0]
                    if "admin" in available_srcs: target_source = "admin"
                    elif "echo" in available_srcs: target_source = "echo"
                    elif "delta" in available_srcs: target_source = "delta"
                    else: target_source = available_srcs[0]
            except Exception:
                pass

        if href.startswith("/"): href = BASE_URL.rstrip("/") + href
        base_href = href.split('?')[0]
        href_target = base_href + f"?source={target_source}"
        
        if href_target in seen_urls: continue
        seen_urls.add(href_target)
        
        # 提取体育分类并匹配 Emoji
        raw_sport = "other"
        for cls in card.get('class', []):
            if cls.startswith('card-sport-'):
                raw_sport = cls.replace('card-sport-', '').lower()
                break
                
        icon = SPORT_ICONS.get(raw_sport, '')
        cat_name = raw_sport.replace('-', ' ').title()
        cat_text = f"{icon} {cat_name}".strip()
        
        title_tag = card.find('h3', class_='card-title')
        title_text = title_tag.get_text(strip=True) if title_tag else card.get('data-watch-title', '')
        if not title_text: continue
        
        formatted_title = re.sub(r'\s+vs\.?\s+', ' — ', title_text, flags=re.IGNORECASE)
        display_name = f"{cat_text}: {formatted_title}"
        team_key = parse_key_from_title(title_text)
        
        if team_key == "unknown" or len(team_key) < 2: continue

        match_started.append({
            "raw_name": title_text, 
            "url": href_target, 
            "display_name": display_name,
            "team_key": team_key,
            "target_source": target_source
        })
        
    return match_started, [], []

# ================= 精准抓取逻辑 =================

def scrape_m3u8_worker(url, team_key, target_source, return_dict):
    display = Display(visible=0, size=(1280, 720))
    display.start()
    
    captured_urls = []
    
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
            context = browser.new_context(user_agent=HEADERS['User-Agent'])
            page = context.new_page()
            
            def smart_wait(ms):
                steps = max(1, int(ms / 200))
                for _ in range(steps):
                    if captured_urls: return True
                    page.wait_for_timeout(200)
                return False
            
            def handle_request(request):
                try:
                    u = request.url
                    if ".m3u8" in u and "http" in u:
                        if "google" not in u and "favicon" not in u:
                            captured_urls.append(u)
                except: pass
            
            page.on("request", handle_request)
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except: pass

            smart_wait(1500)

            if not captured_urls:
                try:
                    clicked = False
                    try:
                        source_locator = page.locator(f"text=/{target_source}/i").locator("visible=true").first
                        if source_locator.count() > 0:
                            source_locator.click(force=True, timeout=500)
                            clicked = True
                    except: pass

                    if not clicked:
                        for i, frame in enumerate(page.frames):
                            try:
                                f_locator = frame.locator(f"text=/{target_source}/i").locator("visible=true").first
                                if f_locator.count() > 0:
                                    f_locator.click(force=True, timeout=500)
                                    clicked = True
                                    break
                            except: pass
                except: pass

            if not captured_urls:
                smart_wait(5000) 

            if not captured_urls:
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
                        if res:
                            captured_urls.append(res)
                            break
                except: pass

            if captured_urls:
                found_url = captured_urls[-1] 
                
                for u in reversed(captured_urls):
                    if "playlist.m3u8" in u or "index.m3u8" in u or "master.m3u8" in u:
                        found_url = u
                        break
                        
                domain_match = re.search(r"https?://([^/]+)", found_url)
                token_match = re.search(r"/secure/([^/]+)/", found_url)
                
                if domain_match:
                    return_dict['domain'] = domain_match.group(1)
                    return_dict['token'] = token_match.group(1) if token_match else "none"
                    return_dict['full_url'] = found_url
            
            browser.close()
    except: pass
    finally: display.stop()

def run_with_timeout(func, args, timeout):
    manager = multiprocessing.Manager()
    return_dict = manager.dict()
    p = multiprocessing.Process(target=func, args=(*args, return_dict))
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.terminate()
        p.join()
        try:
            subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)
            subprocess.run(["pkill", "-9", "Xvfb"], stderr=subprocess.DEVNULL)
        except: pass
        return None
    return return_dict

def process_game_get_m3u8(match_url, team_key, target_source):
    res2 = run_with_timeout(scrape_m3u8_worker, (match_url, team_key, target_source), 25)
    if res2 and 'full_url' in res2:
        return res2
    return None

def main():
    try:
        subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "Xvfb"], stderr=subprocess.DEVNULL)

        match_started, _, _ = fetch_home_matches()
        push_msg = ""
        game_json_data = {}

        print(f"{GREEN}Live: {len(match_started)}{RESET}")
        push_msg += f"Live: {len(match_started)}\n"

        for i, m in enumerate(match_started, 1):
            display_name = m['display_name']
            team_key = m['team_key']
            target_source = m.get('target_source', 'admin') 
            
            print(f"\n======================================")
            print(f"{i}. {display_name} (Using: {target_source})")
            push_msg += f"{i}. {display_name}\n"
            
            m3u8_info = process_game_get_m3u8(m['url'], team_key, target_source)
            
            if m3u8_info:
                game_json_data[team_key] = {
                    "key": team_key,
                    "name": display_name,
                    "domain": m3u8_info['domain'],
                    "token": m3u8_info['token'],
                    "full_url": m3u8_info['full_url'],
                    "updated_at": time.time()
                }
                
                if PROXY_HOST:
                    server_link = f"{PROXY_HOST}/{team_key}/index.m3u8"
                    print(f"  {GREEN}{server_link}{RESET}")
                    push_msg += f"  {server_link}\n"
                else:
                    print(f"  {GREEN}{m3u8_info['full_url'][:60]}...{RESET}")
                    push_msg += f"  {m3u8_info['full_url'][:50]}...\n"
            else:
                print(f"  {RED}Failed{RESET}")
                push_msg += "  Failed\n"

        if game_json_data:
            with open(DATA_FILE, "w", encoding='utf-8') as f:
                json.dump(game_json_data, f, indent=4, ensure_ascii=False)
            print(f"\n[OK] Saved to {DATA_FILE}")

        if push_msg:
            send_telegram(push_msg)
            send_wechat(push_msg)

    except KeyboardInterrupt:
        print("\n[!] Exit")
        subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    main()
