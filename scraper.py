"""只取得頁面原始卡片，解析與資料庫由其他模組處理。"""
import re
import time
from urllib.parse import urlencode

SELECTOR = 'main li, [role="main"] li'


def search_url(config):
    query = (f"Flights from {config['origin']} to {config['destination']} "
             f"on {config['departure_date']}")
    query += (f" returning {config['return_date']}" if config["return_date"] else " one way")
    query += " 1 adult economy"
    return "https://www.google.com/travel/flights?" + urlencode(
        {"q": query, "hl": "en", "curr": config["currency"]})


def fetch_cards(config, headed=False, pause=False):
    from playwright.sync_api import sync_playwright

    url = search_url(config)
    with sync_playwright() as playwright:
        options = {"headless": not headed}
        if config["browser_channel"] != "chromium":
            options["channel"] = config["browser_channel"]
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page(locale="en-US")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            for name in ("Reject all", "Accept all"):
                button = page.get_by_role("button", name=name, exact=True)
                if button.count() and button.first.is_visible():
                    button.first.click(timeout=5000)
                    break
            started = time.monotonic()
            changed_at = started
            previous = None
            cards = []
            reason = "timeout"
            while time.monotonic() - started < config["max_wait_seconds"]:
                body = page.locator("body").inner_text(timeout=10000)
                if re.search(r"unusual traffic|verify you are human|not a robot", body, re.I):
                    raise RuntimeError("遇到網站驗證或存取限制；請暫停排程")
                cards = page.locator(SELECTOR).all_inner_texts()
                signature = tuple(cards)
                now = time.monotonic()
                if signature != previous:
                    changed_at, previous = now, signature
                # 沒有報價的卡片等到上限，避免第一筆價格出現就提前結束。
                if (cards and now - started >= config["min_wait_seconds"]
                        and now - changed_at >= config["stable_seconds"]):
                    reason = "stable"
                    break
                page.wait_for_timeout(1000)
            if not cards:
                raise RuntimeError("未讀到清單卡片；可能無航班、載入失敗或選擇器需調整")
            if headed and pause:
                input("請核對條件，按 Enter 後重新讀取卡片並關閉瀏覽器……")
                cards = page.locator(SELECTOR).all_inner_texts()
            return {"cards": cards, "url": page.url, "wait_reason": reason}
        finally:
            browser.close()
