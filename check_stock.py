import requests
from bs4 import BeautifulSoup
import os
import json

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
PRODUCT_URLS = os.environ["PRODUCT_URLS"].split(",")

HEADERS = {"User-Agent": "Mozilla/5.0"}
STATE_FILE = "stock_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def get_product_name(soup):
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else "Unknown product"

def is_in_stock(soup):
    for btn in soup.find_all("button"):
        text = btn.get_text(strip=True).lower()
        if "add to cart" in text or "add to bag" in text:
            return not btn.has_attr("disabled")
    return False

def notify(product_name, url):
    msg = {"content": f"🚨 **IN STOCK!**\n**{product_name}**\n{url}"}
    requests.post(DISCORD_WEBHOOK, json=msg, timeout=10)

def main():
    state = load_state()

    for raw_url in PRODUCT_URLS:
        url = raw_url.strip()
        if not url:
            continue

        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")

            name = get_product_name(soup)
            in_stock = is_in_stock(soup)

            last_status = state.get(url)

            # ✅ Alert only when changing from OUT → IN
            if in_stock and last_status != "in":
                notify(name, url)
                print(f"ALERT SENT: {name}")

            state[url] = "in" if in_stock else "out"
            print(f"{name}: {'IN' if in_stock else 'OUT'}")

        except Exception as e:
            print("Error checking:", url, e)

    save_state(state)

if __name__ == "__main__":
    main()
