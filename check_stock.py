import requests
from bs4 import BeautifulSoup
import os

PRODUCT_URL = os.environ["PRODUCT_URL"]
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]

def is_in_stock():
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(PRODUCT_URL, headers=headers, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text().lower()

    if "out of stock" in text or "sold out" in text:
        return False
    return True

def notify():
    msg = {"content": f"🚨 Uniqlo item is IN STOCK!\n{PRODUCT_URL}"}
    requests.post(DISCORD_WEBHOOK, json=msg)

if __name__ == "__main__":
    if is_in_stock():
        notify()
        print("Stock available!")
    else:
        print("Still out of stock.")
