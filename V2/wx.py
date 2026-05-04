from WXBizMsgCrypt import WXBizMsgCrypt
from flask import Flask, request, Response, make_response, redirect
import subprocess
import logging
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
import os
import json
import threading
from urllib.parse import quote, urljoin
from curl_cffi import requests

app = Flask(__name__)

# ================= 1. 基础配置 =================
load_dotenv()

# 微信配置
TOKEN = os.getenv("WX_TOKEN")
ENCODING_AES_KEY = os.getenv("WX_ENCODING_AES_KEY")
CORP_ID = os.getenv("WX_CORP_ID")

# ★★★ 路径配置 (绝对路径) ★★★
NBA_JSON_FILE = '/home/nba/game.json'
NBA_SCRAPER_SCRIPT = '/home/nba/nba.py'

SPORTS_JSON_FILE = '/home/nba/sports.json'
SPORTS_SCRAPER_SCRIPT = '/home/nba/sports.py'

# 初始化微信加密
crypto = WXBizMsgCrypt(TOKEN, ENCODING_AES_KEY, CORP_ID)

# 日志配置 (保留 Flask 启动日志)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================= 2. 核心功能函数 =================

def load_all_game_data():
    """读取并合并 NBA 和综合体育的比赛数据"""
    combined_data = {}
    
    # 读取 NBA 数据
    if os.path.exists(NBA_JSON_FILE):
        try:
            with open(NBA_JSON_FILE, 'r', encoding='utf-8') as f:
                combined_data.update(json.load(f))
        except Exception as e:
            logging.error(f"读取 NBA 数据失败: {e}")
            
    # 读取 Sports 数据
    if os.path.exists(SPORTS_JSON_FILE):
        try:
            with open(SPORTS_JSON_FILE, 'r', encoding='utf-8') as f:
                combined_data.update(json.load(f))
        except Exception as e:
            logging.error(f"读取 Sports 数据失败: {e}")
            
    return combined_data

def fetch_and_rewrite_m3u8(target_url):
    """
    代理核心：下载 M3U8 -> 重写链接 -> 返回给播放器
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://embedsports.top/",
        "Origin": "https://embedsports.top"
    }
    
    try:
        # 使用 curl_cffi 模拟浏览器指纹
        r = requests.get(target_url, headers=headers, impersonate="chrome110", timeout=10)
        
        if r.status_code != 200:
            return Response(f"#EXTM3U\n#EXT-X-ERROR: Upstream {r.status_code}", status=502, mimetype="application/vnd.apple.mpegurl")

        content = r.text
        clean_lines = []
        
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("##"): continue
            
            if line.startswith("#"):
                clean_lines.append(line)
            else:
                # 计算绝对路径
                abs_url = urljoin(target_url, line)
                
                # 递归代理逻辑：
                # 只有播放列表(.m3u8)才走代理，视频片段(.ts)全部直连
                if ".m3u8" in abs_url or "playlist" in abs_url:
                    clean_lines.append(f"/proxy?url={quote(abs_url)}")
                else:
                    clean_lines.append(abs_url)
                    
        return Response("\n".join(clean_lines), mimetype="application/vnd.apple.mpegurl")
    
    except Exception as e:
        return Response(f"#EXTM3U\n#EXT-X-ERROR: {str(e)}", status=500, mimetype="application/vnd.apple.mpegurl")

# ================= 3. 路由接口 (播放相关) =================

@app.route('/')
def index():
    return "Sports & NBA Service Running."

@app.route('/<team_key>/index.m3u8')
def team_entry(team_key):
    """短链接入口：读取 JSON 并获取真实地址"""
    data = load_all_game_data()
    if team_key not in data:
        return f"#EXTM3U\n#EXT-X-ERROR: No signal for {team_key}. Please send 'nba' or 'sports' to WeChat.", 404
    
    info = data[team_key]
    # 拼接真实源地址
    real_url = info.get('full_url')
    
    if not real_url:
        return f"#EXTM3U\n#EXT-X-ERROR: URL missing for {team_key}", 500
    
    # 调用代理函数处理 (隐形转发)
    return fetch_and_rewrite_m3u8(real_url)

@app.route('/proxy')
def proxy():
    """通用代理接口"""
    url = request.args.get('url')
    if not url: return "Missing URL", 400
    return fetch_and_rewrite_m3u8(url)

# ================= 4. 微信回调 (触发抓取) =================

@app.route('/wechat_callback', methods=['GET', 'POST'])
def wechat_callback():
    # 1. 验证 URL (企业微信后台配置时使用)
    if request.method == 'GET':
        msg_signature = request.args.get('msg_signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        echostr = request.args.get('echostr', '')
        
        ret, echo_str = crypto.VerifyURL(msg_signature, timestamp, nonce, echostr)
        if ret != 0: return "Verify Error", 400
        return Response(echo_str, content_type='text/plain')

    # 2. 接收消息
    elif request.method == 'POST':
        msg_signature = request.args.get('msg_signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        xml_data = request.data
        
        ret, decrypted_xml = crypto.DecryptMsg(xml_data, msg_signature, timestamp, nonce)
        if ret != 0: return "Decrypt Error", 400

        xml_tree = ET.fromstring(decrypted_xml)
        msg_type = xml_tree.find('MsgType').text
        
        if msg_type == 'text':
            content = xml_tree.find('Content').text.strip().lower()
            logging.info(f"收到微信消息: {content}")
            
            # 分发执行脚本
            if content == "nba":
                logging.info(f"正在后台启动: {NBA_SCRAPER_SCRIPT}")
                subprocess.Popen(["python3", NBA_SCRAPER_SCRIPT])
            elif content == "sports":
                logging.info(f"正在后台启动: {SPORTS_SCRAPER_SCRIPT}")
                subprocess.Popen(["python3", SPORTS_SCRAPER_SCRIPT])

        return "success"

if __name__ == '__main__':
    print(">>> 正在启动 Flask 服务，监听 0.0.0.0:5000 ...")
    # threaded=True 必须开启，否则代理请求会卡顿
    app.run(host='0.0.0.0', port=5000, threaded=True)
