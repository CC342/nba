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

# ================= 辅助函数 =================

def parse_teams(raw_text):
    text = raw_text.replace("Match Started", "").strip()
    clean_text = re.sub(r'vs|v\.s\.|v\.|-|@', ' ', text, flags=re.IGNORECASE)
    words = clean_text.split()
    if len(words) >= 4:
        mid = len(words) // 2
        home_key = "".join(w.lower() for w in words[:mid])
        display_name = " ".join(words[:mid]) + " vs " + " ".join(words[mid:])
        return home_key, display_name
    return "unknown", text

def fetch_home_matches():
    matches = []
    print("[*] 正在获取比赛列表...")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS['User-Agent'])
            page.goto(BASE_URL, timeout=15000, wait_until="domcontentloaded")
            content = page.content()
            if "not started" in content.lower() or "will begin" in content.lower():
                print("    [-] 比赛未开始")
            else:
                soup = BeautifulSoup(content, "html.parser")
                for a in soup.find_all("a", href=True):
                    text = a.get_text(separator=" ", strip=True)
                    if "Match Started" in text:
                        href = a['href']
                        if href.startswith("/"): href = BASE_URL.rstrip("/") + href
                        matches.append({"raw_name": text, "url": href})
            browser.close()
        except Exception: pass
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
                if "sportsbest" in td.get_text(strip=True).lower():
                    onclick = td.get("onclick")
                    m = re.search(r'view\((\d+)\)', onclick)
                    if m:
                        inp = soup.find("input", id=f"linkk{m.group(1)}")
                        if inp: return_dict['url'] = inp.get("value")
                    break
            browser.close()
    except: pass
    finally: display.stop()

# ================= 核心 Worker 2: 强力抓取 M3U8 (与 nba.py 同步) =================

def scrape_m3u8_worker(url, return_dict):
    """
    【HFS版】混合嗅探 Worker
    1. 网络监听 (page.on 'request')
    2. 模拟点击激活
    3. 内存扫描
    """
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
                    '--autoplay-policy=no-user-gesture-required'
                ]
            )
            context = browser.new_context(user_agent=HEADERS['User-Agent'])
            page = context.new_page()
            
            # ★★★ 1. 网络监听 ★★★
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

            start_time = time.time()
            found_url = None
            
            # ★★★ 2. 循环尝试 ★★★
            while time.time() - start_time < 35:
                # 优先检查网络监听
                if captured_urls:
                    found_url = captured_urls[-1]
                    break
                
                # 点击激活
                try:
                    page.mouse.click(640, 360)
                except: pass
                
                # 内存扫描
                try:
                    for frame in page.frames:
                        res = frame.evaluate("""() => {
                            try {
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
                
                time.sleep(3)

            if found_url:
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
    
    # 1. Get Stream Page
    res1 = run_with_timeout(get_stream_url_worker, (game['url'],), 20)
    stream_url = res1.get('url') if res1 else None
    
    if not stream_url:
        print(f"    [-] No stream page found")
        return None
        
    # 2. Get M3U8
    res2 = run_with_timeout(scrape_m3u8_worker, (stream_url,), 40)
    
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
            print("No matches found")
            return

        print(f"Found {len(matches)} matches.")
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
            print("\n[Done] No data captured")
            
    except KeyboardInterrupt:
        print("\n[!] User Interrupted")
        subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    main()
