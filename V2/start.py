import json
import time
import re
import os
import sys
import subprocess
import warnings
import requests
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from pyvirtualdisplay import Display

warnings.filterwarnings("ignore")

DATA_FILE = "game.json"
FOXTREND_URL = "https://foxtrend.fyi/"
EVENT_BASE = "https://foxiy.st/event/"
PUBLIC_BASE = "https://sports.imeet.eu.org"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"}
START_VERSION = "start-docker-v3-20261031"  # 2026-10-31 Docker 定版：1140 不变，串行+重试+0.5s 递增+补点（照主机生产 v3）

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

def fetch_espn_live():
    """ESPN 直播赛程, 返回 [{"raw_name": "A vs B"}]"""
    matches = []
    print("[*] 正在获取比赛列表 (ESPN)...")
    try:
        seen = set()
        for off in (0, -1):
            ymd = et_ymd(off)
            url = ("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
                   f"?dates={ymd}")
            events = requests.get(url, timeout=15).json().get("events", [])
            for e in events:
                eid = e.get("id")
                if eid in seen:
                    continue
                seen.add(eid)
                state = ((e.get("status") or {}).get("type") or {}).get("state")
                if state != "in":
                    continue
                comp = (e.get("competitions") or [{}])[0]
                teams = {}
                for c in comp.get("competitors", []):
                    t = c.get("team", {})
                    teams[c.get("homeAway")] = t.get("displayName", "")
                if "away" not in teams or "home" not in teams:
                    continue
                matches.append({"raw_name": f"{teams['away']} vs {teams['home']}"})
    except Exception as ex:
        print(f"ESPN赛程失败: {ex}")
    return matches

def _card_started(card):
    """卡片是否已开打：tf-evlive 靠站点比分源翻转，会滞后真实跳球十几分钟；
    翻转前卡片是预定模式，带 <time data-ts> 开球时间戳，用它判断（完场卡会被站点撤下，不会残留）"""
    t = card.find("time")
    if not t:
        return False
    try:
        ts = int(t.get("data-ts") or 0)
    except (TypeError, ValueError):
        return False
    now = int(time.time())
    return ts - 600 <= now <= ts + 6 * 3600

def fetch_foxtrend_basketball():
    results = []
    seen_urls = set()
    try:
        _r = requests.get(FOXTREND_URL + "NBA", headers=HEADERS, timeout=5000)
        content = _r.text if _r.status_code == 200 else ""
        if not content or 'tf-ev' not in content:
            raise Exception("fallback")
    except:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                page = browser.new_page(user_agent=HEADERS['User-Agent'])
                page.goto(FOXTREND_URL + "NBA", timeout=12000, wait_until="commit")
                try:
                    page.wait_for_selector('a.tf-ev', timeout=3000)
                except:
                    pass
                content = page.content()
                browser.close()
            except:
                return []
    soup = BeautifulSoup(content, "html.parser")
    for sec in soup.find_all("section", class_="tf-lg"):
        name_tag = sec.find("span", class_="tf-lgname")
        lname = name_tag.get_text(strip=True) if name_tag else ""
        if not any(re.search(r"(?<![A-Za-z])" + k + r"(?![A-Za-z])", lname, re.I)
                   for k in ("NBA", "WNBA", "NBL")):
            continue
        for card in sec.find_all("a", class_="tf-ev"):
            if "tf-evlive" not in card.get("class", []) and not _card_started(card):
                continue
            href = card.get("href", "")
            if href.startswith("/game/"):
                href_target = EVENT_BASE + href[len("/game/"):]
            elif href.startswith("http"):
                href_target = href
            else:
                continue
            if href_target in seen_urls:
                continue
            seen_urls.add(href_target)
            title_text = (card.get("title") or "").strip()
            if not title_text:
                names = [s.get_text(strip=True) for s in card.find_all("span", class_="tf-evnm")]
                title_text = " vs ".join(n for n in names if n)
            if not title_text:
                continue
            results.append({"raw_name": title_text, "url": href_target})
    return results

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


def _info_from_url(found, url):
    dm = re.search(r"https?://([^/]+)", found)
    tm = re.search(r"/secure/([^/]+)/", found)
    if not dm:
        return None
    return {'domain': dm.group(1), 'token': tm.group(1) if tm else "none", 'full_url': found, 'referer': url}


def scrape_page(browser, url, wait_ms=1500):
    """返回 (info_or_None, detail_str)，detail 只记域名/步骤。等待期间每 300ms 补点，成功场抓到就提前退出。"""
    captured = []
    try:
        context = browser.new_context(user_agent=HEADERS['User-Agent'], extra_http_headers={"Referer": url})
        page = context.new_page()
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ("image", "font", "media") else route.continue_())
        page.on("request", lambda r: captured.append(r.url) if ".m3u8" in r.url else None)
        page.goto(url, wait_until="commit", timeout=15000)
        try:
            page.wait_for_selector('a.sr[data-e]', timeout=3000)
        except:
            pass
        feeds = page.evaluate("""() => {
            const els = [...document.querySelectorAll('a.sr[data-e]')];
            return els.map((a, idx) => ({idx: idx, text: (a.textContent || '').trim(), cls: a.className || '', data_e: a.getAttribute('data-e') || ''}));
        }""") or []
        if not feeds:
            context.close()
            return None, "no_feeds: 事件页无 a.sr[data-e]"
        ordered = []
        for f in feeds:
            if 'playing' in f.get('text', '').lower() or 'sr-on' in f.get('cls', ''):
                ordered.append(f)
        for f in feeds:
            if f not in ordered:
                ordered.append(f)
        if not ordered:
            ordered = [{'idx': -1, 'text': 'default', 'cls': ''}]
        src_log = []
        for f in ordered:
            captured.clear()
            _box = False
            if f['idx'] >= 0 and f is not ordered[0]:
                try:
                    page.evaluate(f"""() => {{
                        const els = [...document.querySelectorAll('a.sr[data-e]')];
                        if (els[{f['idx']}]) els[{f['idx']}].click();
                    }}""")
                    for _ in range(50):
                        try:
                            _src = page.evaluate("() => { const fr = document.querySelector('iframe'); return fr ? fr.src : ''; }")
                            if _src and f.get('data_e', '') and _src in f.get('data_e', ''):
                                break
                        except:
                            pass
                        page.wait_for_timeout(20)
                except:
                    pass
            try:
                box = page.evaluate("""() => {
                    const fr = document.querySelector('iframe');
                    if (!fr) return null;
                    const r = fr.getBoundingClientRect();
                    return [Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2)];
                }""")
                _box = bool(box)
                if box:
                    _steps = wait_ms // 10
                    _click_every = max(1, 300 // 10)
                    for _i in range(_steps):
                        if captured:
                            break
                        if _i % _click_every == 0:
                            try:
                                page.mouse.click(box[0], box[1])
                            except:
                                pass
                        page.wait_for_timeout(10)
                    for pg in list(context.pages):
                        if pg is not page:
                            try:
                                pg.close()
                            except:
                                pass
            except:
                pass
            src_log.append(f"idx{f['idx']}:box={int(_box)},cap={len(captured)}")
            if captured:
                valid = [u for u in captured if "secure" in u or "mono" in u or "playlist" in u]
                found = valid[-1] if valid else captured[-1]
                info = _info_from_url(found, url)
                context.close()
                if info:
                    return info, f"click: feeds={len(feeds)} src_idx={f['idx']} text={f.get('text','')[:20]} domain={info['domain']}"
        context.close()
        return None, f"no_m3u8: feeds={len(feeds)} sources=[{';'.join(src_log)}]"
    except Exception as ex:
        import traceback
        print(f"[scrape_page ERROR] url={url} err={ex}")
        traceback.print_exc()
        return None, f"exception: {type(ex).__name__}: {ex}"


def scrape_all_shared(matches, foxtrend_list):
    """串行 + 内部重试：返回成功列表（按原比赛顺序），失败场在同一次命令里重跑第 2、3 遍（等待 2.0s、2.5s）。"""
    ordered = []
    if not matches:
        return ordered
    # 先按比赛顺序准备每场的匹配信息，nomatch 不进重试（foxtrend 列表同一轮不会变）
    jobs = []
    for game in matches:
        team_key, display_name, team1, team2 = parse_teams(game['raw_name'])
        fmatch = match_foxtrend(team1, team2, foxtrend_list)
        jobs.append({"key": team_key, "name": display_name, "team1": team1, "team2": team2, "fmatch": fmatch, "info": None, "detail": "", "status": "nomatch" if not fmatch else "failed"})
    display = Display(visible=0, size=(1280, 720))
    display.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--autoplay-policy=no-user-gesture-required', '--disable-web-security'], executable_path='/root/.cache/ms-playwright/chromium-1140/chrome-linux/chrome')

            def run_one(job, wait_ms):
                if not job["fmatch"]:
                    return
                t0 = time.time()
                info, detail = scrape_page(browser, job["fmatch"]['url'], wait_ms=wait_ms)
                job["detail"] = f"{detail} ({time.time() - t0:.1f}s)"
                if info and 'domain' in info:
                    full_url = info['full_url']
                    dm = re.search(r"https?://([^/]+)", full_url)
                    tm = re.search(r"/secure/([^/]+)/", full_url)
                    job["info"] = {"key": job["key"], "name": job["name"], "domain": dm.group(1) if dm else info['domain'], "token": tm.group(1) if tm else "none", "full_url": full_url, "referer": info.get('referer', job["fmatch"]['url']), "updated_at": time.time()}
                    job["status"] = "ok"
                else:
                    job["status"] = "failed"

            # 第 1 遍：串行，等待 1.5s
            for job in jobs:
                if job["status"] == "nomatch":
                    print(f"[-] {job['name']}: foxtrend无匹配")
                    continue
                run_one(job, 1500)
            # 第 2、3 遍：只串行重跑失败场，等待 2.0s、2.5s
            for attempt in (2, 3):
                failed = [j for j in jobs if j["status"] == "failed"]
                if not failed:
                    break
                print(f"\n[Retry {attempt}] 失败场串行重跑 {len(failed)} 场…")
                for job in failed:
                    run_one(job, 1500 + (attempt - 1) * 500)
            for job in jobs:
                if job["status"] == "ok" and job["info"]:
                    ordered.append(job["info"])
                elif job["status"] == "failed":
                    print(f"[-] {job['name']}: 抓流失败 [detail] {job['detail']}")
                # nomatch 已在第 1 遍打印过，不重复
            browser.close()
    except Exception as ex:
        import traceback
        print(f"[scrape_all ERROR] err={ex}")
        traceback.print_exc()
    finally:
        display.stop()
    return ordered

def main():
    _t0 = time.time()
    print(f"[start.py] version={START_VERSION}")
    try:
        subprocess.run(["pkill", "-9", "-f", "ms-playwright"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "Xvfb"], stderr=subprocess.DEVNULL)
        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(fetch_espn_live)
            f2 = ex.submit(fetch_foxtrend_basketball)
            matches = f1.result()
            foxtrend_list = f2.result()
        if not matches:
            print("No matches found or parsing failed.")
            return
        print(f"Found {len(matches)} live matches, {len(foxtrend_list)} foxtrend basketball streams.")
        final_data = {}
        ordered = scrape_all_shared(matches, foxtrend_list)
        for res in ordered:
            if res and res['key'] != 'unknown':
                final_data[res['key']] = res
        for i, r in enumerate(ordered, 1):
            print(f"{i}. {r['name']}\n  {PUBLIC_BASE}/{r['key']}/play")
        print(f"\n[RESULT] 成功 {len(ordered)}/{len(matches)}")
        if final_data:
            temp_file = DATA_FILE + ".tmp"
            with open(temp_file, "w", encoding='utf-8') as f:
                json.dump(final_data, f, indent=4, ensure_ascii=False)
            os.replace(temp_file, DATA_FILE)
            print(f"\n[Done] Saved {len(final_data)} matches to {DATA_FILE}")
        else:
            print("\n[Done] No streams captured")
        print(f"\n[Time] Total: {time.time() - _t0:.2f}s")
    except KeyboardInterrupt:
        print("\n[!] User Interrupted")
        subprocess.run(["pkill", "-9", "-f", "ms-playwright"], stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    main()

