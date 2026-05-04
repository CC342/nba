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

DATA_FILE = "/home/nba/game.json"
BASE_URL = "https://www.nbabite.is/"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

RED = "\033[1;91m"
GREEN = "\033[1;92m"
YELLOW = "\033[1;93m"
RESET = "\033[0m"

NBA_TEAMS = [
    "Philadelphia 76ers", "Milwaukee Bucks", "Chicago Bulls", "Cleveland Cavaliers", 
    "Boston Celtics", "L.A. Clippers", "LA Clippers", "L.A.Clippers", "Clippers",
    "Memphis Grizzlies", "Atlanta Hawks", "Miami Heat", "Charlotte Hornets", "Utah Jazz", 
    "Sacramento Kings", "New York Knicks", "Los Angeles Lakers", "L.A. Lakers", "Lakers",
    "Orlando Magic", "Dallas Mavericks", "Brooklyn Nets", "Denver Nuggets", "Indiana Pacers", 
    "New Orleans Pelicans", "Detroit Pistons", "Toronto Raptors", "Houston Rockets", 
    "San Antonio Spurs", "Phoenix Suns", "Oklahoma City Thunder", "Minnesota Timberwolves", 
    "Portland Trail Blazers", "Golden State Warriors", "Washington Wizards"
]

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

# ================= 辅助函数 =================

def format_final_name(raw_text):
    clean = raw_text.replace("Final", "").replace("Watch Highlights", "").strip()
    team1 = None
    for team in NBA_TEAMS:
        if clean.startswith(team):
            team1 = team
            break
    if not team1: return clean
    rest = clean[len(team1):].strip()
    m1 = re.match(r'^(\d+)', rest)
    if not m1: return clean
    score1 = m1.group(1)
    rest = rest[len(score1):].strip()
    team2 = None
    for team in NBA_TEAMS:
        if rest.startswith(team):
            team2 = team
            break
    if not team2: return clean
    score2 = rest[len(team2):].strip()
    return f"{team1} {score1} — {score2} {team2}"

def format_from_now_name(raw_text):
    raw_lower = raw_text.lower()
    patterns = [
        (r'(\d+)\s*hours?\s*and\s*(\d+)\s*minutes? from now', lambda h, m: f"{int(h):02d}:{int(m):02d} Later"),
        (r'(\d+)\s*hours? from now', lambda h: f"{int(h):02d}:00 Later"),
        (r'(\d+)\s*minutes? from now', lambda m: f"00:{int(m):02d} Later"),
        (r'(\d+)\s*day[s]? from now', lambda d: f"{int(d)*24}:00 Later"),
    ]
    time_str = ""
    for pattern, func in patterns:
        match = re.search(pattern, raw_lower)
        if match:
            time_str = func(*match.groups())
            raw_text = re.sub(pattern, "", raw_text, flags=re.I)
            break
    t1, t2 = parse_match_name(raw_text)
    if t1 and t2: return f"{time_str}  {t1}  🆚  {t2}"
    return f"{time_str}  {raw_text.strip()}"

def parse_match_name(raw_name):
    clean_name = raw_name.replace("Match Started", " ").strip()
    clean_name = re.sub(r'\s+', ' ', clean_name)
    team1, team2 = "", ""
    for team in NBA_TEAMS:
        if clean_name.lower().startswith(team.lower()):
            team1 = team
            clean_name = clean_name[len(team):].strip()
            break
    if clean_name:
        for team in NBA_TEAMS:
            if clean_name.lower().startswith(team.lower()):
                team2 = team
                break
    if not team1 or not team2:
        words = re.findall(r'[A-Z0-9][a-z0-9]*(?:\s[A-Z0-9][a-z0-9]*)*', raw_name.replace("Match Started", ""))
        if len(words) >= 2:
            mid = len(words) // 2
            return ' '.join(words[:mid]), ' '.join(words[mid:])
        return raw_name, ""
    return team1, team2

def parse_teams_for_key(raw_text):
    text = raw_text.replace("Match Started", "").strip()
    clean_text = re.sub(r'vs|v\.s\.|v\.|-|@', ' ', text, flags=re.IGNORECASE)
    words = clean_text.split()
    if len(words) >= 4:
        mid = len(words) // 2
        home_words = words[:mid]
        home_key = "".join(w.lower() for w in home_words)
        return home_key
    return "unknown"

# ================= 抓取逻辑 =================

def fetch_home_matches():
    match_started, final_matches, from_now_matches = [], [], []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS['User-Agent'])
            page.goto(BASE_URL, timeout=15000, wait_until="domcontentloaded")
            content = page.content()
            soup = BeautifulSoup(content, "html.parser")
            
            for a in soup.find_all("a", href=True):
                text = a.get_text(separator=" ", strip=True)
                href = a['href']
                if href.startswith("/"): href = BASE_URL.rstrip("/") + href
                low = text.lower()
                if "match started" in low:
                    match_started.append({"raw_name": text, "url": href})
                elif "final" in low:
                    final_matches.append({"raw_name": text, "url": href, "name": format_final_name(text)})
                elif "from now" in low:
                    from_now_matches.append({"raw_name": text, "url": href, "name": format_from_now_name(text)})
            browser.close()
        except Exception: pass
    return match_started, final_matches, from_now_matches

def get_stream_url_worker(match_url, return_dict):
    display = Display(visible=0, size=(1280, 720))
    display.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=['--no-sandbox'])
            page = browser.new_page(user_agent=HEADERS['User-Agent'])
            page.goto(match_url, timeout=15000, wait_until="domcontentloaded")
            content = page.content()
            soup = BeautifulSoup(content, "html.parser")
            for td in soup.find_all("td"):
                text_lower = td.get_text(strip=True).lower()
                if "sportsbest" in text_lower or "admin" in text_lower:
                    onclick = td.get("onclick")
                    if onclick:
                        m = re.search(r'view\((\d+)\)', onclick)
                        if m:
                            inp = soup.find("input", id=f"linkk{m.group(1)}")
                            if inp: return_dict['url'] = inp.get("value")
                    break
            browser.close()
    except: pass
    finally: display.stop()

def scrape_m3u8_worker(url, return_dict):
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
            
            # 【核心优化】：智能打断函数
            def smart_wait(ms):
                """每 0.2 秒检查一次，一旦拿到 m3u8 立即停止等待并返回 True"""
                steps = max(1, int(ms / 200))
                for _ in range(steps):
                    if captured_urls: return True
                    page.wait_for_timeout(200)
                return False
            
            # 1. 网络监听
            def handle_request(request):
                try:
                    u = request.url
                    if ".m3u8" in u and "http" in u:
                        if "google" not in u and "favicon" not in u:
                            captured_urls.append(u)
                except: pass
            
            page.on("request", handle_request)
            
            # 访问页面
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception: pass

            # 页面加载完先看一眼有没有抓到
            if not captured_urls:
                smart_wait(2000) 

            # 2. 模拟点击 admin
            if not captured_urls:
                try:
                    clicked = False
                    # 主页面找
                    try:
                        admin_locator = page.locator("text=/admin/i").locator("visible=true").first
                        if admin_locator.count() > 0:
                            admin_locator.click(force=True, timeout=3000)
                            clicked = True
                    except Exception: pass

                    # iframe找
                    if not clicked:
                        for i, frame in enumerate(page.frames):
                            try:
                                f_locator = frame.locator("text=/admin/i").locator("visible=true").first
                                if f_locator.count() > 0:
                                    f_locator.click(force=True, timeout=3000)
                                    clicked = True
                                    break
                            except: pass
                    
                    if clicked:
                        smart_wait(5000) 

                except Exception: pass

            # 3. 兜底轮询
            if not captured_urls:
                start_time = time.time()
                while time.time() - start_time < 20:
                    if captured_urls: break
                    
                    try: page.mouse.click(640, 360)
                    except: pass
                    
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
                    
                    if smart_wait(2000):
                        break 

            # ========== 最终处理成果 ==========
            if captured_urls:
                found_url = captured_urls[-1]
                match = re.search(r"https://([^/]+)/secure/([^/]+)/", found_url)
                if match:
                    return_dict['domain'] = match.group(1)
                    return_dict['token'] = match.group(2)
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

def process_game_get_m3u8(match_url):
    res1 = run_with_timeout(get_stream_url_worker, (match_url,), 25)
    stream_url = res1.get('url') if res1 else match_url  
    
    if not stream_url: return None
        
    res2 = run_with_timeout(scrape_m3u8_worker, (stream_url,), 75)
    if res2 and 'domain' in res2:
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
            team1, team2 = parse_match_name(m['raw_name'])
            display_name = f"{team1} — {team2}"
            print(f"\n{i}. {display_name}")
            push_msg += f"{i}. {display_name}\n"
            
            m3u8_info = process_game_get_m3u8(m['url'])
            
            if m3u8_info:
                team_key = parse_teams_for_key(m['raw_name'])
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

        push_msg += "\n"
        
        print(f"\n{RED}Final: {len(final_matches)}{RESET}")
        push_msg += f"Final: {len(final_matches)}\n"
        for i, m in enumerate(final_matches, 1):
            print(f"{i}. {m['name']}")
            push_msg += f"{i}. {m['name']}\n"

        push_msg += "\n"
        
        print(f"\n{YELLOW}Future: {len(from_now_matches)}{RESET}")
        push_msg += f"Future: {len(from_now_matches)}\n"
        for i, m in enumerate(from_now_matches, 1):
            print(f"{i}. {m['name']}")
            push_msg += f"{i}. {m['name']}\n"

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
