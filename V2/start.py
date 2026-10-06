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

warnings.filterwarnings("ignore")

DATA_FILE = "game.json"
BASE_URL = "https://www.nbabite.is/"
FOXTREND_URL = "https://foxtrend.app/"
# 对外播放地址前缀（Flask 的 /<team_key>/index.m3u8 经该域名对外）
PUBLIC_BASE = "https://sports.imeet.eu.org"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# 提速：直接拦截图片/样式/字体，不加载
BLOCKED_TYPES = {"image", "stylesheet", "font"}

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

# ================= 辅助函数 (强制映射全称作为 Docker Key) =================
def parse_teams(raw_text):
    clean_name = raw_text.replace("Match Started", "").replace("Live Now", "").replace("Live", "").strip()
    clean_name = re.sub(r'\s+', ' ', clean_name)

    split_patterns = [r'\s+vs\.?\s+', r'\s+v\.s\.\s+', r'\s+v\.\s+', r'\s+-\s+', r'\s+@\s+', r'\s+🆚\s+']
    team1, team2 = "", ""
    for pattern in split_patterns:
        parts = re.split(pattern, clean_name, flags=re.IGNORECASE)
        if len(parts) >= 2:
            team1 = parts[0].strip()
            team2 = " ".join(parts[1:]).strip()
            break

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

    if not team1:
        words = clean_name.split()
        if len(words) >= 2:
            mid = len(words) // 2
            team1 = ' '.join(words[:mid])
            team2 = ' '.join(words[mid:])
        else:
            team1 = clean_name

    display_name = f"{team1} — {team2}" if team2 else team1

    team1_lower = team1.lower()
    alias_map = {
        "l.a. clippers": "losangelesclippers", "la clippers": "losangelesclippers", "clippers": "losangelesclippers",
        "l.a. lakers": "losangeleslakers", "la lakers": "losangeleslakers", "lakers": "losangeleslakers",
        "sixers": "philadelphia76ers", "76ers": "philadelphia76ers",
        "cavs": "clevelandcavaliers", "mavs": "dallasmavericks",
        "t-wolves": "minnesotatimberwolves", "okc": "oklahomacitythunder"
    }

    home_key = ""
    for alias, std_key in alias_map.items():
        if alias in team1_lower:
            home_key = std_key
            break

    if not home_key:
        words = re.findall(r'[a-z0-9]+', team1_lower)
        for team in STANDARD_NBA_TEAMS:
            team_std_lower = team.lower()
            for w in words:
                if len(w) >= 3 and w in team_std_lower:
                    home_key = team_std_lower.replace(" ", "")
                    break
            if home_key: break

    if not home_key:
        home_key = re.sub(r'[^a-zA-Z0-9]', '', team1).lower()

    return home_key, display_name, team1, team2

# ================= 抓取主页 (只抓 NBA 区域) =================
def fetch_home_matches():
    matches = []
    print("[*] 正在获取比赛列表...")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS['User-Agent'])
            page.goto(BASE_URL, timeout=12000, wait_until="domcontentloaded")
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
                        if "Match Started" in text:
                            href = a['href']
                            if href.startswith("/"): href = BASE_URL.rstrip("/") + href
                            matches.append({"raw_name": text, "url": href})

            browser.close()
        except Exception as e:
            print(f"Error fetching home: {e}")
            pass
    return matches

# ================= foxtrend.app 取篮球直播流地址 =================
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

# ================= 进入播放器，激活并提取 M3U8 =================
# 2026-10-06 修：比赛页有多个备用源（a.sr 的 data-e 即 embed 直链），
# 上游源会波动，逐个试源，哪个先出 m3u8 用哪个。
def scrape_m3u8_worker(stream_url, return_dict):
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
            # 带上来源 Referer，防止被目标播放器秒封
            context = browser.new_context(
                user_agent=HEADERS['User-Agent'],
                extra_http_headers={"Referer": stream_url}
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
                    if ".m3u8" in u and "http" in u:
                        if "google" not in u and "favicon" not in u:
                            captured_urls.append(u)
                except: pass

            page.on("request", handle_request)

            def pick_valid():
                valid = [u for u in captured_urls if "secure" in u or "mono" in u or "playlist" in u]
                return valid[-1] if valid else None

            def js_mem_scan():
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
                            return res
                except: pass
                return None

            # 1) 先打开比赛页，收集全部备用源
            feeds = []
            try:
                page.goto(stream_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1200)
                feeds = page.evaluate("""() => {
                    const out = [];
                    document.querySelectorAll('a.sr[data-e]').forEach(a => {
                        out.push(a.getAttribute('data-e'));
                    });
                    return out;
                }""") or []
            except: pass

            # 目标顺序：比赛页本身（含默认 iframe）→ 各个备用 embed 直链
            targets, seen = [], set()
            for t in [stream_url] + [f for f in feeds if f]:
                if t not in seen:
                    seen.add(t)
                    targets.append(t)

            found_url, feed_idx = None, -1

            # 2) 逐个试源
            for idx, target in enumerate(targets):
                captured_urls.clear()
                try:
                    page.goto(target, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1000)
                except: pass

                # 击碎广告遮罩
                try:
                    page.mouse.click(640, 360)
                    page.wait_for_timeout(300)
                    page.mouse.click(640, 360)
                except: pass

                t0 = time.time()
                js_round = 0
                while not found_url and time.time() - t0 < 6:
                    js_round += 1
                    if js_round % 3 == 0:
                        mem = js_mem_scan()
                        if mem:
                            found_url = mem
                            captured_urls.append(mem)
                            break
                    try: page.mouse.click(640, 360)
                    except: pass
                    page.wait_for_timeout(500)
                    found_url = pick_valid()

                if found_url:
                    feed_idx = idx
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
                    return_dict['referer'] = stream_url  # ★ 记录播放器来源
                    return_dict['feed'] = f"{feed_idx + 1}/{len(targets)}"
            else:
                return_dict['debug_feeds'] = len(targets)

            browser.close()
    except Exception as e:
        print(f"  [!] 提取 M3U8 异常: {e}")
    finally:
        display.stop()

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

def process_game(args):
    game, foxtrend_list = args
    team_key, display_name, team1, team2 = parse_teams(game['raw_name'])

    # 混合逻辑：nbabite 取赛程，foxtrend 取流地址
    fmatch = match_foxtrend(team1, team2, foxtrend_list)
    if not fmatch:
        print(f"[-] {display_name}: foxtrend无匹配")
        return None
    stream_url = fmatch['url']

    res2 = run_with_timeout(scrape_m3u8_worker, (stream_url,), 75)

    if res2 and 'domain' in res2:
        full_url = res2['full_url']
        domain_match = re.search(r"https?://([^/]+)", full_url)
        token_match = re.search(r"/secure/([^/]+)/", full_url)
        return {
            "key": team_key,
            "name": display_name,
            "domain": domain_match.group(1) if domain_match else res2['domain'],
            "token": token_match.group(1) if token_match else "none",
            "full_url": full_url,
            "referer": res2.get('referer', stream_url),
            "updated_at": time.time()
        }
    else:
        n = res2.get('debug_feeds') if res2 else 0
        print(f"[-] {display_name}: 抓流失败" + (f"（试了{n}个源）" if n else ""))
        return None

def main():
    try:
        subprocess.run(["pkill", "-9", "chrome"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "Xvfb"], stderr=subprocess.DEVNULL)

        # 提速：两个数据源并行抓
        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(fetch_home_matches)
            f2 = ex.submit(fetch_foxtrend_basketball)
            matches = f1.result()
            foxtrend_list = f2.result()

        if not matches:
            print("No matches found or parsing failed.")
            return

        print(f"Found {len(matches)} live matches, {len(foxtrend_list)} foxtrend basketball streams.")
        final_data = {}
        ordered = []

        # 提速：多场比赛并行抓流（最多3路）
        with ThreadPoolExecutor(max_workers=min(3, len(matches))) as ex:
            for res in ex.map(process_game, [(g, foxtrend_list) for g in matches]):
                if res and res['key'] != 'unknown':
                    final_data[res['key']] = res
                    ordered.append(res)

        for i, r in enumerate(ordered, 1):
            print(f"{i}. {r['name']}\n  {PUBLIC_BASE}/{r['key']}/index.m3u8")

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
