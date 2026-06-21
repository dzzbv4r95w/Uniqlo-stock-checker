import json
import os
import re
import requests

# ==================== CONFIGURATION ====================
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
PRODUCT_URLS = os.environ.get("PRODUCT_URLS", "").split(",")
STATE_FILE = "stock_state.json"
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

def query_uniqlo_api(session, market, product_id):
    """Helper function to execute direct endpoint requests across market regions"""
    api_url = f"https://www.uniqlo.com/front/api/v1/{market}/product/{product_id}/basic"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "fr-BE,fr;q=0.9"
    }
    try:
        response = session.get(api_url, headers=headers, timeout=15)
        return response
    except Exception:
        return None

def check_product_api(session, url):
    # FIXED: Extract ONLY the 6-digit numerical ID expected by Uniqlo's database API
    prod_match = re.search(r"products/E?(\d+)", url)
    if not prod_match:
        print(f"❌ Could not parse a valid numerical Uniqlo ID from link: {url}")
        return "Produit inconnu", False
        
    clean_id = prod_match.group(1)
    
    # Extract specific target tracking constraints from the URL string parameters
    target_color = re.search(r"colorDisplayCode=(\d+)", url)
    target_size = re.search(r"sizeDisplayCode=(\d+)", url)
    
    color_code = target_color.group(1) if target_color else None
    size_code = target_size.group(1) if target_size else None
    
    print(f"→ Extraction: ID {clean_id} | Couleur ciblée: {color_code} | Taille ciblée: {size_code}")
    
    # Executing multi-market pivot checks to avoid region-lock 404s
    response = query_uniqlo_api(session, "be", clean_id)
    
    if response is None or response.status_code == 404:
        print(f"   [Pivot] Node 'be' returned 404. Attempting fallback query on regional node 'eu'...")
        response = query_uniqlo_api(session, "eu", clean_id)
        
    if response is None or response.status_code != 200:
        status_code = response.status_code if response else "Timeout"
        print(f"❌ Uniqlo API rejected requests for product ID {clean_id} (Code: {status_code})")
        return "Produit inconnu", False
        
    try:
        data = response.json()
        product_data = data.get("result", {}).get("product", {})
        if not product_data and "result" in data:
            product_data = data["result"]
            
        if not isinstance(product_data, dict):
            print(f"❌ Malformed response payload schema received for ID {clean_id}")
            return "Produit inconnu", False
            
        product_name = product_data.get("name", product_data.get("title", f"Produit Uniqlo {clean_id}")).strip()
        variants = product_data.get("l1s", product_data.get("items", []))
        
        if not variants:
            print(f"⚠ Database response contains empty variant arrays for ID {clean_id}")
            return product_name, False
            
        in_stock = False
        matched_variants_checked = 0
        
        # Walk the multi-dimensional database matrix evaluating stock metrics
        for item in variants:
            if not isinstance(item, dict):
                continue
                
            item_color = str(item.get("colorCode", item.get("color", "")))
            item_size = str(item.get("sizeCode", item.get("size", "")))
            
            # Extract stock metrics and check status flags safely
            stock_qty = item.get("stock", item.get("quantity", item.get("qty", 0)))
            is_salable = item.get("salable", item.get("available", True))
            
            if isinstance(stock_qty, bool):
                has_stock = stock_qty
            elif isinstance(stock_qty, (int, float)):
                has_stock = stock_qty > 0
            elif isinstance(stock_qty, str):
                has_stock = stock_qty.isdigit() and int(stock_qty) > 0
            else:
                has_stock = False
                
            variant_available = has_stock and is_salable
            
            # Filter checks based on link parameters
            match_color = (color_code is None) or (item_color == color_code)
            match_size = (size_code is None) or (item_size == size_code)
            
            if match_color and match_size:
                matched_variants_checked += 1
                if variant_available:
                    in_stock = True
                    break
                    
        # General Fallback: If URL filter codes didn't align, verify overall layout status
        if matched_variants_checked == 0 and variants:
            for item in variants:
                if isinstance(item, dict):
                    qty = item.get("stock", item.get("quantity", 0))
                    if isinstance(qty, (int, float)) and qty > 0:
                        in_stock = True
                        break
                    
        emoji = "🟢" if in_stock else "🔴"
        status_text = "EN STOCK 🎉" if in_stock else "Hors stock"
        print(f"{emoji} {product_name} ({clean_id}) : {status_text}")
        return product_name, in_stock
        
    except Exception as e:
        print(f"❌ Exception occurred parsing inventory streams for ID {clean_id}: {e}")
        return "Produit inconnu", False

def main():
    state = load_state()
    urls_to_check = [url.strip() for url in PRODUCT_URLS if url.strip()]
    if not urls_to_check:
        print("❌ Error: No product URLs found inside your PRODUCT_URLS secret.")
        return

    # Use a persistent network session to bypass Akamai rate-limiting blocks
    with requests.Session() as session:
        for url in urls_to_check:
            product_name, in_stock = check_product_api(session, url)
            last_state = state.get(url, {}).get("in_stock", False)
            
            if in_stock and not last_state:
                notify_discord(product_name, url)
                print(f"🔔 Restock notification dispatched for {product_name}!")
                
            state[url] = {"in_stock": in_stock, "product_name": product_name}
        
    save_state(state)
    print("✅ System verification run completed successfully.")

if __name__ == "__main__":
    main()
