import json
import os
import re
import subprocess
import threading
import time
from urllib.parse import quote, urljoin
from flask import Flask, request, redirect, Response, render_template_string
from curl_cffi import requests

app = Flask(__name__)

# ================= 配置 =================
JSON_FILE = 'game.json'
SCRAPER_SCRIPT = 'start.py'
scrape_lock = threading.Lock()

# ================= 球队列表 (UI用) =================
PLAYLIST = [
    {"name": "Atlanta Hawks (老鹰)", "key": "atlantahawks", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/atl.png"},
    {"name": "Boston Celtics (凯尔特人)", "key": "bostonceltics", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/bos.png"},
    {"name": "Brooklyn Nets (篮网)", "key": "brooklynnets", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/bkn.png"},
    {"name": "Charlotte Hornets (黄蜂)", "key": "charlottehornets", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/cha.png"},
    {"name": "Chicago Bulls (公牛)", "key": "chicagobulls", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/chi.png"},
    {"name": "Cleveland Cavaliers (骑士)", "key": "clevelandcavaliers", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/cle.png"},
    {"name": "Dallas Mavericks (独行侠)", "key": "dallasmavericks", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/dal.png"},
    {"name": "Denver Nuggets (掘金)", "key": "denvernuggets", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/den.png"},
    {"name": "Detroit Pistons (活塞)", "key": "detroitpistons", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/det.png"},
    {"name": "Golden State Warriors (勇士)", "key": "goldenstatewarriors", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/gs.png"},
    {"name": "Houston Rockets (火箭)", "key": "houstonrockets", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/hou.png"},
    {"name": "Indiana Pacers (步行者)", "key": "indianapacers", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/ind.png"},
    {"name": "LA Clippers (快船)", "key": "laclippers", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/lac.png"},
    {"name": "Los Angeles Lakers (湖人)", "key": "losangeleslakers", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/lal.png"},
    {"name": "Memphis Grizzlies (灰熊)", "key": "memphisgrizzlies", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/mem.png"},
    {"name": "Miami Heat (热火)", "key": "miamiheat", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/mia.png"},
    {"name": "Milwaukee Bucks (雄鹿)", "key": "milwaukeebucks", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/mil.png"},
    {"name": "Minnesota Timberwolves (森林狼)", "key": "minnesotatimberwolves", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/min.png"},
    {"name": "New Orleans Pelicans (鹈鹕)", "key": "neworleanspelicans", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/no.png"},
    {"name": "New York Knicks (尼克斯)", "key": "newyorkknicks", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/ny.png"},
    {"name": "Oklahoma City Thunder (雷霆)", "key": "oklahomacitythunder", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/okc.png"},
    {"name": "Orlando Magic (魔术)", "key": "orlandomagic", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/orl.png"},
    {"name": "Philadelphia 76ers (76人)", "key": "philadelphia76ers", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/phi.png"},
    {"name": "Phoenix Suns (太阳)", "key": "phoenixsuns", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/phx.png"},
    {"name": "Portland Trail Blazers (开拓者)", "key": "portlandtrailblazers", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/por.png"},
    {"name": "Sacramento Kings (国王)", "key": "sacramentokings", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/sac.png"},
    {"name": "San Antonio Spurs (马刺)", "key": "sanantoniospurs", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/sas.png"},
    {"name": "Toronto Raptors (猛龙)", "key": "torontoraptors", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/tor.png"},
    {"name": "Utah Jazz (爵士)", "key": "utahjazz", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/utah.png"},
    {"name": "Washington Wizards (奇才)", "key": "washingtonwizards", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/was.png"}
]

# ================= 辅助函数 =================
def load_game_data():
    if not os.path.exists(JSON_FILE): return {}
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except: return {}

# ================= 核心逻辑：抓取并重写 M3U8（照主机 wx v3.3） =================
def fetch_and_rewrite_m3u8(target_url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://embed.st/",
        "Origin": "https://embed.st"
    }
    try:
        r = requests.get(target_url, headers=headers, impersonate="chrome110", timeout=10)
        if r.status_code != 200:
            return Response(f"#EXTM3U\n#EXT-X-ERROR: Upstream {r.status_code}", status=502, mimetype="application/vnd.apple.mpegurl")
        content = r.text
        clean_lines = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("##"): continue
            if line == "#EXT-X-GAP":
                continue
            if line.startswith("#"):
                if line.startswith("#EXT-X-MAP:"):
                    m = re.search(r'URI="([^"]+)"', line)
                    if m and not m.group(1).startswith("data:"):
                        abs_uri = urljoin(target_url, m.group(1))
                        line = line[:m.start(1)] + abs_uri + line[m.end(1):]
                    clean_lines.append(line)
                elif line.startswith("#EXT-X-KEY:"):
                    m = re.search(r'URI="([^"]+)"', line)
                    if m:
                        uri = m.group(1)
                        if uri.startswith("data:") or uri.startswith("http"):
                            pass
                        else:
                            abs_uri = urljoin(target_url, uri)
                            line = line[:m.start(1)] + f"/proxy?url={quote(abs_uri)}" + line[m.end(1):]
                    clean_lines.append(line)
                elif 'URI="' in line:
                    m = re.search(r'URI="([^"]+)"', line)
                    if m:
                        uri = m.group(1)
                        if uri.startswith("data:") or uri.startswith("http"):
                            pass
                        else:
                            abs_uri = urljoin(target_url, uri)
                            if ".m3u8" in abs_uri or "playlist" in abs_uri:
                                new_uri = f"/proxy?url={quote(abs_uri)}"
                            else:
                                new_uri = abs_uri
                            line = line[:m.start(1)] + new_uri + line[m.end(1):]
                    clean_lines.append(line)
                else:
                    clean_lines.append(line)
            else:
                abs_url = urljoin(target_url, line)
                if ".m3u8" in abs_url or "playlist" in abs_url:
                    if "?" not in abs_url and "?" in target_url:
                        abs_url = abs_url + "?" + target_url.split("?", 1)[1]
                    clean_lines.append(f"/proxy?url={quote(abs_url)}")
                else:
                    clean_lines.append(abs_url)
        resp = Response("\n".join(clean_lines), mimetype="application/vnd.apple.mpegurl")
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except Exception as e:
        return Response(f"#EXTM3U\n#EXT-X-ERROR: {str(e)}", status=500, mimetype="application/vnd.apple.mpegurl")

# ================= ClearKey 自动取用（照主机 wx v3.3，Docker 版只读本容器 game.json） =================
_CLEAKEY_CACHE = {}
_CLEAKEY_TTL = 600
_CLEAKEY_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36"

def fetch_clearkey_for_team(team_key):
    """返回 (result, step, detail)。result 为 {keyId, key} 或 None。"""
    import urllib.request
    now = time.time()
    cached = _CLEAKEY_CACHE.get(team_key)
    if cached and now - cached[0] < _CLEAKEY_TTL:
        return cached[1], "cache", "cached"
    data = load_game_data()
    info = data.get(team_key)
    if not info:
        return None, "no_team", "game.json 里没有 " + team_key
    referer = info.get('referer')
    if not referer:
        return None, "no_referer", "game.json 里没有 referer"
    def get(url, ref=None):
        import gzip as _gzip
        req = urllib.request.Request(url, headers={"User-Agent": _CLEAKEY_UA, "Accept-Encoding": "identity", **({"Referer": ref} if ref else {})})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            if raw[:2] == b'\x1f\x8b':
                raw = _gzip.decompress(raw)
            return resp.status, raw.decode('utf-8', errors='ignore')
    try:
        status, ev = get(referer)
        if status != 200:
            return None, "foxiy", "foxiy 事件页 HTTP %d" % status
        cands = re.findall(r'data-e="([^"]+)"', ev)
        tops = [c for c in cands if "/top/" in c]
        if not tops:
            return None, "no_top", "事件页候选 %d 个，无 /top/" % len(cands)
        last_detail = ""
        for top in tops:
            try:
                status2, page = get(top, ref=referer)
            except Exception as e:
                last_detail = "trendy48 异常 %s" % str(e)[:100]; continue
            if status2 != 200:
                last_detail = "trendy48 HTTP %d len %d" % (status2, len(page)); continue
            iframe = None
            for m in re.finditer(r'<iframe[^>]*src="([^"]+)"', page):
                if "topstreamer" in m.group(1):
                    iframe = m.group(1); break
            if not iframe:
                last_detail = "trendy48 200 len %d 但无 topstreamer iframe" % len(page); continue
            got = False
            for _attempt in range(3):
                try:
                    status3, page = get(iframe, ref=top)
                except Exception:
                    continue
                if status3 == 200 and re.search(r'masterinf\s*=\s*(\{[^}]+\})', page):
                    got = True; break
                time.sleep(1)
            if not got:
                last_detail = "topstreamer 200 但 3 次均无 masterinf，末次 len %d" % len(page); continue
            m = re.search(r'masterinf\s*=\s*(\{[^}]+\})', page)
            if not m:
                continue
            pairs = re.findall(r'"?([0-9a-f-]{32,})"?\s*:\s*"?([0-9a-f]{32,})"?', m.group(1))
            if not pairs:
                continue
            result = {"keyId": pairs[0][0], "key": pairs[0][1]}
            _CLEAKEY_CACHE[team_key] = (now, result)
            return result, "ok", "ok"
        return None, "no_masterinf", last_detail or ("已试 /top/ 候选 %d 个" % len(tops))
    except Exception as e:
        return None, "exception", str(e)[:200]

# ================= HTML 模板 =================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HF NBA Live</title>
    <style>
        body {
            background-image: url('https://images.unsplash.com/photo-1567158186373-2cdd94855eac?q=80&w=1920&auto=format&fit=crop');
            background-size: cover; background-position: center; background-repeat: no-repeat; background-attachment: fixed;
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
            display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0;
            box-shadow: inset 0 0 0 2000px rgba(0, 0, 0, 0.4);
        }
        .container {
            text-align: center; padding: 2.5rem; width: 85%; max-width: 450px;
            background-color: rgba(20, 20, 20, 0.2); backdrop-filter: blur(10px) saturate(150%); -webkit-backdrop-filter: blur(10px) saturate(150%);
            border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 30px; box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
            transition: all 0.3s ease;
        }
        .team-logo {
            width: 100px; height: 100px; object-fit: contain; margin-bottom: 10px;
            filter: drop-shadow(0 4px 6px rgba(0,0,0,0.3)); transition: transform 0.3s;
        }
        h1 { color: #fff; margin: 10px 0 5px 0; font-weight: 700; font-size: 1.5rem; text-shadow: 0 2px 4px rgba(0,0,0,0.5); }
        p { color: rgba(255, 255, 255, 0.6); margin-bottom: 25px; font-size: 0.9rem; }
        select, input, .btn-play, .btn-update {
            width: 100%; padding: 16px; border-radius: 14px; margin-bottom: 15px;
            font-size: 16px; outline: none; border: 1px solid rgba(255, 255, 255, 0.1);
        }
        select { background-color: rgba(0, 0, 0, 0.4); color: white; cursor: pointer; text-align: center; }
        input { background: rgba(0, 0, 0, 0.25); color: rgba(255, 255, 255, 0.8); box-sizing: border-box; }
        .btn-play { background: #007AFF; color: white; border: none; font-weight: 600; cursor: pointer; transition: 0.2s; box-shadow: 0 4px 12px rgba(0, 122, 255, 0.3); }
        .btn-play:hover { background: #0062cc; transform: scale(0.98); }
        .btn-update { background: transparent; border: 1px solid rgba(255,255,255,0.3); color: rgba(255,255,255,0.8); padding: 12px; font-size: 14px; cursor: pointer; }
        .btn-update:hover { background: rgba(255,255,255,0.1); }
        .btn-update:disabled { color: rgba(255,255,255,0.3); cursor: not-allowed; }
        .tips { margin-top: 20px; font-size: 0.8rem; color: rgba(255, 255, 255, 0.4); }
        .select-wrapper { position: relative; width: 100%; }
        .select-wrapper::after {
            content: '▼'; font-size: 12px; color: rgba(255, 255, 255, 0.5); position: absolute; right: 20px; top: 50%; transform: translateY(-50%); pointer-events: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <img id="teamLogo" src="https://cdn.nba.com/headshots/nba/latest/1040x760/logoman.png" class="team-logo" alt="Team Logo">
        <h1>NBA Live</h1>
        <p id="statusText">Select a team to start streaming</p>
        <button id="updateBtn" class="btn-update" onclick="triggerUpdate()">🔄 更新今日比赛源 (Run Scraper)</button>
        <br><br>
        <div class="select-wrapper">
            <select id="channelSelect" onchange="updateUI()">
                <option value="" disabled selected data-logo="https://cdn.nba.com/headshots/nba/latest/1040x760/logoman.png">✨ 选择球队 / Select Team</option>
                {% for channel in channels %}
                <option value="{{ channel.key }}" data-logo="{{ channel.logo }}">
                    {{ channel.name }} {% if channel.key in live_keys %} [🟢LIVE] {% endif %}
                </option>
                {% endfor %}
            </select>
        </div>
        <input type="text" id="pathInput" placeholder="URL will appear here..." readonly>
        <button class="btn-play" onclick="play()">▶ Open Stream</button>
        <div class="tips">点击 Open Stream 即打开自动播放页<br>播放器会自动取本场 ClearKey，满屏 1080p</div>
    </div>
    <script>
        function updateUI() {
            var select = document.getElementById("channelSelect");
            var input = document.getElementById("pathInput");
            var logo = document.getElementById("teamLogo");
            input.value = "/" + select.value + "/play";
            var selectedOption = select.options[select.selectedIndex];
            var logoUrl = selectedOption.getAttribute('data-logo');
            if (logoUrl) {
                logo.style.transform = "scale(0.8)";
                setTimeout(() => { logo.src = logoUrl; logo.style.transform = "scale(1)"; }, 150);
            }
        }
        function play() {
            let path = document.getElementById('pathInput').value;
            if (!path || path.includes('URL will appear')) return alert("请先选择球队");
            window.location.href = path;
        }
        function triggerUpdate() {
            const btn = document.getElementById('updateBtn');
            const status = document.getElementById('statusText');
            btn.disabled = true;
            btn.innerText = '正在后台抓取... (约60秒)';
            status.innerText = '正在运行，请勿关闭页面...';
            fetch('/trigger_update')
                .then(res => res.text())
                .then(data => {
                    status.innerText = '更新完成！正在刷新列表...';
                    setTimeout(() => location.reload(), 1000);
                })
                .catch(err => {
                    btn.disabled = false;
                    btn.innerText = '更新失败 (点击重试)';
                    status.innerText = '错误: ' + err;
                });
        }
    </script>
</body>
</html>
"""

# ================= 路由逻辑 =================

@app.route('/')
def home():
    live_data = load_game_data()
    live_keys = list(live_data.keys())
    return render_template_string(HTML_TEMPLATE, channels=PLAYLIST, live_keys=live_keys)

@app.route('/player.html')
def player_page():
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'player.html'),
        '/main/player.html',
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                resp = Response(f.read(), mimetype='text/html')
                resp.headers["Access-Control-Allow-Origin"] = "*"
                return resp
    return "player.html not found: docker cp player.html to /main/player.html", 404

@app.route('/<team_key>/clearkey')
def team_clearkey(team_key):
    result, step, detail = fetch_clearkey_for_team(team_key)
    if not result:
        return {"error": "no clearkey for " + team_key, "step": step, "detail": detail}, 404
    resp = Response(json.dumps(result), mimetype='application/json')
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

@app.route('/<team_key>/play')
def team_play(team_key):
    return redirect(f"/player.html?team={team_key}")

@app.route('/trigger_update')
def trigger_update():
    if scrape_lock.acquire(blocking=False):
        try:
            print(f">>> [Flask] 启动 {SCRAPER_SCRIPT} ...")
            subprocess.run(["python3", SCRAPER_SCRIPT], check=True)
            return "OK"
        except Exception as e:
            return str(e), 500
        finally:
            scrape_lock.release()
    else:
        return "Running", 429

@app.route('/<team_key>/index.m3u8')
def team_stream(team_key):
    data = load_game_data()
    if team_key not in data:
        return f"#EXTM3U\n#EXT-X-ERROR: No signal found for {team_key}. Please update.", 404
    info = data[team_key]
    real_url = info.get('full_url')
    if not real_url:
        return f"#EXTM3U\n#EXT-X-ERROR: URL missing for {team_key}", 500
    return fetch_and_rewrite_m3u8(real_url)

@app.route('/proxy')
def proxy():
    target_url = request.args.get('url')
    if not target_url: return "Missing URL", 400
    return fetch_and_rewrite_m3u8(target_url)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7860)

