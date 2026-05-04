import requests
import json
import time
import re
import os
import sys
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
BASE_URL = "https://gamescentral.top/"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

RED = "\033[1;91m"
GREEN = "\033[1;92m"
YELLOW = "\033[1;93m"
RESET = "\033[0m"

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

def parse_display_and_key(raw_text):
    time_str = ""
    raw_lower = raw_text.lower()
    
    patterns = [
        (r'(\d+)\s*hours?\s*and\s*(\d+)\s*minutes? from now', lambda h, m: f"{int(h):02d}:{int(m):02d} Later"),
        (r'(\d+)\s*hours? from now', lambda h: f"{int(h):02d}:00 Later"),
        (r'(\d+)\s*minutes? from now', lambda m: f"00:{int(m):02d} Later"),
        (r'(\d+)\s*day[s]? from now', lambda d: f"{int(d)*24}:00 Later"),
    ]
    for pattern, func in patterns:
        match = re.search(pattern, raw_lower)
        if match:
            time_str = func(*match.groups())
            raw_text = re.sub(pattern, "", raw_text, flags=re.I)
            break

    clean = raw_text.replace("Match Started", "").replace("Live Now", "").replace("LIVE", "").replace("Live", "").replace("Regular Season", "").replace("Final", "").strip()
    clean = re.sub(r'\s+', ' ', clean)
    
    categories = r'(?i)\b(hockey|basketball|baseball|football|soccer|tennis|cricket|other|rugby|motorsport|boxing|mma|ufc|wwe|volleyball|handball|darts|snooker|rally|tv)\b'
    match = re.search(categories, clean)
    category_formatted = ""
    teams_part = clean
    
    if match:
        cat_end_idx = match.end()
        category_raw = clean[:cat_end_idx].strip()
        teams_part = clean[cat_end_idx:].strip()
        
        words = category_raw.split()
        if words:
            words[-1] = words[-1].capitalize()
            category_formatted = " ".join(words)
            
    if not teams_part:
        teams_part = clean

    split_patterns = [r'\s+vs\.?\s+', r'\s+v\.s\.\s+', r'\s+v\.\s+', r'\s+-\s+', r'\s+🆚\s+']
    t1, t2 = "", ""
    for pattern in split_patterns:
        parts = re.split(pattern, teams_part, flags=re.IGNORECASE)
        if len(parts) >= 2:
            t1 = parts[0].strip()
            t2 = " ".join(parts[1:]).strip() 
            break
            
    if not t1:
        t1 = teams_part
        
    display_teams = f"{t1} — {t2}" if t2 else t1
    
    display_name = ""
    if time_str: display_name += f"{time_str}  "
        
    if category_formatted:
        display_name += f"{category_formatted}: {display_teams}"
    else:
        display_name += display_teams
        
    key_text = re.sub(r'[^a-zA-Z0-9\s]', '', teams_part)
    key_words = key_text.split()
    if len(key_words) >= 2:
        if t1 and t2:
            t1_word = re.sub(r'[^a-zA-Z0-9]', '', t1.split()[0]).lower()
            t2_word = re.sub(r'[^a-zA-Z0-9]', '', t2.split()[0]).lower()
            key = f"{t1_word}{t2_word}"
        else:
            key = "".join(w.lower() for w in key_words[:2])
    elif len(key_words) == 1:
        key = key_words[0].lower()
    else:
        key = "unknown"
        
    return display_name.strip(), key

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

# ================= 精准抓取逻辑 =================

def fetch_home_matches():
    match_started, final_matches, from_now_matches = [], [], []
    seen_urls = set()

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS['User-Agent'])
            page.goto(BASE_URL, timeout=15000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000) 
            content = page.content()
            soup = BeautifulSoup(content, "html.parser")
            
            track = soup.find(id="liveNowTrack")
            if track:
                cards = track.find_all('a', class_='watch')
                for card in cards:
                    href = card.get('href', '')
                    if not href: continue
                    
                    if href.startswith("/"): href = BASE_URL.rstrip("/") + href
                    
                    base_href = href.split('?')[0]
                    href_admin = base_href + "?source=admin"
                    
                    if base_href in seen_urls: continue
                    seen_urls.add(base_href)
                    
                    chip = card.find('span', class_='ln-chip')
                    cat_text = chip.get_text(strip=True) if chip else ""
                    
                    title_tag = card.find('h3', class_='card-title')
                    title_text = title_tag.get_text(strip=True) if title_tag else card.get('data-watch-title', '')
                    if not title_text: continue
                    
                    formatted_title = re.sub(r'\s+vs\.?\s+', ' — ', title_text, flags=re.IGNORECASE)
                    if cat_text:
                        display_name = f"{cat_text}: {formatted_title}"
                    else:
                        display_name = formatted_title
                        
                    team_key = parse_key_from_title(title_text)
                    if team_key == "unknown" or len(team_key) < 2: continue

                    match_started.append({
                        "raw_name": title_text, 
                        "url": href_admin, 
                        "display_name": display_name,
                        "team_key": team_key
                    })
                        
            browser.close()
        except Exception: pass
        
    return match_started, final_matches, from_now_matches

def scrape_m3u8_worker(url, team_key, return_dict):
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
            except Exception: pass

            smart_wait(1500)

            if not captured_urls:
                try:
                    clicked = False
                    try:
                        admin_locator = page.locator("text=/admin/i").locator("visible=true").first
                        if admin_locator.count() > 0:
                            admin_locator.click(force=True, timeout=500)
                            clicked = True
                    except Exception: pass

                    if not clicked:
                        for i, frame in enumerate(page.frames):
                            try:
                                f_locator = frame.locator("text=/admin/i").locator("visible=true").first
                                if f_locator.count() > 0:
                                    f_locator.click(force=True, timeout=500)
                                    clicked = True
                                    break
                            except: pass
                except Exception: pass

            if not captured_urls:
                smart_wait(3000) 

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
                
                domain_match = re.search(r"https?://([^/]+)", found_url)
                if domain_match:
                    return_dict['domain'] = domain_match.group(1)
                else:
                    return_dict['domain'] = "unknown"
                
                token_match = re.search(r"/secure/([^/]+)/", found_url)
                if token_match:
                    return_dict['token'] = token_match.group(1)
                else:
                    return_dict['token'] = "none"
                    
                return_dict['full_url'] = found_url
            
            browser.close()
    except Exception: pass
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

def process_game_get_m3u8(match_url, team_key):
    res2 = run_with_timeout(scrape_m3u8_worker, (match_url, team_key), 25)
    if res2 and 'full_url' in res2:
        return res2
    return None

def main():
    try:
        subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "Xvfb"], stderr=subprocess.DEVNULL)

        match_started, final_matches, from_now_matches = fetch_home_matches()
        push_msg = ""
        game_json_data = {}

        print(f"{GREEN}Live: {len(match_started)}{RESET}")
        push_msg += f"Live: {len(match_started)}\n"

        for i, m in enumerate(match_started, 1):
            display_name = m['display_name']
            team_key = m['team_key']
            
            print(f"\n======================================")
            print(f"{i}. {display_name}")
            push_msg += f"{i}. {display_name}\n"
            
            m3u8_info = process_game_get_m3u8(m['url'], team_key)
            
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

        # 删除了 Final 和 Future 的输出

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
