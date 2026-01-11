import json
import os
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import requests

# --- Configuration ---
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
PRODUCT_URLS = os.environ["PRODUCT_URLS"].split(",")  # séparer par virgule
STATE_FILE = "stock_state.json"
PAGE_TIMEOUT = 20000  # 20s max pour goto
BUTTON_TIMEOUT = 5000  # 5s pour attendre le bouton
MAX_RETRIES = 2  # nombre de tentatives par produit

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
    product_name = "Produit inconnu"
    stock_info = {}

    for attempt in range(MAX_RETRIES):
        try:
            # Charger la page rapidement (DOM initial seulement)
            await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")

            # Nom du produit
            h1 = await page.query_selector("h1")
            if h1:
                product_name = (await h1.inner_text()).strip()

            # Chercher tous les boutons et détecter "Ajouter au panier"
            sizes_buttons = await page.query_selector_all("button")
            for btn in sizes_buttons:
                text = (await btn.inner_text()).strip()
                size_attr = await btn.get_attribute("data-size") or "Taille inconnue"
                stock_info[size_attr] = "Ajouter au panier" in text

            return product_name, stock_info

        except PlaywrightTimeoutError:
            print(f"Timeout sur {url}, tentative {attempt+1}")
            await asyncio.sleep(1)  # petite pause avant la prochaine tentative
        except Exception as e:
            print(f"Erreur sur {url}: {e}")
            return product_name, {}

    # Si timeout répété → considérer hors stock
    return product_name, stock_info

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

            state[url] = stock_info
            await page.close()

        # Créer une tâche par produit
        for url in PRODUCT_URLS:
            url = url.strip()
            if url:
                tasks.append(process_url(url))

        # Exécuter toutes les tâches en parallèle
        await asyncio.gather(*tasks)
        await browser.close()

    save_state(state)

if __name__ == "__main__":
    asyncio.run(main())
