import requests
from bs4 import BeautifulSoup
import json
import os

# --- Configuration ---
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
PRODUCT_URLS = os.environ["PRODUCT_URLS"].split(",")  # Sépare tes URLs par des virgules dans le secret
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}
STATE_FILE = "stock_state.json"

# --- Fonctions ---
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def notify_discord(product_name, url):
    message = {
        "content": f"🚨 **IN STOCK!**\n**{product_name}**\n{url}"
    }
    try:
        requests.post(DISCORD_WEBHOOK, json=message, timeout=10)
    except Exception as e:
        print("Erreur Discord:", e)

def check_stock(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")

        # Nom du produit
        h1 = soup.find("h1")
        product_name = h1.get_text(strip=True) if h1 else "Produit inconnu"

        # Vérifier bouton "Ajouter au panier"
        btn = soup.find("button", string=lambda x: x and "Ajouter au panier" in x)
        in_stock = bool(btn)

        return product_name, in_stock

    except Exception as e:
        print("Erreur sur URL:", url, e)
        return "Erreur produit", False

# --- Main ---
def main():
    state = load_state()

    for url in PRODUCT_URLS:
        url = url.strip()
        if not url:
            continue

        product_name, in_stock = check_stock(url)
        last_status = state.get(url)

        print(f"{product_name} => {'IN STOCK' if in_stock else 'OUT OF STOCK'}")

        # Alert only when OUT → IN
        if in_stock and last_status != "in":
            notify_discord(product_name, url)
            print("ALERTE envoyée:", product_name)

        # Mettre à jour l'état
        state[url] = "in" if in_stock else "out"

    save_state(state)

if __name__ == "__main__":
    main()
