from playwright.sync_api import sync_playwright
import time

def main():
    url = "https://www.yaozh.com/"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        def handle_response(response):
            request = response.request

            if request.resource_type not in ["xhr", "fetch"]:
                return

            print("捕获接口：")
            print("方法：", request.method)
            print("地址：", request.url)
            print("状态码：", response.status)
            print("-" * 80)

        page.on("response", handle_response)

        page.goto(url, wait_until="domcontentloaded")
        time.sleep(8)

        browser.close()

if __name__ == "__main__":
    main()