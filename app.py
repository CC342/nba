from flask import Flask, Response, request, render_template
import requests
import urllib.parse
import urllib3

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# ================= 配置 =================
HIDDEN_UPSTREAM = "https://gg.poocloud.in"

# 🏀 30支球队完整列表 (含官方 Logo)
PLAYLIST = [
    {"name": "Atlanta Hawks (老鹰)", "url": "/atlantahawks/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/atl.png"},
    {"name": "Boston Celtics (凯尔特人)", "url": "/bostonceltics/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/bos.png"},
    {"name": "Brooklyn Nets (篮网)", "url": "/brooklynnets/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/bkn.png"},
    {"name": "Charlotte Hornets (黄蜂)", "url": "/charlottehornets/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/cha.png"},
    {"name": "Chicago Bulls (公牛)", "url": "/chicagobulls/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/chi.png"},
    {"name": "Cleveland Cavaliers (骑士)", "url": "/clevelandcavaliers/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/cle.png"},
    {"name": "Dallas Mavericks (独行侠)", "url": "/dallasmavericks/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/dal.png"},
    {"name": "Denver Nuggets (掘金)", "url": "/denvernuggets/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/den.png"},
    {"name": "Detroit Pistons (活塞)", "url": "/detroitpistons/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/det.png"},
    {"name": "Golden State Warriors (勇士)", "url": "/goldenstatewarriors/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/gs.png"},
    {"name": "Houston Rockets (火箭)", "url": "/houstonrockets/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/hou.png"},
    {"name": "Indiana Pacers (步行者)", "url": "/indianapacers/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/ind.png"},
    {"name": "LA Clippers (快船)", "url": "/laclippers/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/lac.png"},
    {"name": "Los Angeles Lakers (湖人)", "url": "/lakers/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/lal.png"},
    {"name": "Memphis Grizzlies (灰熊)", "url": "/memphisgrizzlies/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/mem.png"},
    {"name": "Miami Heat (热火)", "url": "/miamineheat/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/mia.png"},
    {"name": "Milwaukee Bucks (雄鹿)", "url": "/milwaukeebucks/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/mil.png"},
    {"name": "Minnesota Timberwolves (森林狼)", "url": "/minnesotatimberwolves/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/min.png"},
    {"name": "New Orleans Pelicans (鹈鹕)", "url": "/neworleanspelicans/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/no.png"},
    {"name": "New York Knicks (尼克斯)", "url": "/newyorkknicks/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/ny.png"},
    {"name": "Oklahoma City Thunder (雷霆)", "url": "/oklahomacitythunder/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/okc.png"},
    {"name": "Orlando Magic (魔术)", "url": "/orlandomagic/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/orl.png"},
    {"name": "Philadelphia 76ers (76人)", "url": "/philadelphia76ers/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/phi.png"},
    {"name": "Phoenix Suns (太阳)", "url": "/phoenixsuns/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/phx.png"},
    {"name": "Portland Trail Blazers (开拓者)", "url": "/portlandtrailblazers/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/por.png"},
    {"name": "Sacramento Kings (国王)", "url": "/sacramentokings/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/sac.png"},
    {"name": "San Antonio Spurs (马刺)", "url": "/sanantoniospurs/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/sas.png"},
    {"name": "Toronto Raptors (猛龙)", "url": "/torontoraptors/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/tor.png"},
    {"name": "Utah Jazz (爵士)", "url": "/utahjazz/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/utah.png"},
    {"name": "Washington Wizards (奇才)", "url": "/washingtonwizards/index.m3u8", "logo": "https://a.espncdn.com/i/teamlogos/nba/500/was.png"}
]

HEADERS = {
    "Referer": "https://embedsports.top/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0 Safari/537.36"
}
# =======================================

@app.route('/')
def home():
    return render_template('index.html', channels=PLAYLIST)

@app.route('/<path:subpath>')
def direct_proxy(subpath):
    real_url = f"{HIDDEN_UPSTREAM}/{subpath}"

    if "index.m3u8" in subpath:
        real_url = real_url.replace("index.m3u8", "tracks-v1a1/mono.ts.m3u8")

    if request.query_string:
        real_url += f"?{request.query_string.decode('utf-8')}"

    print(f"[HFS Mode] Processing: {real_url}")

    try:
        # verify=False 防止容器内找不到证书报错
        r = requests.get(real_url, headers=HEADERS, timeout=10, verify=False)

        if "application/vnd.apple.mpegurl" in r.headers.get("Content-Type", "") or subpath.endswith(".m3u8"):
            base_url = real_url
            content = r.text
            new_lines = []

            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    new_lines.append(line)
                    continue
                
                # 关键：将相对路径转为绝对路径，实现直连
                absolute_url = urllib.parse.urljoin(base_url, line)
                new_lines.append(absolute_url)

            return Response("\n".join(new_lines), status=r.status_code, mimetype="application/vnd.apple.mpegurl")

        return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type"))

    except Exception as e:
        return f"Proxy Error: {e}", 500

if __name__ == '__main__':
    # 【重要】Hugging Face 强制要求监听 7860 端口
    app.run(host='0.0.0.0', port=7860)
