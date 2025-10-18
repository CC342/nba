from bs4 import BeautifulSoup
import requests
import re

url = "https://www.nbabite.is/Philadelphia-76ers-vs-Minnesota-Timberwolves/51337"
headers = {"User-Agent": "Mozilla/5.0"}

resp = requests.get(url, headers=headers)
soup = BeautifulSoup(resp.text, "html.parser")

# 遍历所有 td
for td in soup.find_all("td", class_="display-bg"):
    text = td.get_text(strip=True).lower()  # 获取文本，包括子标签
    if "sheri" in text:
        onclick_val = td.get("onclick", "")
        m = re.search(r'view\((\d+)\)', onclick_val)
        if m:
            view_id = m.group(1)
            input_tag = soup.find("input", id=f"linkk{view_id}")
            if input_tag:
                print(f"sheri—{input_tag['value']}")
