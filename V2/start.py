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

DATA_FILE = "game.json"
BASE_URL = "https://www.nbabite.is/"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# ================= 核心逻辑 =================

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
            page.goto(BASE_URL, timeout=30000, wait_until="domcontentloaded")
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

def scrape_m3u8_worker(url, return_dict):
    display = Display(visible=0, size=(1280, 720))
    display.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=['--no-sandbox'])
            context = browser.new_context(user_agent=HEADERS['User-Agent'])
            page = context.new_page()

            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            
            start_time = time.time()
            found_url = None
            
            while time.time() - start_time < 25:
                try:
                    for frame in page.frames:
                        res = frame.evaluate("""() => {
                            try {
                                if (window.jwplayer) return window.jwplayer(0).getConfig().file;
                                if (window.config) return window.config.file;
                                for (let k in window) {
                                    if (typeof window[k] === 'string' && window[k].includes('.m3u8')) return window[k];
                                }
                            } catch(e) {}
                            return null;
                        }""") 
                        if res and "http" in res:
                            found_url = res
                            break
                except: pass
                
                if found_url: break
                time.sleep(1)

            if found_url:
                match = re.search(r"https://([^/]+)/secure/([^/]+)/", found_url)
                if match:
                    return_dict['domain'] = match.group(1)
                    return_dict['token'] = match.group(2)
                    return_dict['full_url'] = found_url
            
            browser.close()
    except: pass
    finally: display.stop()

# ================= 核心修改：多进程封装器 =================

def run_with_timeout(func, args, timeout):
    manager = multiprocessing.Manager()
    return_dict = manager.dict()
    
    # 启动子进程
    p = multiprocessing.Process(target=func, args=(*args, return_dict))
    p.start()
    
    # 等待结果或超时
    p.join(timeout)
    
    if p.is_alive():
        print(f"    [!] 进程超时({timeout}s)，强制终止...")
        p.terminate()
        p.join()
        subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "Xvfb"], stderr=subprocess.DEVNULL)
        return None
    
    return return_dict

def process_game(game):
    team_key, display_name = parse_teams(game['raw_name'])
    print(f"\n>>> 处理: {display_name} (Key: {team_key})")
    
    res1 = run_with_timeout(get_stream_url_worker, (game['url'],), 20)
    stream_url = res1.get('url') if res1 else None
    
    if not stream_url:
        print(f"    [-] 未找到中间页，跳过")
        return None
        
    print(f"    -> 中间页: {stream_url[:40]}...")

    res2 = run_with_timeout(scrape_m3u8_worker, (stream_url,), 35)
    
    if res2 and 'domain' in res2:
        print(f"    [+] 成功: {res2['domain']}")
        return {
            "key": team_key, "name": display_name,
            "domain": res2['domain'], "token": res2['token'],
            "full_url": res2['full_url'], "updated_at": time.time()
        }
    else:
        print("    [-] 抓取失败或超时")
        return None

def main():
    try:
        subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)
        
        matches = fetch_home_matches()
        if not matches:
            print("未发现比赛")
            return

        print(f"共发现 {len(matches)} 场比赛。")
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
            print(f"\n[完成] 已保存 {len(final_data)} 场数据")
        else:
            print("\n[结束] 本次未抓取到数据")
            
    except KeyboardInterrupt:
        print("\n[!] 用户中断")
        subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    main()
