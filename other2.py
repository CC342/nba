from flask import Flask, Response, request, stream_with_context
import requests
import urllib.parse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

# ================= 配置 =================
HIDDEN_UPSTREAM = "https://gg.poocloud.in"
# 你的 Tunnel 域名 (必须填写，用于重写 URL)
MY_DOMAIN = "https://sports.imeet.eu.org" 

HEADERS = {
    "Referer": "https://embedsports.top/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0 Safari/537.36"
}

# 建立连接池，提高并发稳定性
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))
# =======================================

# --- 通用代理接口：负责搬运一切数据 (TS/Key/Image) ---
@app.route('/proxy')
def unified_proxy():
    target_url = request.args.get('url')
    if not target_url: return "Missing URL", 400
    
    target_url = urllib.parse.unquote(target_url)

    try:
        # 请求源文件
        r = session.get(target_url, headers=HEADERS, stream=True, timeout=10, verify="/etc/ssl/certs/ca-certificates.crt")
        
        # 强制修正 Header：不管源站说是图片(png)还是什么，统一告诉播放器这是视频流
        resp_headers = dict(r.headers)
        # 剔除导致错误的头
        for k in ['Content-Encoding', 'Content-Length', 'Transfer-Encoding', 'Connection']:
            resp_headers.pop(k, None)
        
        # 【关键】欺骗播放器，解决 -1015 和 格式不支持错误
        resp_headers['Content-Type'] = 'video/mp2t'
        resp_headers['Access-Control-Allow-Origin'] = '*'

        return Response(stream_with_context(r.iter_content(chunk_size=4096)), status=r.status_code, headers=resp_headers)
    except Exception as e:
        print(f"Proxy Fail: {e}")
        return str(e), 500

# --- 入口接口：处理 M3U8 列表 ---
@app.route('/<path:subpath>')
def manifest_handler(subpath):
    # 1. 构造初始地址
    real_url = f"{HIDDEN_UPSTREAM}/{subpath}"
    if "index.m3u8" in subpath:
        real_url = real_url.replace("index.m3u8", "tracks-v1a1/mono.ts.m3u8")
    if request.query_string:
        real_url += f"?{request.query_string.decode('utf-8')}"

    print(f"[Full Proxy] Manifest: {real_url}")

    try:
        r = session.get(real_url, headers=HEADERS, timeout=10, verify="/etc/ssl/certs/ca-certificates.crt")
        
        if "application/vnd.apple.mpegurl" in r.headers.get("Content-Type", "") or subpath.endswith(".m3u8"):
            base_url = real_url
            new_lines = []
            
            for line in r.text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    new_lines.append(line)
                    continue
                
                # 2. 计算绝对路径 (处理相对路径)
                abs_url = urllib.parse.urljoin(base_url, line)
                
                # 3. 【核心】全部打包发给 /proxy 接口
                # 无论这个 abs_url 是 fotor 还是 poocloud，全由你的服务器接管
                encoded_url = urllib.parse.quote(abs_url)
                # 生成链接: https://你的域名/proxy?url=xxxxx
                proxied_line = f"{MY_DOMAIN}/proxy?url={encoded_url}"
                new_lines.append(proxied_line)

            return Response("\n".join(new_lines), mimetype="application/vnd.apple.mpegurl", headers={"Access-Control-Allow-Origin": "*"})
        
        return "Not a valid m3u8", 400

    except Exception as e:
        return f"Manifest Error: {e}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9000, threaded=True)
