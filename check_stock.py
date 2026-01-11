import json
import os
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import requests

# --- Configuration ---
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
PRODUCT_URLS = os.environ["PRODUCT_URLS"].split(",")  # séparer par virgule
STATE_FILE = "stock_state.json"
TIMEOUT = 15000  # 15 secondes max par page
WAIT_JS = 1500  # 1.5 sec pour le JS

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

def notify_discord(product_name, size, url):
    message = {
        "content": f"🚨 **IN STOCK!**\nProduit: **{product_name}**\nTaille: {size}\n{url}"
    }
    try:
        requests.post(DISCORD_WEBHOOK, json=message, timeout=10)
    except Exception as e:
        print("Erreur Discord:", e)

async def check_product(page, url):
    try:
        await page.goto(url, timeout=TIMEOUT)
        await page.wait_for_timeout(WAIT_JS)  # laisser le JS charger

        # Nom du produit
        h1 = await page.query_selector("h1")
        product_name = (await h1.inner_text()).strip() if h1 else "Produit inconnu"

        # Vérifier chaque taille
        stock_info = {}
        # Sélecteur générique pour les boutons "Ajouter au panier" en français
        sizes_buttons = await page.query_selector_all("button")
        for btn in sizes_buttons:
            text = (await btn.inner_text()).strip()
            size_attr = await btn.get_attribute("data-size") or "Taille inconnue"
            # True si le bouton indique clairement "Ajouter au panier"
            stock_info[size_attr] = "Ajouter au panier" in text

        return product_name, stock_info

    except PlaywrightTimeoutError:
        print(f"Timeout sur {url}")
        return "Erreur produit", {}
    except Exception as e:
        print(f"Erreur sur {url}: {e}")
        return "Erreur produit", {}

async def main():
    state = load_state()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        tasks = []

        async def process_url(url):
            page = await browser.new_page()
            product_name, stock_info = await check_product(page, url)
            last_state = state.get(url, {})

            for size, available in stock_info.items():
                last_available = last_state.get(size)
                if available and last_available != True:
                    notify_discord(product_name, size, url)
                    print(f"ALERTE envoyée: {product_name} Taille {size}")

            # Mise à jour de l'état local
            state[url] = stock_info
            await page.close()

        # Créer une tâche pour chaque produit
        for url in PRODUCT_URLS:
            url = url.strip()
            if url:
                tasks.append(process_url(url))

        # Exécuter toutes les tâches en parallèle
        await asyncio.gather(*tasks)
        await browser.close()

    # Sauvegarder l'état pour éviter le spam
    save_state(state)

if __name__ == "__main__":
    asyncio.run(main())
