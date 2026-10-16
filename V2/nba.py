import requests
import json
import time
import re
import os
import sys
import subprocess
import warnings
import multiprocessing
from datetime import datetime, timedelta, timezone
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
FOXTREND_URL = "https://fxt.app/"
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

# ================= 数据源1: ESPN 记分牌取 NBA 赛程 =================
# 公开接口免 key, dates 参数按美东日期解释
# 一次取美东今天+昨天: Final 按北京时间过滤出"今天"的; Live/Future 取美东今天

BJ_TZ = timezone(timedelta(hours=8))  # 北京时间无夏令时, 固定 UTC+8

def et_offset_hours(now_utc=None):
    """美东 UTC 偏移: 夏令时(3月第2周日~11月第1周日)为 -4, 否则 -5"""
    now_utc = now_utc or datetime.now(timezone.utc)
    y = now_utc.year
    dst_start = datetime(y, 3, 1) + timedelta(days=(6 - datetime(y, 3, 1).weekday()) % 7 + 7)
    dst_end = datetime(y, 11, 1) + timedelta(days=(6 - datetime(y, 11, 1).weekday()) % 7)
    dst_start_utc = dst_start.replace(tzinfo=timezone.utc) + timedelta(hours=7)
    dst_end_utc = dst_end.replace(tzinfo=timezone.utc) + timedelta(hours=6)
    return -4 if dst_start_utc <= now_utc < dst_end_utc else -5

def et_ymd(offset=0):
    et_now = datetime.now(timezone.utc) + timedelta(hours=et_offset_hours())
    return (et_now + timedelta(days=offset)).date().strftime("%Y%m%d")

def to_bj(utc_str):
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(BJ_TZ)
    except Exception:
        return None

def fetch_espn_matches():
    """ESPN 赛程: 返回 (match_started, final_matches, from_now_matches)"""
    match_started, final_matches, from_now_matches = [], [], []
    bj_today = datetime.now(BJ_TZ).date()
    try:
        seen = set()
        for off in (0, -1):  # 美东今天 + 昨天
            ymd = et_ymd(off)
            url = ("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
                   f"?dates={ymd}")
            events = requests.get(url, timeout=15).json().get("events", [])
            for e in events:
                eid = e.get("id")
                if eid in seen:
                    continue
                seen.add(eid)
                comp = (e.get("competitions") or [{}])[0]
                teams = {}
                for c in comp.get("competitors", []):
                    t = c.get("team", {})
                    teams[c.get("homeAway")] = (t.get("displayName", ""), c.get("score", "0"))
                if "away" not in teams or "home" not in teams:
                    continue
                (t_away, s_away), (t_home, s_home) = teams["away"], teams["home"]
                state = ((e.get("status") or {}).get("type") or {}).get("state")
                dt = to_bj(e.get("date", ""))
                if state == "in":
                    match_started.append({"raw_name": f"{t_away} vs {t_home}",
                                          "team1": t_away, "team2": t_home})
                elif state == "post":
                    if bj_today is None or (dt and dt.date() == bj_today):
                        final_matches.append({"name": f"{t_away} {s_away} — {s_home} {t_home}"})
                elif state == "pre":
                    bts = dt.strftime("%H:%M") if dt else ""
                    from_now_matches.append({"name": f"{bts}  {t_away}  🆚  {t_home}"})
    except Exception as ex:
        print(f"ESPN赛程失败: {ex}")
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
        p.join(5)
        if p.is_alive():
            p.kill()
            p.join(5)
        try:
            subprocess.run(["pkill", "-9", "-f", "ms-playwright"], stderr=subprocess.DEVNULL)
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
        subprocess.run(["pkill", "-9", "-f", "ms-playwright"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "Xvfb"], stderr=subprocess.DEVNULL)

        # 提速：两个主页并行抓（赛程走 ESPN）
        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(fetch_espn_matches)
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
        subprocess.run(["pkill", "-9", "-f", "ms-playwright"], stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    main()
