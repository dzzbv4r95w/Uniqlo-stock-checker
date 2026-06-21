import json
import os
import asyncio
from playwright.async_api import async_playwright
import requests

# ==================== CONFIGURATION ====================
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
PRODUCT_URLS = os.environ.get("PRODUCT_URLS", "").split(",")
STATE_FILE = "stock_state.json"
PAGE_TIMEOUT = 15000  # Cut off hanging threads after 15 seconds max

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
        
    message = {"content": f"🚨 **UNIQLO BE RESTOCK!** 🚨\nProduit: **{product_name}**\nLien: {url}"}
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
        
        # Pull layout structure instantly
        await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        
        # Give Uniqlo Belgium's system 7 seconds to resolve size/color variant parameters
        await page.wait_for_timeout(7000)
        
        # Capture product name
        h1 = await page.query_selector("h1")
        if h1:
            product_name = (await h1.inner_text()).strip()
            
        # DUAL-LAYER FIX 1: Lock onto Uniqlo's primary checkout block container
        buybox = None
        for selector in ["div.fr-pdp-controls", "div[class*='pdp-controls']", "div.product-form", "section[class*='product-order']"]:
            loc = page.locator(selector).first
            if await loc.count() > 0 and await loc.is_visible():
                buybox = loc
                print(f"   [Container Scope] Locked onto control panel: '{selector}'")
                break
                
        # Fall back to page context if layout wrapper shifts dynamically
        search_scope = buybox if buybox else page
        all_buttons = search_scope.locator("button")
        btn_count = await all_buttons.count()
        
        primary_cta_text = None
        all_keywords = [IN_STOCK_KEYWORD] + OUT_OF_STOCK_KEYWORDS
        
        # Evaluate primary block items sequentially
        for i in range(btn_count):
            try:
                btn = all_buttons.nth(i)
                if await btn.is_visible():
                    btn_text = await btn.inner_text()
                    cleaned_text = " ".join(btn_text.lower().split())
                    
                    if any(kw in cleaned_text for kw in all_keywords):
                        # DUAL-LAYER FIX 2: Validate buy button execution status attributes
                        if IN_STOCK_KEYWORD in cleaned_text:
                            if await btn.is_enabled():
                                primary_cta_text = cleaned_text
                                print(f"   [Active CTA] Buy button is fully active: '{cleaned_text}'")
                                break
                            else:
                                print(f"   [Disabled CTA] Found buy button text, but it is grayed out/disabled by Uniqlo.")
                        else:
                            # Direct out-of-stock button match (like an enabled 'De nouveau en stock' email notifier)
                            primary_cta_text = cleaned_text
                            print(f"   [Active CTA] Out-of-stock indicator active: '{cleaned_text}'")
                            break
            except:
                pass

        # Final Evaluation Tree
        if primary_cta_text and IN_STOCK_KEYWORD in primary_cta_text:
            in_stock = True
            print(f"🟢 {product_name} : EN STOCK 🎉")
        elif primary_cta_text and any(out in primary_cta_text for out in OUT_OF_STOCK_KEYWORDS):
            in_stock = False
            print(f"🔴 {product_name} : Hors stock ({primary_cta_text})")
        else:
            # Emergency layout panel string fallbacks
            panel_text = (await buybox.inner_text()).lower() if buybox else (await page.inner_text("body")).lower()
            if any(out in panel_text for out in OUT_OF_STOCK_KEYWORDS):
                in_stock = False
                print(f"🔴 {product_name} : Hors stock (Panel String Guard)")
            elif IN_STOCK_KEYWORD in panel_text and buybox:
                in_stock = True
                print(f"🟢 {product_name} : EN STOCK 🎉 (Panel String Guard)")
            else:
                in_stock = False
                print(f"🔴 {product_name} : Hors stock (No active checkout paths verified)")
            
    except Exception as e:
        print(f"❌ Timeout ou restriction réseau sur {url}")
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
            
            if in_stock and not last_state:
                notify_discord(product_name, url)
                print(f"🔔 Restock alert fired for {product_name}!")
                
            state[url] = {"in_stock": in_stock, "product_name": product_name}
            await context.close()
            
        for url in urls_to_check:
            tasks.append(process_url(url))
            
        # Execute all tracking queries concurrently in parallel paths
        await asyncio.gather(*tasks)
        await browser.close()
        
    save_state(state)
    print("✅ Verification cycle finished successfully.")

if __name__ == "__main__":
    asyncio.run(main())
