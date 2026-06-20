import json
import os
import asyncio
from playwright.async_api import async_playwright
import requests

# ==================== CONFIGURATION ====================
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
PRODUCT_URLS = os.environ.get("PRODUCT_URLS", "").split(",")
STATE_FILE = "stock_state.json"
PAGE_TIMEOUT = 30000  # 30 seconds max loading buffer

# Target Keywords (Keep everything lowercase for safe matching)
IN_STOCK_TEXT = "ajouter au panier"
FALSE_ALARM_TEXT = "de nouveau en stock"  # This means 'Notify me when back in stock' -> SOLD OUT
# =======================================================

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            content = f.read().strip()
            if not content:  
                return {}
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        # Automatically heals empty or corrupted state files
        print(f"ℹ️ {STATE_FILE} missing or blank. Starting fresh tracking history.")
        return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"⚠ Failed to save state file: {e}")

def notify_discord(product_name, url):
    if not DISCORD_WEBHOOK:
        print("⚠ Warning: DISCORD_WEBHOOK secret is missing. Cannot send alert.")
        return
        
    message = {"content": f"🚨 **UNIQLO IN STOCK!** 🚨\nProduit: **{product_name}**\nLien: {url}"}
    try:
        response = requests.post(DISCORD_WEBHOOK, json=message, timeout=10)
        if response.status_code in [200, 204]:
            print(f"📡 Discord notification sent for: {product_name}")
        else:
            print(f"⚠ Discord returned status code: {response.status_code}")
    except Exception as e:
        print("❌ Failed to reach Discord API:", e)

async def check_product(page, url):
    product_name = "Produit inconnu"
    in_stock = False
    
    try:
        print(f"→ Connexion en cours: {url}")
        
        # Load the page layout structure first
        await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="load")
        
        # CRITICAL FIX: Uniqlo loads inventory data slowly via background APIs.
        # We hold the browser open for 6 full seconds to let the real variant button render.
        await page.wait_for_timeout(6000)
        
        # Capture the product name
        h1 = await page.query_selector("h1")
        if h1:
            product_name = (await h1.inner_text()).strip()
            
        # Extract whole page layout text and lowercase it
        body_text_lowercase = (await page.inner_text("body")).lower()
        
        # UNIQLO-SPECIFIC LOGIC ENGINE
        # Rule 1: If the email alert alert button "de nouveau en stock" exists, it is definitively SOLD OUT.
        if FALSE_ALARM_TEXT in body_text_lowercase:
            in_stock = False
            print(f"🔴 {product_name} : Hors stock (Bouton d'alerte mail détecté)")
            
        # Rule 2: If the alert button is gone and the buy button is visible, it is IN STOCK.
        elif IN_STOCK_TEXT in body_text_lowercase:
            in_stock = True
            print(f"🟢 {product_name} : EN STOCK 🎉")
            
        # Rule 3: Safety net fallback if neither text pattern resolves
        else:
            in_stock = False
            print(f"🔴 {product_name} : Hors stock (Bouton d'achat invisible)")
            
    except Exception as e:
        print(f"❌ Erreur ou Timeout pour {url}: {e}")
        in_stock = False
        
    return product_name, in_stock

async def main():
    state = load_state()
    
    # Clean up white space and eliminate empty lines from the secret link array
    urls_to_check = [url.strip() for url in PRODUCT_URLS if url.strip()]
    if not urls_to_check:
        print("❌ Error: No product URLs found inside your PRODUCT_URLS secret.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        tasks = []
        
        async def process_url(url):
            # Create a clean isolated desktop session with standard browser dimensions
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = await context.new_page()
            
            product_name, in_stock = await check_product(page, url)
            last_state = state.get(url, {}).get("in_stock", False)
            
            # Fire Discord notification only on a fresh transition to in-stock
            if in_stock and not last_state:
                notify_discord(product_name, url)
                
            state[url] = {"in_stock": in_stock, "product_name": product_name}
            await context.close()
            
        for url in urls_to_check:
            tasks.append(process_url(url))
            
        # Execute checks for all links simultaneously in parallel paths
        await asyncio.gather(*tasks)
        await browser.close()
        
    save_state(state)
    print("✅ Session de vérification terminée avec succès.")

if __name__ == "__main__":
    asyncio.run(main())
