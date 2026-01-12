import json
import os
import asyncio
from playwright.async_api import async_playwright
import requests

# Config
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
PRODUCT_URLS = os.environ["PRODUCT_URLS"].split(",")
STATE_FILE = "stock_state.json"
PAGE_TIMEOUT = 15000  # 15s max
OUT_TEXTS = ["Rupture de stock", "Indisponible", "En réassort"]

# Fonctions
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
    try:
        print(f"→ Vérification {url}")
        await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        # Nom produit
        h1 = await page.query_selector("h1")
        if h1:
            product_name = (await h1.inner_text()).strip()
        # Texte disponible
        body_text = await page.inner_text("body")
        # Vérification OUT_TEXTS
        if any(txt in body_text for txt in OUT_TEXTS):
            in_stock = False
            print(f"{product_name} : Hors stock")
        else:
            in_stock = True
            print(f"{product_name} : EN STOCK")
    except Exception as e:
        print(f"⚠ Timeout ou erreur pour {url}: {e}")
        in_stock = False
    return product_name, in_stock

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
