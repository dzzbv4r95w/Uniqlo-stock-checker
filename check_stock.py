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

# Master Stock Identifiers (Exact text matches for primary CTA)
IN_STOCK_KEYWORD = "ajouter au panier"
OUT_OF_STOCK_KEYWORDS = ["de nouveau en stock", "indisponible", "rupture de stock", "épuisé"]
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
        
        # Pull initial page elements instantly
        await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="commit")
        
        # Give Uniqlo's background API 8 seconds to process variant codes (size/color)
        await page.wait_for_timeout(8000)
        
        # Capture product name
        h1 = await page.query_selector("h1")
        if h1:
            product_name = (await h1.inner_text()).strip()
            
        # Target all buttons sequentially from top to bottom
        all_buttons = page.locator("button")
        btn_count = await all_buttons.count()
        
        main_button_text = None
        target_keywords = [IN_STOCK_KEYWORD] + OUT_OF_STOCK_KEYWORDS
        
        # Find the very FIRST button that matches a key stock action string
        for i in range(btn_count):
            try:
                btn_text = await all_buttons.nth(i).inner_text()
                cleaned_text = " ".join(btn_text.lower().split())
                
                # CRITICAL IMPROVEMENT: Check for strict matching so marketing banners don't cause false alarms
                if cleaned_text == IN_STOCK_KEYWORD or cleaned_text in OUT_OF_STOCK_KEYWORDS:
                    main_button_text = cleaned_text
                    print(f"   [Found CTA] Primary action button identified: '{cleaned_text}'")
                    break
            except:
                pass

        # UNIQLO FINAL EVALUATION LOGIC
        if main_button_text == IN_STOCK_KEYWORD:
            in_stock = True
            print(f"🟢 {product_name} : EN STOCK 🎉")
            
        elif main_button_text in OUT_OF_STOCK_KEYWORDS:
            in_stock = False
            print(f"🔴 {product_name} : Hors stock ({main_button_text})")
            
        else:
            # Fallback scan if layout structure renders oddly
            body_text = (await page.inner_text("body")).lower()
            if IN_STOCK_KEYWORD in body_text and not any(out in body_text for out in OUT_OF_STOCK_KEYWORDS):
                in_stock = True
                print(f"🟢 {product_name} : EN STOCK (Fallback Detection)")
            else:
                in_stock = False
                print(f"🔴 {product_name} : Hors stock (Bouton principal introuvable/inactif)")
            
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
            
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = await context.new_page()
            
            product_name, in_stock = await check_product(page, url)
            last_state = state.get(url, {}).get("in_stock", False)
            
            # Trigger notification only on a clean state switch
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
