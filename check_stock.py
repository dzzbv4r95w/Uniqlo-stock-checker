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
    text = soup.get_text(" ", strip=True).lower()

    # ❌ OUT OF STOCK keywords (Belgium FR + NL + EN)
    out_keywords = [
        "out of stock",
        "sold out",
        "rupture de stock",
        "épuisé",
        "me notifier",
        "notifier",
        "niet op voorraad",
        "momenteel niet beschikbaar",
        "breng mij op de hoogte",
        "verwittig"
    ]

    for word in out_keywords:
        if word in text:
            return False

    # ✅ IN STOCK keywords (Belgium FR + NL + EN)
    in_keywords = [
        "add to cart",
        "add to bag",
        "ajouter au panier",
        "ajouter au sac",
        "in winkelwagen",
        "toevoegen"
    ]

    for word in in_keywords:
        if word in text:
            return True

    # Default fallback
    return False


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

            # ✅ Alert only when status changes from OUT → IN
            if in_stock and last_status != "in":
                notify(product_name, url)
                print(f"ALERT SENT: {product_name}")

            # Save current state
            state[url] = "in" if in_stock else "out"
            print(f"{product_name}: {'IN STOCK' if in_stock else 'OUT OF STOCK'}")

        except Exception as e:
            print("Error checking:", url, e)

    save_state(state)


if __name__ == "__main__":
    main()
