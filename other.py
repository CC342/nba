from flask import Flask, Response, request
import requests
import urllib.parse

app = Flask(__name__)

# ================= 配置 =================
# 隐藏的上游域名 (虽然是直连，但入口需要这个)
HIDDEN_UPSTREAM = "https://gg.poocloud.in"

# 伪装头
HEADERS = {
    "Referer": "https://embedsports.top/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0 Safari/537.36"
}
# =======================================

@app.route('/<path:subpath>')
def direct_proxy(subpath):
    # 1. 动态拼接入口地址
    real_url = f"{HIDDEN_UPSTREAM}/{subpath}"

    # 2. 保留你的特定业务逻辑 (替换 index 为 mono)
    if "index.m3u8" in subpath:
        real_url = real_url.replace("index.m3u8", "tracks-v1a1/mono.ts.m3u8")

    # 3. 携带 URL 参数 (Token 等)
    if request.query_string:
        real_url += f"?{request.query_string.decode('utf-8')}"

    print(f"[Direct Mode] Fetching M3U8: {real_url}")

    try:
        # 4. 请求 m3u8
        r = requests.get(real_url, headers=HEADERS, timeout=5, verify="/etc/ssl/certs/ca-certificates.crt")

        # 5. 解析并重写
        # 核心逻辑：不通过剥离字符串，而是利用 urljoin 智能计算绝对路径
        if "application/vnd.apple.mpegurl" in r.headers.get("Content-Type", "") or subpath.endswith(".m3u8"):
            base_url = real_url #以此为基准
            content = r.text
            new_lines = []

            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    new_lines.append(line)
                    continue
                
                # 【关键】无论地址怎么变，这里都计算出它的绝对直连地址
                # 如果 line 是 "http://other.com/1.ts"，urljoin 会直接保留它
                # 如果 line 是 "1.ts"，urljoin 会拼成 "https://gg.poocloud.in/.../1.ts"
                absolute_url = urllib.parse.urljoin(base_url, line)
                new_lines.append(absolute_url)

            return Response("\n".join(new_lines), status=r.status_code, mimetype="application/vnd.apple.mpegurl")

        # 理论上直连模式不应该收到 TS 请求，但以防万一
        return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type"))

    except Exception as e:
        return f"Error: {e}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9000, threaded=True)
