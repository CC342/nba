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

warnings.filterwarnings("ignore")

# HFS 上通常直接放在当前目录
DATA_FILE = "game.json"
BASE_URL = "https://www.nbabite.is/"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# ================= 标准球队字典 =================
STANDARD_NBA_TEAMS = [
    "Philadelphia 76ers", "Milwaukee Bucks", "Chicago Bulls", "Cleveland Cavaliers", 
    "Boston Celtics", "Los Angeles Clippers", "Memphis Grizzlies", "Atlanta Hawks", 
    "Miami Heat", "Charlotte Hornets", "Utah Jazz", "Sacramento Kings", 
    "New York Knicks", "Los Angeles Lakers", "Orlando Magic", "Dallas Mavericks", 
    "Brooklyn Nets", "Denver Nuggets", "Indiana Pacers", "New Orleans Pelicans", 
    "Detroit Pistons", "Toronto Raptors", "Houston Rockets", "San Antonio Spurs", 
    "Phoenix Suns", "Oklahoma City Thunder", "Minnesota Timberwolves", 
    "Portland Trail Blazers", "Golden State Warriors", "Washington Wizards"
]

# ================= 辅助函数 (强制映射全称) =================

def parse_teams(raw_text):
    clean_name = raw_text.replace("Match Started", "").replace("Live Now", "").replace("Live", "").strip()
    clean_name = re.sub(r'\s+', ' ', clean_name)
    
    # 1. 优先使用连接符切割队伍名
    split_patterns = [r'\s+vs\.?\s+', r'\s+v\.s\.\s+', r'\s+v\.\s+', r'\s+-\s+', r'\s+@\s+', r'\s+🆚\s+']
    team1, team2 = "", ""
    for pattern in split_patterns:
        parts = re.split(pattern, clean_name, flags=re.IGNORECASE)
        if len(parts) >= 2:
            team1 = parts[0].strip()
            team2 = " ".join(parts[1:]).strip()
            break

    # 2. 如果没有明显分隔符，尝试传统匹配
    if not team1:
        for team in STANDARD_NBA_TEAMS:
            if clean_name.lower().startswith(team.lower()):
                team1 = team
                clean_name_rem = clean_name[len(team):].strip()
                clean_name_rem = re.sub(r'^[^a-zA-Z0-9]+', '', clean_name_rem).strip()
                break
        if team1:
            for team in STANDARD_NBA_TEAMS:
                if clean_name_rem.lower().startswith(team.lower()):
                    team2 = team
                    break
                    
    # 3. 兜底对半分
    if not team1:
        words = clean_name.split()
        if len(words) >= 2:
            mid = len(words) // 2
            team1 = ' '.join(words[:mid])
            team2 = ' '.join(words[mid:])
        else:
            team1 = clean_name
            
    display_name = f"{team1} — {team2}" if team2 else team1

    # ==== 4. 开始强制映射 Team1 作为 Docker Key ====
    team1_lower = team1.lower()
    alias_map = {
        "l.a. clippers": "losangelesclippers", "la clippers": "losangelesclippers", "clippers": "losangelesclippers",
        "l.a. lakers": "losangeleslakers", "la lakers": "losangeleslakers", "lakers": "losangeleslakers",
        "sixers": "philadelphia76ers", "76ers": "philadelphia76ers",
        "cavs": "clevelandcavaliers", "mavs": "dallasmavericks",
        "t-wolves": "minnesotatimberwolves", "okc": "oklahomacitythunder"
    }
    
    home_key = ""
    # 检查别名
    for alias, std_key in alias_map.items():
        if alias in team1_lower:
            home_key = std_key
            break
            
    # 核心映射查找
    if not home_key:
        words = re.findall(r'[a-z0-9]+', team1_lower)
        for team in STANDARD_NBA_TEAMS:
            team_std_lower = team.lower()
            for w in words:
                # 至少3个字母才算有效关键词匹配
                if len(w) >= 3 and w in team_std_lower:
                    home_key = team_std_lower.replace(" ", "")
                    break
            if home_key: break
            
    # 最终兜底防错
    if not home_key:
        home_key = re.sub(r'[^a-zA-Z0-9]', '', team1).lower()

    return home_key, display_name

def fetch_home_matches():
    matches = []
    print("[*] 正在获取比赛列表...")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS['User-Agent'])
            page.goto(BASE_URL, timeout=15000, wait_until="domcontentloaded")
            content = page.content()
            
            soup = BeautifulSoup(content, "html.parser")
            for a in soup.find_all("a", href=True):
                text = a.get_text(separator=" ", strip=True)
                if "Match Started" in text:
                    href = a['href']
                    if href.startswith("/"): href = BASE_URL.rstrip("/") + href
                    matches.append({"raw_name": text, "url": href})
            
            browser.close()
        except Exception as e: 
            print(f"Error fetching home: {e}")
            pass
    return matches

# ================= 核心 Worker 1: 获取中间页 =================

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

# ================= 核心 Worker 2: 强力抓取 M3U8 =================

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
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except: pass

            if not captured_urls:
                smart_wait(2000)

            if not captured_urls:
                try:
                    clicked = False
                    try:
                        admin_locator = page.locator("text=/admin/i").locator("visible=true").first
                        if admin_locator.count() > 0:
                            admin_locator.click(force=True, timeout=3000)
                            clicked = True
                    except: pass

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
                except: pass

            start_time = time.time()
            found_url = None
            
            while time.time() - start_time < 20:
                if captured_urls: break
                
                try: page.mouse.click(640, 360)
                except: pass
                
                try:
                    for frame in page.frames:
                        res = frame.evaluate("""() => {
                            try {
                                if (window.player && window.player.options) return window.player.options.source;
                                if (window.Clappr && window.Clappr.options) return window.Clappr.options.source;
                                if (window.jwplayer) return window.jwplayer(0).getConfig().file;
                                if (window.config && window.config.file) return window.config.file;
                                for (let k in window) {
                                    if (typeof window[k] === 'string' && window[k].includes('.m3u8') && window[k].includes('http')) return window[k];
                                }
                            } catch(e) {}
                            return null;
                        }""") 
                        if res:
                            captured_urls.append(res)
                            break
                except: pass
                
                if smart_wait(2000): break

            if captured_urls:
                found_url = captured_urls[-1]
                match = re.search(r"https://([^/]+)/secure/([^/]+)/", found_url)
                if match:
                    return_dict['domain'] = match.group(1)
                    return_dict['token'] = match.group(2)
                    return_dict['full_url'] = found_url
            
            browser.close()
    except: pass
    finally: display.stop()

# ================= 多进程封装 =================

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

def process_game(game):
    team_key, display_name = parse_teams(game['raw_name'])
    print(f"\n>>> Processing: {display_name}")
    
    res1 = run_with_timeout(get_stream_url_worker, (game['url'],), 20)
    stream_url = res1.get('url') if res1 else game['url']
    
    if not stream_url:
        print(f"    [-] No stream page found")
        return None
        
    res2 = run_with_timeout(scrape_m3u8_worker, (stream_url,), 75)
    
    if res2 and 'domain' in res2:
        print(f"    [+] SUCCESS: {res2['full_url'][:50]}...")
        return {
            "key": team_key, "name": display_name,
            "domain": res2['domain'], "token": res2['token'],
            "full_url": res2['full_url'], "updated_at": time.time()
        }
    else:
        print("    [-] Failed")
        return None

def main():
    try:
        subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "Xvfb"], stderr=subprocess.DEVNULL)
        
        matches = fetch_home_matches()
        if not matches:
            print("No matches found or parsing failed.")
            return

        print(f"Found {len(matches)} live matches.")
        final_data = {}

        for game in matches:
            res = process_game(game)
            if res and res['key'] != 'unknown':
                final_data[res['key']] = res

        if final_data:
            temp_file = DATA_FILE + ".tmp"
            with open(temp_file, "w", encoding='utf-8') as f:
                json.dump(final_data, f, indent=4, ensure_ascii=False)
            os.replace(temp_file, DATA_FILE)
            print(f"\n[Done] Saved {len(final_data)} matches to {DATA_FILE}")
        else:
            print("\n[Done] No streams captured")
            
    except KeyboardInterrupt:
        print("\n[!] User Interrupted")
        subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    main()

