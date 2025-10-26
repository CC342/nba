from playwright.sync_api import sync_playwright, TimeoutError
import re

URL = "https://www.nbabite.is/Golden-State-Warriors-vs-Denver-Nuggets/51545"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
MAX_WAIT = 8  # 最大等待时间，秒

def fetch_sportsbest_input(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        page.set_default_timeout(MAX_WAIT * 1000)

        try:
            page.goto(url, wait_until="networkidle")
        except TimeoutError:
            pass

        # 使用 locator 快速查找 td.display-bg 中 Sportsbest
        td_elements = page.locator("td.display-bg")
        count = td_elements.count()
        input_value = None

        for i in range(count):
            td_text = td_elements.nth(i).inner_text().strip().lower()
            if td_text == "sportsbest":
                onclick_val = td_elements.nth(i).get_attribute("onclick") or ""
                m = re.search(r'view\((\d+)\)', onclick_val)
                if m:
                    view_id = m.group(1)
                    input_locator = page.locator(f"input#linkk{view_id}")
                    if input_locator.count() > 0:
                        input_value = input_locator.first.get_attribute("value")
                        break

        browser.close()
        return input_value

if __name__ == "__main__":
    result = fetch_sportsbest_input(URL)
    print(result if result else "")

