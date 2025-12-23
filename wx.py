from WXBizMsgCrypt import WXBizMsgCrypt
from flask import Flask, request, make_response，Response, stream_with_context
import subprocess
import logging
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
import os

app = Flask(__name__)

load_dotenv()

TOKEN = os.getenv("WX_TOKEN")
ENCODING_AES_KEY = os.getenv("WX_ENCODING_AES_KEY")
CORP_ID = os.getenv("WX_CORP_ID")

# 初始化加解密类
crypto = WXBizMsgCrypt(TOKEN, ENCODING_AES_KEY, CORP_ID)

logging.basicConfig(level=logging.DEBUG)
logging.getLogger('werkzeug').setLevel(logging.DEBUG)

@app.route('/proxy')
def hls_proxy():
    import requests
    import urllib.parse
    # 1. 获取并解码 URL
    url = request.args.get('url')
    if not url:
        return "Missing url", 400
    
    url = urllib.parse.unquote(url)

    # 2. 针对特定源的路径替换（保留你的逻辑）
    # 注意：这里假设源只改路径，不需要改 host。如果源是相对路径，这里返回给播放器后，播放器会基于你的代理域名去拼，可能会出错。
    # 如果源 m3u8 里面全是 http 开头的绝对路径，那么这里没问题。
    url_modified = url.replace("index.m3u8", "tracks-v1a1/mono.ts.m3u8")
    print(f"[HLS Direct] Requesting: {url_modified}")

    headers = {
        "Referer": "https://embedsports.top/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0 Safari/537.36"
    }

    try:
        # 3. 请求远程 m3u8
        # stream=True 即使对于小文件也是个好习惯
        r = requests.get(
            url_modified, 
            headers=headers, 
            stream=True, 
            verify="/etc/ssl/certs/ca-certificates.crt", # 根据你的环境调整
            timeout=10
        )

        # 4. 【关键步骤】清洗 Headers
        # requests 库会自动解压 gzip 内容，所以 r.content 是明文。
        # 但 r.headers 里依然保留着 'Content-Encoding: gzip'。
        # 如果把这个 header 透传给 iOS/VLC，播放器会以为这是压缩数据再次尝试解压，导致 -1015 错误。
        
        excluded_headers = [
            'content-encoding', 
            'content-length', 
            'transfer-encoding', 
            'connection', 
            'keep-alive',
            'proxy-authenticate', 
            'proxy-authorization', 
            'te', 
            'trailers', 
            'upgrade'
        ]
        
        headers_to_return = []
        for name, value in r.headers.items():
            if name.lower() not in excluded_headers:
                headers_to_return.append((name, value))

        # 5. 返回数据
        # 使用 stream_with_context 确保在大并发下内存安全
        return Response(
            stream_with_context(r.iter_content(chunk_size=4096)),
            status=r.status_code,
            headers=headers_to_return,
            content_type=r.headers.get('content-type', 'application/vnd.apple.mpegurl')
        )

    except Exception as e:
        print(f"Error: {e}")
        return f"Proxy Error: {str(e)}", 500

# 路由改成 /wechat_callback，与企业微信后台保持一致
@app.route('/wechat_callback', methods=['GET', 'POST'])
def wechat_callback():
    if request.method == 'GET':
        # 企业微信验证 URL
        msg_signature = request.args.get('msg_signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        echostr = request.args.get('echostr', '')

        logging.debug(f"GET params - msg_signature: {msg_signature}, timestamp: {timestamp}, nonce: {nonce}, echostr: {echostr}")
        ret, echo_str = crypto.VerifyURL(msg_signature, timestamp, nonce, echostr)
        logging.debug(f"VerifyURL ret: {ret}, echo_str: {echo_str}")
        if ret != 0:
            return "验证失败", 400

        response = make_response(echo_str)
        response.headers['Content-Type'] = 'text/plain'
        return response

    elif request.method == 'POST':
        # 企业微信发送消息
        msg_signature = request.args.get('msg_signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        xml_data = request.data

        logging.debug(f"POST params - msg_signature: {msg_signature}, timestamp: {timestamp}, nonce: {nonce}")
        logging.debug(f"POST data: {xml_data}")

        ret, decrypted_xml = crypto.DecryptMsg(xml_data, msg_signature, timestamp, nonce)
        logging.debug(f"DecryptMsg ret: {ret}, decrypted_xml: {decrypted_xml}")
        if ret != 0:
            return "解密失败", 400

        # 解析 XML
        xml_tree = ET.fromstring(decrypted_xml)
        msg_type = xml_tree.find('MsgType').text if xml_tree.find('MsgType') is not None else 'unknown'

        if msg_type == 'text':
            content = xml_tree.find('Content').text.strip()
            logging.info(f"收到文本消息: {content}")

            # 如果消息是 "nba"，直接执行 nba.py，不捕获输出
            if content.lower() == "nba":
                try:
                    subprocess.Popen(["python3", "/home/nba/nba.py"])
                    logging.info("已触发 nba.py 执行")
                except Exception as e:
                    logging.error(f"执行 nba.py 失败: {e}")

        else:
            logging.info(f"收到非文本消息，类型: {msg_type}")

        return "success"


if __name__ == '__main__':
    # 使用 0.0.0.0 允许公网访问
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
