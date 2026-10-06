import requests
import json
import time
import re
import os
import sys
import subprocess
import warnings
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from pyvirtualdisplay import Display
from dotenv import load_dotenv

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
NBABITE_URL = "https://www.nbabite.is/"
FOXTREND_URL = "https://foxtrend.app/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"}

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

# 提速：直接拦截图片/样式/字体，不加载
BLOCKED_TYPES = {"image", "stylesheet", "font"}

# ================= 消息推送 =================

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try: requests.get(url, params={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except: pass

def send_wechat(msg):
    token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WX_CORP_ID}&corpsecret={WX_SECRET}"
    try:
        r = requests.get(token_url, timeout=10).json()
        access_token = r.get("access_token")
        if access_token:
            send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
            data = {"touser": "@all", "msgtype": "text", "agentid": int(WX_AGENT_ID), "text": {"content": msg}, "safe": 0}
            requests.post(send_url, json=data, timeout=10)
    except: pass

# ================= 文本解析 =================

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

# ================= 数据源1: nbabite.is 取 NBA 赛程 =================

def fetch_nbabite_matches():
    match_started, final_matches, from_now_matches = [], [], []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS['User-Agent'])
            page.goto(NBABITE_URL, timeout=12000, wait_until="domcontentloaded")
            content = page.content()
            soup = BeautifulSoup(content, "html.parser")

            nba_header = None
            for span in soup.find_all("span", class_="text-white"):
                if "nba streams" in span.get_text(strip=True).lower():
                    nba_header = span
                    break

            if nba_header:
                nba_container = nba_header.find_next("div", class_="row")
                if nba_container:
                    for a in nba_container.find_all("a", href=True):
                        text = a.get_text(separator=" ", strip=True)
                        low = text.lower()
                        if "match started" in low:
                            t1, t2 = parse_match_name(text)
                            match_started.append({"raw_name": text, "team1": t1, "team2": t2})
                        elif "final" in low:
                            final_matches.append({"name": format_final_name(text)})
                        elif "from now" in low:
                            from_now_matches.append({"name": format_from_now_name(text)})
            browser.close()
        except: pass
    return match_started, final_matches, from_now_matches

# ================= 数据源2: foxtrend.app 取直播流地址 =================

def fetch_foxtrend_basketball():
    results = []
    seen_urls = set()
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS['User-Agent'])
            page.goto(FOXTREND_URL, timeout=12000, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            try:
                live_btn = page.locator('a.see-all-live[data-live="1"]').first
                if live_btn.count() > 0:
                    live_btn.click(force=True, timeout=1500)
                    page.wait_for_timeout(800)
            except: pass
            content = page.content()
            browser.close()
        except:
            return []

    soup = BeautifulSoup(content, "html.parser")
    for card in soup.find_all('a', class_='watch'):
        if not any(c.startswith('card-sport-') and 'basketball' in c for c in card.get('class', [])):
            continue
        href = card.get('href', '')
        if not href:
            continue
        pill = card.find('span', class_='card-pill')
        if not (pill and 'live' in pill.get_text(strip=True).lower()):
            continue

        # 注：旧版 ?source=admin 参数 fxtrend.st 已不识别（带与不带返回相同页面），
        # 直接使用卡片原链接；播放页默认激活的即是网站推荐的第一个 HD 源（Core 1）。
        if href.startswith("/"): href = FOXTREND_URL.rstrip("/") + href
        href_target = href.split('?')[0]
        if href_target in seen_urls:
            continue
        seen_urls.add(href_target)

        title_tag = card.find('h3', class_='card-title')
        title_text = title_tag.get_text(strip=True) if title_tag else card.get('data-watch-title', '')
        if not title_text:
            continue
        results.append({"raw_name": title_text, "url": href_target})
    return results

# ================= 队名匹配 =================

def team_words(name):
    w = set(re.sub(r'[^a-z0-9 ]', ' ', name.lower()).split())
    w -= {'l', 'a'}
    return w

def match_foxtrend(team1, team2, foxtrend_list):
    t1w, t2w = team_words(team1), team_words(team2)
    if not t1w or not t2w:
        return None
    best, best_score = None, 0
    for f in foxtrend_list:
        fw = team_words(f['raw_name'])
        score = len(t1w & fw) / len(t1w) + len(t2w & fw) / len(t2w)
        if score > best_score:
            best_score, best = score, f
    return best if best and best_score >= 1.0 else None

# ================= 抓 m3u8 =================
# 播放页默认激活的即网站推荐的第一个 HD 源（Core 1），上游波动时依次试备用源，
# 哪个先出 m3u8 用哪个。

def scrape_m3u8_worker(url, return_dict):
    display = Display(visible=0, size=(1280, 720))
    display.start()
    captured_urls = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox',
                      '--autoplay-policy=no-user-gesture-required', '--disable-web-security']
            )
            context = browser.new_context(
                user_agent=HEADERS['User-Agent'],
                extra_http_headers={"Referer": url}
            )
            page = context.new_page()

            # 提速：拦截图片/样式/字体
            def block_res(route):
                if route.request.resource_type in BLOCKED_TYPES:
                    route.abort()
                else:
                    route.continue_()
            page.route("**/*", block_res)

            def handle_request(request):
                try:
                    u = request.url
                    if ".m3u8" in u and "http" in u and "google" not in u and "favicon" not in u:
                        captured_urls.append(u)
                except: pass
            page.on("request", handle_request)

            def pick_valid():
                valid = [u for u in captured_urls if "secure" in u or "mono" in u or "playlist" in u]
                return valid[-1] if valid else None

            # 1) 打开比赛页，收集全部备用源（a.sr 的 data-e 即 embed 直链）
            feeds = []
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1200)
                feeds = page.evaluate("""() => {
                    const out = [];
                    document.querySelectorAll('a.sr[data-e]').forEach(a => {
                        out.push(a.getAttribute('data-e'));
                    });
                    return out;
                }""") or []
            except: pass

            # 目标顺序：比赛页本身（默认 HD 源）→ 各个备用 embed 直链
            targets, seen = [], set()
            for t in [url] + [f for f in feeds if f]:
                if t not in seen:
                    seen.add(t)
                    targets.append(t)

            # 2) 逐个试源
            found_url = None
            for target in targets:
                captured_urls.clear()
                try:
                    page.goto(target, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1000)
                except: pass

                try:
                    page.mouse.click(640, 360)
                    page.wait_for_timeout(300)
                    page.mouse.click(640, 360)
                except: pass

                t0 = time.time()
                js_round = 0
                while not found_url and time.time() - t0 < 6:
                    # JS 兜底每 3 轮才跑一次（慢），平时只轮询网络抓包
                    js_round += 1
                    if js_round % 3 == 0:
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
                            if found_url: break
                        except: pass
                    try: page.mouse.click(640, 360)
                    except: pass
                    page.wait_for_timeout(500)
                    found_url = pick_valid()
                if found_url:
                    break

            if not found_url and captured_urls:
                for u in reversed(captured_urls):
                    if "playlist.m3u8" in u or "index.m3u8" in u or "master.m3u8" in u or "secure" in u:
                        found_url = u
                        break
                if not found_url:
                    found_url = captured_urls[-1]

            if found_url:
                domain_match = re.search(r"https?://([^/]+)", found_url)
                token_match = re.search(r"/secure/([^/]+)/", found_url)
                if domain_match:
                    return_dict['domain'] = domain_match.group(1)
                    return_dict['token'] = token_match.group(1) if token_match else "none"
                    return_dict['full_url'] = found_url
                    return_dict['referer'] = url
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

def process_game_get_m3u8(match_url):
    res = run_with_timeout(scrape_m3u8_worker, (match_url,), 75)
    if res and 'full_url' in res:
        domain_match = re.search(r"https?://([^/]+)", res['full_url'])
        token_match = re.search(r"/secure/([^/]+)/", res['full_url'])
        if domain_match:
            res['domain'] = domain_match.group(1)
            res['token'] = token_match.group(1) if token_match else "none"
        return res
    return None

def scrape_one(args):
    """单场比赛抓流（供线程池调用），返回 (index, m3u8_info 或 None/无匹配标记)"""
    i, m, foxtrend_list = args
    fmatch = match_foxtrend(m['team1'], m['team2'], foxtrend_list)
    if not fmatch:
        return (i, "nomatch", None)
    info = process_game_get_m3u8(fmatch['url'])
    return (i, "ok" if info else "failed", info)

# ================= 主流程 =================

def main():
    try:
        subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "Xvfb"], stderr=subprocess.DEVNULL)

        # 提速：两个主页并行抓
        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(fetch_nbabite_matches)
            f2 = ex.submit(fetch_foxtrend_basketball)
            match_started, final_matches, from_now_matches = f1.result()
            foxtrend_list = f2.result()

        push_msg = ""
        game_json_data = {}

        print(f"{GREEN}Live: {len(match_started)}{RESET}")
        push_msg += f"Live: {len(match_started)}\n"

        # 提速：多场比赛并行抓流（最多3路）
        results = {}
        if match_started:
            with ThreadPoolExecutor(max_workers=min(3, len(match_started))) as ex:
                for i, status, info in ex.map(scrape_one,
                        [(i, m, foxtrend_list) for i, m in enumerate(match_started, 1)]):
                    results[i] = (status, info)

        for i, m in enumerate(match_started, 1):
            display_name = f"{m['team1']} — {m['team2']}"
            print(f"\n{i}. {display_name}")
            push_msg += f"{i}. {display_name}\n"

            status, m3u8_info = results.get(i, ("failed", None))
            if status == "nomatch":
                print(f"  {YELLOW}foxtrend无匹配{RESET}")
                push_msg += "  foxtrend无匹配\n"
            elif m3u8_info:
                team_key = parse_teams_for_key(m['raw_name'])
                game_json_data[team_key] = {
                    "key": team_key,
                    "name": display_name,
                    "domain": m3u8_info['domain'],
                    "token": m3u8_info['token'],
                    "full_url": m3u8_info['full_url'],
                    "referer": m3u8_info.get('referer', ''),
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
