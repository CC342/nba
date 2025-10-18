#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError
import re
from concurrent.futures import ThreadPoolExecutor
import time

BASE_URL = "https://www.nbabite.is/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 代理配置，给Sportsbest的m3u8地址添加代理前缀
PROXY_HOST = "代理地址"
PROXY_PREFIX = f"{PROXY_HOST}/proxy?url="

# 终端颜色输出
RED = "\033[1;91m"
GREEN = "\033[1;92m"
YELLOW = "\033[1;93m"
RESET = "\033[0m"

# TG / 企业微信配置
TELEGRAM_BOT_TOKEN = "你的token"
TELEGRAM_CHAT_ID = "聊天id"
WX_CORP_ID = "企业微信id"
WX_AGENT_ID = "应用id"
WX_SECRET = "密钥"

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
    clean_text = raw_text.replace("Final", "").replace("Watch Highlights", "").strip()
    pattern = re.compile(r"([A-Za-z\s]*76ers[A-Za-z\s]*|[A-Za-z\s]+)\s*(\d+)\s*([A-Za-z\s]*76ers[A-Za-z\s]*|[A-Za-z\s]+)\s*(\d+)", re.I)
    m = pattern.search(clean_text)
    if m:
        team1 = m.group(1).strip()
        score1 = m.group(2)
        team2 = m.group(3).strip()
        score2 = m.group(4)
        return f"{team1} {score1} — {score2} {team2}"
    return clean_text

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

def fetch_sportsbest_url(match_url):
    # 获取Sportsbest直播页面URL
    resp = requests.get(match_url, headers=HEADERS)
    soup = BeautifulSoup(resp.text, "html.parser")
    for td in soup.find_all("td", class_="display-bg"):
        if td.get_text(strip=True) == "Sportsbest":
            onclick_val = td.get("onclick", "")
            m = re.search(r'view\((\d+)\)', onclick_val)
            if m:
                view_id = m.group(1)
                input_tag = soup.find("input", id=f"linkk{view_id}")
                if input_tag and input_tag.get("value"):
                    return input_tag['value']
    return None

def fetch_sportsbest_m3u8_with_proxy(url):
    # Playwright打开直播页面，抓取m3u8，返回带代理的m3u8链接列表
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36")
        page = context.new_page()
        page.set_extra_http_headers({"Referer": url})

        m3u8_urls = set()
        def capture_m3u8(req_or_resp):
            url_ = getattr(req_or_resp, 'url', None)
            if url_ and ".m3u8" in url_ and "embedsports.top" in url_:
                m3u8_urls.add(url_)
                return True
            return False

        page.on("request", lambda r: capture_m3u8(r))
        page.on("response", lambda r: capture_m3u8(r))

        try:
            page.goto(url, wait_until="load", timeout=10000)
        except TimeoutError:
            pass

        # 最多等待2秒寻找m3u8链接
        max_wait = 2
        poll_interval = 0.1
        start_time = time.time()
        found = False
        while (time.time() - start_time) < max_wait and not found:
            for f in page.frames:
                if "embedsports.top" in f.url:
                    try:
                        content = f.content()
                        for found_m3u8 in re.findall(r"https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*", content):
                            if found_m3u8 not in m3u8_urls:
                                m3u8_urls.add(found_m3u8)
                                found = True
                                break
                    except:
                        pass
                if found:
                    break
            if not found:
                content = page.content()
                for found_m3u8 in re.findall(r"https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*", content):
                    if found_m3u8 not in m3u8_urls:
                        m3u8_urls.add(found_m3u8)
                        found = True
                        break
            if found:
                break
            time.sleep(poll_interval)

        try:
            context.close()
            browser.close()
        except:
            pass

        return [PROXY_PREFIX + m for m in m3u8_urls]

def parse_match_name(raw_name):
    # 从比赛标题中解析双方队伍名称
    name = raw_name.replace("Match Started", "").strip()
    words = re.findall(r'[A-Z][a-z]*(?:\s[A-Z][a-z]*)*', name)
    if len(words) >= 2:
        mid = len(words) // 2
        return ' '.join(words[:mid]), ' '.join(words[mid:])
    return name, ""

def main():
    match_started, final_matches, from_now_matches = fetch_home_matches()

    push_msg = ""

    # 进行中比赛统计并打印
    print(f"{GREEN}Match Started 比赛数: {len(match_started)}{RESET}")
    push_msg += f"Match Started 比赛数: {len(match_started)}\n"

    def process_match(i, m):
        team1, team2 = parse_match_name(m['raw_name'])
        sportsbest_url = fetch_sportsbest_url(m['url'])
        sportsbest_m3u8 = []
    if sportsbest_url:
            sportsbest_m3u8 = fetch_sportsbest_m3u8_with_proxy(sportsbest_url)
        return i, team1, team2, sportsbest_m3u8

    results = []
    # 最大并发6个线程，提升速度
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(process_match, i, m) for i, m in enumerate(match_started, 1)]
        for future in futures:
            results.append(future.result())

    results.sort(key=lambda x: x[0])  # 保证输出顺序

    # 打印并拼接推送消息
    for i, team1, team2, m3u8s in results:
        print(f"{i}. {team1} — {team2}")
        push_msg += f"{i}. {team1} — {team2}\n"
        if m3u8s:
            for url in m3u8s:
                print(f"  {GREEN}{url}{RESET}")
                push_msg += f"  {url}\n"
        else:
            print(f"  {RED}未找到m3u8地址{RESET}")
            push_msg += "  未找到m3u8地址\n"
    
    push_msg += "\n"
    
    print(f"\n{RED}Final 比赛数: {len(final_matches)}{RESET}")
    push_msg += f"Final 比赛数: {len(final_matches)}\n"
    for i, m in enumerate(final_matches, 1):
        print(f"{i}. {m['name']}")
        push_msg += f"{i}. {m['name']}\n"

    push_msg += "\n"
    
    print(f"\n{YELLOW}From Now 比赛数: {len(from_now_matches)}{RESET}")
    push_msg += f"From Now 比赛数: {len(from_now_matches)}\n"
    for i, m in enumerate(from_now_matches, 1):
        print(f"{i}. {m['name']}")
        push_msg += f"{i}. {m['name']}\n"

    # 发送推送消息
    if push_msg:
        send_telegram(push_msg)
        send_wechat(push_msg)

if __name__ == "__main__":
    main()
