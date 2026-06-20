import json
import os
import asyncio
from playwright.async_api import async_playwright
import requests

# ==================== CONFIGURATION ====================
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
PRODUCT_URLS = os.environ.get("PRODUCT_URLS", "").split(",")
STATE_FILE = "stock_state.json"
PAGE_TIMEOUT = 30000  

# Target Keywords (Keep lowercase, spaces will be normalized automatically)
IN_STOCK_TEXT = "ajouter au panier"
FALSE_ALARM_TEXT = "de nouveau en stock"  # Email alert button text = SOLD OUT
# =======================================================

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            content = f.read().strip()
            if not content:  
                return {}
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
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
        
        # Open page structure
        await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="commit")
        
        # CRITICAL FIX: Give Uniqlo's system 8 full seconds to process your URL parameters 
        # (size/color codes) and swap the default interface out for the true availability data.
        await page.wait_for_timeout(8000)
        
        # Capture the product name
        h1 = await page.query_selector("h1")
        if h1:
            product_name = (await h1.inner_text()).strip()
            
        # Extract page layout text
        raw_body_text = await page.inner_text("body")
        
        # TEXT NORMALIZATION FIX: This strips out hidden elements, newlines (\n), and 
        # complex HTML non-breaking spaces (\xa0 / &nbsp;), turning everything into clean single spaces.
        body_text_clean = " ".join(raw_body_text.lower().split())
        
        # Live diagnostic logs inside your GitHub terminal
        has_false_alarm_btn = FALSE_ALARM_TEXT in body_text_clean
        has_buy_btn = IN_STOCK_TEXT in body_text_clean
        print(f"   [Diagnostic] Alerte mail détectée ? {has_false_alarm_btn} | Bouton d'achat détecté ? {has_buy_btn}")
        
        # UNIQLO CRITICAL LOGIC ENGINE
        # Rule 1: If "de nouveau en stock" is anywhere on the page, the main variant is definitively out of stock.
        if has_false_alarm_btn:
            in_stock = False
            print(f"🔴 {product_name} : Hors stock (Bouton d'alerte mail actif)")
            
        # Rule 2: If the email alert button is missing but the buy text is found, it's open for purchase!
        elif has_buy_btn:
            in_stock = True
            print(f"🟢 {product_name} : EN STOCK 🎉")
            
        # Rule 3: Backup safety switch
        else:
            in_stock = False
            print(f"🔴 {product_name} : Hors stock (Bouton d'achat introuvable)")
            
    except Exception as e:
        print(f"❌ Erreur ou Timeout pour {url}: {e}")
        in_stock = False
        
    return product_name, in_stock

async def main():
    state = load_state()
    urls_to_check = [url.strip() for url in PRODUCT_URLS if url.strip()]
    if not urls_to_check:
        print("❌ Error: No product URLs found inside your PRODUCT_URLS secret.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--ignore-certificate-errors"
            ]
        )
        tasks = []
        
        async def process_url(url):
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="fr-BE",
                timezone_id="Europe/Brussels"
            )
            
            # Mask automated web automation presence
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            page = await context.new_page()
            product_name, in_stock = await check_product(page, url)
            last_state = state.get(url, {}).get("in_stock", False)
            
            if in_stock and not last_state:
                notify_discord(product_name, url)
                print(f"🔔 Notification envoyée pour {product_name} !")
                
            state[url] = {"in_stock": in_stock, "product_name": product_name}
            await context.close()
            
        for url in urls_to_check:
            tasks.append(process_url(url))
            
        await asyncio.gather(*tasks)
        browser.close()
        
    save_state(state)
    print("✅ Session de vérification terminée avec succès.")

if __name__ == "__main__":
    asyncio.run(main())
