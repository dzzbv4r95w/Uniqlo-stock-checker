from playwright.sync_api import sync_playwright
import os
import json
import requests

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
PRODUCT_URLS = os.environ["PRODUCT_URLS"].split(",")

STATE_FILE = "stock_state.json"


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def notify(product_name, url):
    payload = {
        "content": f"🚨 **IN STOCK!**\n**{product_name}**\n{url}"
    }
    requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)


def check_product(page, url):
    page.goto(url, wait_until="networkidle", timeout=60000)

    # Give JS time to update buttons
    page.wait_for_timeout(3000)

    content = page.content().lower()

    # OUT OF STOCK signal (real rendered text)
    if "de nouveau en stock" in content:
        return False

    # IN STOCK signal
    if "ajouter au panier" in content or "ajouter au sac" in content:
        return True

    # Safe fallback
    return False


def get_product_name(page):
    try:
        h1 = page.query_selector("h1")
        if h1:
            return h1.inner_text().strip()
    except:
        pass
    return "Unknown product"


def main():
    state = load_state()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for raw_url in PRODUCT_URLS:
            url = raw_url.strip()
            if not url:
                continue

            try:
                print("Checking:", url)

                in_stock = check_product(page, url)
                name = get_product_name(page)

                last_status = state.get(url)

                # Alert only when OUT → IN
                if in_stock and last_status != "in":
                    notify(name, url)
                    print("ALERT SENT:", name)

                state[url] = "in" if in_stock else "out"
                print(name, "=>", "IN STOCK" if in_stock else "OUT OF STOCK")

            except Exception as e:
                print("Error:", url, e)

        browser.close()

    save_state(state)


if __name__ == "__main__":
    main()
