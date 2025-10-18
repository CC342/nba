from WXBizMsgCrypt import WXBizMsgCrypt
from flask import Flask, request, make_response
import subprocess
import logging
import xml.etree.ElementTree as ET

app = Flask(__name__)

# 企业微信开发者接口配置
TOKEN = "企业微信应用——接收消息——启用api"
ENCODING_AES_KEY = "企业微信应用——接收消息——启用api"
CORP_ID = "企业微信id"

# 初始化加解密类
crypto = WXBizMsgCrypt(TOKEN, ENCODING_AES_KEY, CORP_ID)

logging.basicConfig(level=logging.DEBUG)

@app.route('/proxy')
def hls_proxy():
    import requests
    import urllib.parse

    # 获取 URL 参数
    url = request.args.get('url')
    if not url:
        return "Missing url", 400

    # URL decode（防止特殊字符出错）
    url = urllib.parse.unquote(url)

    # 把 index.m3u8 替换为 tracks-v1a1/mono.ts.m3u8
    url_modified = url.replace("index.m3u8", "tracks-v1a1/mono.ts.m3u8")
    print(f"[HLS Proxy] 原始: {url} -> 修改: {url_modified}")

    # 请求远程 m3u8/ts
    headers = {
        "Referer": "https://embedsports.top/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0 Safari/537.36"
    }
    resp = requests.get(url_modified, headers=headers, stream=True)
    return resp.content, resp.status_code, resp.headers.items()

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
