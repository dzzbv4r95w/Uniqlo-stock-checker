import json
import os
import asyncio
from playwright.async_api import async_playwright
import requests

# ==================== CONFIGURATION ====================
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
PRODUCT_URLS = os.environ.get("PRODUCT_URLS", "").split(",")
STATE_FILE = "stock_state.json"
PAGE_TIMEOUT = 30000  # 30 seconds maximum for heavy loading pages

# Target Keywords (Keep everything lowercase for case-insensitive matching)
IN_STOCK_TEXTS = ["ajouter au panier"]
OUT_TEXTS = ["rupture de stock", "indisponible", "en réassort", "épuisé"]
# =======================================================

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            content = f.read().strip()
            if not content:  # If the file exists but is completely empty
                return {}
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        # Captures missing files OR invisible character spacing bugs.
        # Returns a clean dictionary to let the script run safely.
        print(f"ℹ️ {STATE_FILE} missing or unreadable. Generating a fresh state history.")
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
        if response.status_code == 204 or response.status_code == 200:
            print(f"📡 Discord notification successfully sent for: {product_name}")
        else:
            print(f"⚠ Discord returned status code: {response.status_code}")
    except Exception as e:
        print("❌ Failed to reach Discord API:", e)

async def check_product(page, url):
    product_name = "Produit inconnu"
    in_stock = False
    
    try:
        print(f"→ Connexion en cours: {url}")
        
        # 1. Wait until network activity settles
        await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="networkidle")
        
        # 2. Hard pause for 2 seconds to let the Uniqlo React engines completely swap out the placeholders
        await page.wait_for_timeout(2000)
        
        # Extract product name
        h1 = await page.query_selector("h1")
        if h1:
            product_name = (await h1.inner_text()).strip()
            
        # Extract whole page text and convert to lowercase for total case insensitivity
        body_text_lowercase = (await page.inner_text("body")).lower()
        
        # 3. ADVANCED VERIFICATION LOGIC
        # Priority 1: If "Ajouter au panier" is visible, the buy button is active!
        if any(in_txt in body_text_lowercase for in_txt in IN_STOCK_TEXTS):
            in_stock = True
            print(f"🟢 {product_name} : EN STOCK")
            
        # Priority 2: If buy text is missing and out-of-stock signals are explicitly caught
        elif any(out_txt in body_text_lowercase for out_txt in OUT_TEXTS):
            in_stock = False
            print(f"🔴 {product_name} : Hors stock")
            
        # Priority 3: Fallback safety if the site structure changes unexpectedly
        else:
            in_stock = False
            print(f"⚠ {product_name} : Impossible de lire le stock de manière définitive (Par sécurité: traité comme hors stock)")
            
    except Exception as e:
        print(f"❌ Erreur ou Timeout pour {url}: {e}")
        in_stock = False
        
    return product_name, in_stock

async def main():
    state = load_state()
    
    # Filter empty elements from product strings list
    urls_to_check = [url.strip() for url in PRODUCT_URLS if url.strip()]
    if not urls_to_check:
        print("❌ Error: No product URLs detected in your PRODUCT_URLS repository secret.")
        return

    async with async_playwright() as p:
        # Launch browser without typical bot indicators
        browser = await p.chromium.launch(headless=True)
        tasks = []
        
        async def process_url(url):
            # Isolate cookies and assign a clean Google Chrome user profile
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = await context.new_page()
            
            product_name, in_stock = await check_product(page, url)
            last_state = state.get(url, {}).get("in_stock", False)
            
            # Send notification ONLY if state switches from False (or None) to True
            if in_stock and not last_state:
                notify_discord(product_name, url)
                
            state[url] = {"in_stock": in_stock, "product_name": product_name}
            await context.close()
            
        for url in urls_to_check:
            tasks.append(process_url(url))
            
        # Execute checks simultaneously in parallel loops
        await asyncio.gather(*tasks)
        await browser.close()
        
    save_state(state)
    print("✅ Session de vérification terminée avec succès.")

if __name__ == "__main__":
    asyncio.run(main())
