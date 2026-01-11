import requests
from bs4 import BeautifulSoup
import os
import json

# Secrets from GitHub
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
PRODUCT_URLS = os.environ["PRODUCT_URLS"].split(",")

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

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


def get_product_name(soup):
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return "Unknown product"


def is_in_stock(soup):
    """
    Belgium logic (button-based only):

    ❌ If ANY button contains "de nouveau en stock" → OUT OF STOCK
    ✅ Otherwise → IN STOCK

    We intentionally ignore "ajouter au panier" because it exists
    in Uniqlo templates even when product is unavailable.
    """

    buttons = soup.find_all("button")

    for btn in buttons:
        text = btn.get_text(" ", strip=True).lower()

        # Strong OUT signal
        if "de nouveau en stock" in text:
            return False

    # If the OUT button is NOT present, treat as IN
    return True


def notify(product_name, url):
    message = {
        "content": f"🚨 **IN STOCK!**\n**{product_name}**\n{url}"
    }
    requests.post(DISCORD_WEBHOOK, json=message, timeout=10)


def main():
    state = load_state()

    for raw_url in PRODUCT_URLS:
        url = raw_url.strip()
        if not url:
            continue

        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(response.text, "html.parser")

            product_name = get_product_name(soup)
            in_stock = is_in_stock(soup)

            last_status = state.get(url)

            # ✅ Alert only when OUT → IN
            if in_stock and last_status != "in":
                notify(product_name, url)
                print(f"ALERT SENT: {product_name}")

            state[url] = "in" if in_stock else "out"
            print(f"{product_name}: {'IN STOCK' if in_stock else 'OUT OF STOCK'}")

        except Exception as e:
            print("Error checking:", url, e)

    save_state(state)


if __name__ == "__main__":
    main()
