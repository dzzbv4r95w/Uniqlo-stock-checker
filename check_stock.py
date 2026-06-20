import json
import os
import asyncio
from playwright.async_api import async_playwright
import requests

# Config
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
PRODUCT_URLS = os.environ["PRODUCT_URLS"].split(",")
STATE_FILE = "stock_state.json"
PAGE_TIMEOUT = 20000  # Bumped to 20s for networkidle safety

# Crucial: Keep these lowercase for the case-insensitive check later
OUT_TEXTS = ["rupture de stock", "indisponible", "en réassort", "épuisé"]

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
        
        # FIX 1: Use "networkidle" so background scripts can finish loading stock status
        await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="networkidle")
        
        # Optional Safety: Hard pause for 1.5 seconds to let scripts render UI elements
        await page.wait_for_timeout(1500)
        
        # Nom produit
        h1 = await page.query_selector("h1")
        if h1:
            product_name = (await h1.inner_text()).strip()
            
        # Texte disponible
        body_text = await page.inner_text("body")
        
        # FIX 2: Convert the entire page text to lowercase to prevent casing bugs
        body_text_lowercase = body_text.lower()
        
        # Vérification OUT_TEXTS (Case-insensitive)
        if any(txt in body_text_lowercase for txt in OUT_TEXTS):
            in_stock = False
            print(f"{product_name} : Hors stock")
        else:
            in_stock = True
            print(f"{product_name} : EN STOCK 🎉")
            
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
            # Best practice: Use a unique browser context per page to isolate cookies/sessions
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            product_name, in_stock = await check_product(page, url)
            last_state = state.get(url, {}).get("in_stock")
            
            if in_stock and last_state != True:
                notify_discord(product_name, url)
                print(f"ALERTE envoyée: {product_name}")
                
            state[url] = {"in_stock": in_stock}
            await context.close()  # Closes page and context cleaner
            
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
