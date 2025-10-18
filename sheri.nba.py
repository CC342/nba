#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import re

BASE_URL = "https://www.nbabite.is/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
WAIT_TIMEOUT = 10000  # ms
WAIT_AFTER_LOAD_MS = 10000  # 等待页面JS生成m3u8

# ANSI 颜色
RED = "\033[1;91m"      # 已结束
GREEN = "\033[1;92m"    # 进行中 / m3u8 高亮
YELLOW = "\033[1;93m"   # 未开始
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
    
    # 定义匹配模式和对应格式化函数
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

    # 清理时间信息，剔除含“from now”的时间表达
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

    # 提取队伍名称（用原始文本提高准确率）
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

def fetch_stream_links(match_url, target_name="sheri"):
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

# ===== 并行获取 m3u8（保持顺序） =====
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

def fetch_m3u8(urls):
    if isinstance(urls, str):
        urls = [urls]
    if not urls:  # ✅ 没有URL时直接返回空列表                                           
        return []
    results = [None] * len(urls)
    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as executor:
        futures = [executor.submit(fetch_m3u8_single, url) for url in urls]
        for idx, future in enumerate(futures):
            results[idx] = future.result()
    return results

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

    # === Match Started ===
    print(f"{GREEN}Match Started 比赛数: {len(match_started)}{RESET}")
    push_msg += f"Match Started 比赛数: {len(match_started)}\n"

    # 收集所有比赛第一个 stream 链接
    match_stream_map = {}
    for i, m in enumerate(match_started, 1):
        team1, team2 = parse_match_name(m['raw_name'])
        stream_links = fetch_stream_links(m['url'], target_name="sheri")
        if stream_links:
            match_stream_map[i] = {"teams": f"{team1} — {team2}", "url": stream_links[0]}
        else:
            print(f"{i}. {team1} — {team2}   {RED}未找到 sheri 地址{RESET}")

    # 并行获取 m3u8（顺序保持和比赛一致）
    urls_to_fetch = [info["url"] for info in match_stream_map.values()]
    all_m3u8_lists = fetch_m3u8(urls_to_fetch)

    # 输出和匹配每场比赛
    for idx, (i, info) in enumerate(match_stream_map.items(), 1):
        teams = info["teams"]
        m3u8s = all_m3u8_lists[idx-1] if idx-1 < len(all_m3u8_lists) else []
        if not m3u8s:
            print(f"{i}. {teams}   {RED}未找到 m3u8 地址{RESET}")
            continue
        print(f"{i}. {teams}")
        for url in m3u8s:
            print(f"   {GREEN}{url}{RESET}")
            push_msg += f"{i}. {teams}\n{url}\n"

    print("\n")
    push_msg += "\n"

    # === Final ===
    print(f"{RED}Final 比赛数: {len(final_matches)}{RESET}")
    push_msg += f"Final 比赛数: {len(final_matches)}\n"
    for i, m in enumerate(final_matches, 1):
        print(f"{i}. {m['name']}")
        push_msg += f"{i}. {m['name']}\n"

    print("\n")
    push_msg += "\n"

    # === From Now ===
    print(f"{YELLOW}From Now 比赛数: {len(from_now_matches)}{RESET}")
    push_msg += f"From Now 比赛数: {len(from_now_matches)}\n"
    for i, m in enumerate(from_now_matches, 1):
        print(f"{i}. {m['name']}")
        push_msg += f"{i}. {m['name']}\n"

    # 推送
    if push_msg:
        send_telegram(push_msg)
        send_wechat(push_msg)

if __name__ == "__main__":
    main()
