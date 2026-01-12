import json
import os
import asyncio
from playwright.async_api import async_playwright
import requests

# --- Config ---
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
PRODUCT_URLS = os.environ["PRODUCT_URLS"].split(",")
STATE_FILE = "stock_state.json"
PAGE_TIMEOUT = 40000  # 40s max pour que la page charge
MAX_RETRIES = 2
OUT_TEXTS = ["Rupture de stock", "Indisponible", "En réassort"]

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
    message = {"content": f"🚨 **IN STOCK!**\nProduit: **{product_name}**\n{url}"}
    try:
        requests.post(DISCORD_WEBHOOK, json=message, timeout=10)
    except Exception as e:
        print("Erreur Discord:", e)

async def check_product(page, url):
    product_name = "Produit inconnu"
    in_stock = False

    for attempt in range(MAX_RETRIES):
        try:
            print(f"→ Tentative {attempt+1} pour {url}")
            # Attendre que tout le JS charge
            await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="networkidle")
            await asyncio.sleep(2)  # laisser le JS injecter le DOM final

            # Nom produit
            h1 = await page.query_selector("h1")
            if h1:
                product_name = (await h1.inner_text()).strip()
            else:
                print(f"⚠ h1 non trouvé pour {url}, considéré hors stock")
                return product_name, False

            # Zone produit spécifique
            stock_div = await page.query_selector(".product-info, .product-detail")
            stock_text = (await stock_div.inner_text()).strip() if stock_div else ""
            if not stock_div:
                print(f"⚠ div stock non trouvé pour {url}, body utilisé")
                stock_text = await page.inner_text("body")

            # Vérification OUT_TEXTS
            if any(txt in stock_text for txt in OUT_TEXTS):
                in_stock = False
                print(f"{product_name} : Hors stock")
            else:
                in_stock = True
                print(f"{product_name} : EN STOCK")

            return product_name, in_stock

        except Exception as e:
            print(f"Erreur sur {url}: {e}")
            await asyncio.sleep(1)

    # Si timeout répété → considérer hors stock
    return product_name, False

async def main():
    state = load_state()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        tasks = []

        async def process_url(url):
            page = await browser.new_page()
            product_name, in_stock = await check_product(page, url)
            last_state = state.get(url, {}).get("in_stock")

            if in_stock and last_state != True:
                notify_discord(product_name, url)
                print(f"ALERTE envoyée: {product_name}")

            state[url] = {"in_stock": in_stock}
            await page.close()

        for url in PRODUCT_URLS:
            url = url.strip()
            if url:
                tasks.append(process_url(url))

        await asyncio.gather(*tasks)
        await browser.close()

    save_state(state)
    print("✅ Vérification terminée.")

if __name__ == "__main__":
    asyncio.run(main())
