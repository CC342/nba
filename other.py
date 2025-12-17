from flask import Flask, Response, request, make_response
import requests
import urllib3
from urllib.parse import quote, unquote

app = Flask(__name__)

UPSTREAM_DOMAIN = "https://gg.poocloud.in"

HEADERS = {
    "Referer": "https://embedsports.top/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

@app.route('/external_proxy')
def external_proxy():
    # 获取原始的外部链接
    real_url = request.args.get('url')
    if not real_url:
        return "Missing URL", 400
    
    # 解码 (如果被多次编码)
    real_url = unquote(real_url)
    
    print(f"[Ext Proxy] -> {real_url[:60]}...") # 打印日志，只显示前60字符防止刷屏

    try:
        # 直接请求这个外部地址 (比如 corsproxy.io 或 fotor.com)
        r = requests.get(real_url, headers=HEADERS, stream=True, verify="/etc/ssl/certs/ca-certificates.crt")
        
        # 透传数据
        def generate():
            for chunk in r.iter_content(chunk_size=4096):
                yield chunk

        resp = Response(generate(), status=r.status_code)
        
        # 复制必要的头
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        for name, value in r.headers.items():
            if name.lower() not in excluded_headers:
                resp.headers[name] = value
        
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
        
    except Exception as e:
        print(f"Ext Error: {e}")
        return str(e), 500


# ==========================================
# 主路由：处理干净的 m3u8 地址
# ==========================================
@app.route('/<path:subpath>')
def main_proxy(subpath):
    # 构造上游 URL
    upstream_url = f"{UPSTREAM_DOMAIN}/{subpath}"
    
    # 传递 Token
    current_query = request.query_string.decode('utf-8')
    if current_query:
        upstream_url += f"?{current_query}"

    print(f"[Main Proxy] -> {upstream_url}")

    try:
        r = requests.get(upstream_url, headers=HEADERS, stream=True, verify="/etc/ssl/certs/ca-certificates.crt")
        
        if "google.com" in r.url:
            print("❌ Blocked by source (Google Redirect)")
            return "Blocked", 403

        content_type = r.headers.get("Content-Type", "")

        # --- M3U8 重写逻辑 ---
        if "application/vnd.apple.mpegurl" in content_type or subpath.endswith(".m3u8"):
            try:
                content = r.content.decode('utf-8', errors='ignore')
            except:
                return Response(r.content, status=r.status_code, headers=dict(r.headers))

            lines = content.splitlines()
            new_lines = []

            for line in lines:
                if line.startswith("#") or not line.strip():
                    new_lines.append(line)
                    continue
                
                clean_line = line.strip()

                # 1. 情况 A: 属于 upstream 的链接 (gg.poocloud.in)
                # 变成相对路径，保持优雅
                if UPSTREAM_DOMAIN in clean_line:
                    clean_line = clean_line.replace(UPSTREAM_DOMAIN, "")
                    if not clean_line.startswith("/"):
                        clean_line = "/" + clean_line
                    
                    # 补上 Token (防止断连)
                    if current_query:
                        separator = "&" if "?" in clean_line else "?"
                        clean_line = f"{clean_line}{separator}{current_query}"
                
                # 2. 情况 B: 外部链接 (corsproxy, fotor 等)
                # 【关键修复】这里把外部链接转发给我们的辅助路由 /external_proxy
                elif clean_line.startswith("http"):
                    # 编码这个 URL
                    encoded_url = quote(clean_line)
                    # 重写为走我们的代理
                    clean_line = f"/external_proxy?url={encoded_url}"

                new_lines.append(clean_line)

            resp = make_response("\n".join(new_lines))
            resp.headers["Content-Type"] = "application/vnd.apple.mpegurl"
            resp.headers["Access-Control-Allow-Origin"] = "*"
            return resp

        # 普通文件直接透传
        else:
            def generate():
                for chunk in r.iter_content(chunk_size=4096):
                    yield chunk
            resp = Response(generate(), status=r.status_code)
            for name, value in r.headers.items():
                if name.lower() not in ['content-encoding', 'content-length', 'transfer-encoding', 'connection']:
                    resp.headers[name] = value
            resp.headers["Access-Control-Allow-Origin"] = "*"
            return resp

    except Exception as e:
        print(f"Error: {e}")
        return str(e), 500


if __name__ == '__main__':
    # 使用 0.0.0.0 允许公网访问
    app.run(host='0.0.0.0', port=9000, debug=False, threaded=True)
