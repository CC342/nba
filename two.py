#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import re
from concurrent.futures import ThreadPoolExecutor
import time

BASE_URL = "https://www.nbabite.is/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
WAIT_AFTER_LOAD_MS = 1000  # 页面加载后等待JS生成m3u8链接时间（毫秒）

# 代理配置，用于Sportsbest m3u8代理访问
PROXY_HOST = "https://nba.imeet.eu.org"
PROXY_PREFIX = f"{PROXY_HOST}/proxy?url="

# 彩色终端输出
RED = "\033[1;91m"
GREEN = "\033[1;92m"
YELLOW = "\033[1;93m"
RESET = "\033[0m"

# Telegram/企业微信配置，请替换成您自己的token和id
TELEGRAM_BOT_TOKEN = "1864911909:AAE4vhlfdFn7aHX57TZioe6BImeDstCWYLA"
TELEGRAM_CHAT_ID = "856601829"
WX_CORP_ID = "wwee932559bcea72cc"
WX_AGENT_ID = "1000003"
WX_SECRET = "SgMMexlVwa9HRov7FMNORY6Kv3dKoDFVkEQE1hYpDls"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.get(url, params={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

def send_wechat(msg):
    token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WX_CORP_ID}&corpsecret={WX_SECRET}"
    r = requests.get(token_url).json()
    access_token = r.get("access_token")
    if not access_token:
        print(f"{RED}企业微信获取access_token失败{RESET}")
        return
    send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
    data = {
        "touser": "@all",
        "msgtype": "text",
        "agentid": int(WX_AGENT_ID),
        "text": {"content": msg},
        "safe": 0
    }
    requests.post(send_url, json=data)

def format_final_name(raw_text):
    clean_text = raw_text.lower().replace("final", "").replace("watch highlights", "").strip()
    pattern = re.compile(r"([a-z\s]+)(\d+)([a-z\s]+)(\d+)", re.I)
    m = pattern.search(clean_text)
    if m:
        team1 = m.group(1).strip().title()
        score1 = m.group(2)
        team2 = m.group(3).strip().title()
        score2 = m.group(4)
        return f"{team1} {score1} — {score2} {team2}"
    return clean_text.title()

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
            break
    time_patterns = [
        r'\d+\s*hours?\s*and\s*\d+\s*minutes?\s*from now',
        r'\d+\s*hours?\s*from now',
        r'\d+\s*minutes?\s*from now',
        r'\d+\s*day[s]? from now'
    ]
    teams_text = raw_text
    for pat in time_patterns:
        teams_text = re.sub(pat, '', teams_text, flags=re.I)
    teams_text = teams_text.strip()
    teams = re.findall(r'(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s(?:[A-Z][a-z]+|[A-Z]{2,}))*', raw_text)
    if len(teams) >= 2:
        return f"{time_str}  {teams[0]} 🆚 {teams[1]}"
    return f"{time_str}  {teams_text}"

def fetch_home_matches():
    try:
        resp = requests.get(BASE_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"{RED}请求主页失败: {e}{RESET}")
        return [], [], []

    soup = BeautifulSoup(resp.text, "html.parser")
    match_started, final_matches, from_now_matches = [], [], []

    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        low = text.lower()
        href = a['href']
        if href.startswith("/"):
            href = BASE_URL.rstrip("/") + href

        if "match started" in low:
            match_started.append({"raw_name": text, "url": href})
        elif "final" in low:
            final_matches.append({"raw_name": text, "name": format_final_name(text), "url": href})
        elif "from now" in low:
            from_now_matches.append({"raw_name": text, "name": format_from_now_name(text), "url": href})

    return match_started, final_matches, from_now_matches

def fetch_stream_links_sheri(match_url, target_name="sheri"):
    resp = requests.get(match_url, headers=HEADERS)
    soup = BeautifulSoup(resp.text, "html.parser")
    links = []
    seen = set()
    for td in soup.find_all("td", class_="display-bg"):
        text = td.get_text(strip=True).lower()
        if target_name.lower() in text:
            onclick_val = td.get("onclick", "")
            m = re.search(r'view\((\d+)\)', onclick_val)
            if m:
                view_id = m.group(1)
                input_tag = soup.find("input", id=f"linkk{view_id}")
                if input_tag:
                    url = input_tag['value']
                    if url not in seen:
                        links.append(url)
                        seen.add(url)
    return links

def fetch_sportsbest_url(match_url):
    # 获取Sportsbest直播页地址（先通过页面解析获取Sportsbest对应直播链接）
    resp = requests.get(match_url, headers=HEADERS)
    soup = BeautifulSoup(resp.text, "html.parser")
    for td in soup.find_all("td", class_="display-bg"):
        text = td.get_text(strip=True)
        if text == "Sportsbest":  # 精确匹配
            onclick_val = td.get("onclick", "")
            m = re.search(r'view\((\d+)\)', onclick_val)
            if m:
                view_id = m.group(1)
                input_tag = soup.find("input", id=f"linkk{view_id}")
                if input_tag and input_tag.get("value"):
                    return input_tag['value']
    return None

def fetch_m3u8_single(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, timeout=30000)
        page.wait_for_timeout(WAIT_AFTER_LOAD_MS)
        content = page.content()
        browser.close()
        m3u8_list = re.findall(r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*', content)
        m3u8_list = [u for u in set(m3u8_list) if "?md5=" in u or "?expires=" in u]
        return m3u8_list

def fetch_sportsbest_m3u8_with_proxy(url):
    # 用playwright模拟访问，抓取embedsports.top等网站请求的m3u8链接，再代理
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36")
        page = context.new_page()
        page.set_extra_http_headers({"Referer": url})
        m3u8_urls = set()
        found_first = False

        def capture_m3u8(req_or_resp):
            url_cand = getattr(req_or_resp, 'url', None)
            if url_cand and ".m3u8" in url_cand and "embedsports.top" in url_cand:
                m3u8_urls.add(url_cand)
                return True
            return False

        page.on("request", lambda r: capture_m3u8(r))
        page.on("response", lambda r: capture_m3u8(r))

        try:
            page.goto(url, wait_until="load", timeout=15000)
        except TimeoutError:
            pass

        start_ts = time.time()
        MAX_WAIT = 3.5
        POLL_INTERVAL = 0.1
        while (time.time() - start_ts) < MAX_WAIT and not found_first:
            for f in page.frames:
                if "embedsports.top" in f.url:
                    try:
                        content = f.content()
                        for found in re.findall(r"https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*", content):
                            if found not in m3u8_urls:
                                m3u8_urls.add(found)
                                found_first = True
                                break
                    except Exception:
                        pass
                if found_first:
                    break
            if not found_first:
                content = page.content()
                for found in re.findall(r"https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*", content):
                    if found not in m3u8_urls:
                        m3u8_urls.add(found)
                        found_first = True
                        break
            if found_first:
                break
            time.sleep(POLL_INTERVAL)

        try:
            context.close()
            browser.close()
        except Exception:
            pass

        # 返回代理过的m3u8链接
        return [PROXY_PREFIX + url for url in m3u8_urls]

def parse_match_name(raw_name):
    name = raw_name.replace("Match Started", "").strip()
    words = re.findall(r'[A-Z][a-z]*(?:\s[A-Z][a-z]*)*', name)
    if len(words) >= 2:
        mid = len(words) // 2
        team1 = ' '.join(words[:mid])
        team2 = ' '.join(words[mid:])
        return team1, team2
    return name, ""

def main():
    match_started, final_matches, from_now_matches = fetch_home_matches()

    push_msg = ""

    # 进行中比赛数
    print(f"{GREEN}Match Started 比赛数: {len(match_started)}{RESET}")
    push_msg += f"Match Started 比赛数: {len(match_started)}\n"

    match_stream_map = {}
    # 遍历所有进行中比赛
    for i, m in enumerate(match_started, 1):
        team1, team2 = parse_match_name(m['raw_name'])

        # 获取Sheri直播源m3u8
        sheri_links = fetch_stream_links_sheri(m['url'], target_name="sheri")
        sheri_m3u8 = []
        if sheri_links:
            with ThreadPoolExecutor(max_workers=min(4, len(sheri_links))) as executor:
                futures = [executor.submit(fetch_m3u8_single, link) for link in sheri_links]
                for future in futures:
                    sheri_m3u8.extend(future.result())

        # 获取Sportsbest直播源地址
        sportsbest_url = fetch_sportsbest_url(m['url'])
        sportsbest_m3u8 = []
        if sportsbest_url:
            sportsbest_m3u8 = fetch_sportsbest_m3u8_with_proxy(sportsbest_url)

        match_stream_map[i] = {
            "teams": f"{team1} — {team2}",
            "sheri_m3u8": sheri_m3u8,
            "sportsbest_m3u8": sportsbest_m3u8,
        }

    # 输出结果与消息拼接
    for i, info in match_stream_map.items():
        print(f"{i}. {info['teams']}")
        push_msg += f"{i}. {info['teams']}\n"
        if info["sheri_m3u8"]:
            for url in info["sheri_m3u8"]:
                print(f"  Sheri: {GREEN}{url}{RESET}")
                push_msg += f"  Sheri: {url}\n"
        else:
            print(f"  Sheri: {RED}未找到m3u8地址{RESET}")
            push_msg += "  Sheri: 未找到m3u8地址\n"

        if info["sportsbest_m3u8"]:
            for url in info["sportsbest_m3u8"]:
                print(f"  Sportsbest: {GREEN}{url}{RESET}")
                push_msg += f"  Sportsbest: {url}\n"
        else:
            print(f"  Sportsbest: {RED}未找到m3u8地址{RESET}")
            push_msg += "  Sportsbest: 未找到m3u8地址\n"

    print("\n")
    push_msg += "\n"

    # 结束场次
    print(f"{RED}Final 比赛数: {len(final_matches)}{RESET}")
    push_msg += f"Final 比赛数: {len(final_matches)}\n"
    for i, m in enumerate(final_matches, 1):
        print(f"{i}. {m['name']}")
        push_msg += f"{i}. {m['name']}\n"

    print("\n")
    push_msg += "\n"

    # 未开始（from now）
    print(f"{YELLOW}From Now 比赛数: {len(from_now_matches)}{RESET}")
    push_msg += f"From Now 比赛数: {len(from_now_matches)}\n"
    for i, m in enumerate(from_now_matches, 1):
        print(f"{i}. {m['name']}")
        push_msg += f"{i}. {m['name']}\n"

    # 发送推送
    if push_msg:
        send_telegram(push_msg)
        send_wechat(push_msg)

if __name__ == "__main__":
    main()
