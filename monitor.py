import json
import os
import re
import time
from typing import List, Dict, Set
import requests
from bs4 import BeautifulSoup

EBAY_SEARCH_URLS = [
    "https://www.ebay.com/sch/i.html?_nkw=nikon+slr+camera+bodies&LH_BIN=1",
    "https://www.ebay.com/sch/i.html?_nkw=canon+eos+film+cameras+lot&LH_BIN=1",
]

BLOCKLIST = [
    "for parts", "parts only", "untested", "junk", "job lot", "spares", "as-is",
    "broken", "repair", "read description", "mixed lot", "bundle only", "accessories"
]

BRANDS = ["nikon", "canon", "minolta", "olympus", "pentax", "konica", "yashica", "rolleiflex", "leica"]

POSITIVE_PATTERNS = {
    "count": re.compile(r"\b(\d+|two|three|four|five|six|seven|eight|nine|ten|x\d+)\b", re.I),
    "camera_body": re.compile(r"\b(camera body|slr|tlr|rangefinder)\b", re.I),
    "model_hint": re.compile(r"\b(ftn?|nikkormat|ae-1|srt|om-1|om-10|k1000|spotmatic)\b", re.I),
    "working_hint": re.compile(r"\b(shutter working|shutters working)\b", re.I),
}

SEEN_PATH = "seen.json"
UA = "Mozilla/5.0 (compatible; CameraLotMonitor/1.0; +https://github.com)"

def tg_send(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram secrets missing. Message would be:\n", text)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, data={"chat_id": chat_id, "text": text})
    if resp.status_code != 200:
        print("Telegram send failed:", resp.status_code, resp.text)

def load_seen() -> Set[str]:
    if not os.path.exists(SEEN_PATH):
        return set()
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("seen_ids", []))
    except Exception:
        return set()

def save_seen(seen: Set[str]) -> None:
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"seen_ids": sorted(list(seen))[-2000:]}, f)

def hard_reject(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in BLOCKLIST)

def score_listing(title: str) -> int:
    t = title.lower()
    if hard_reject(t):
        return -999

    score = 0
    if POSITIVE_PATTERNS["count"].search(t):
        score += 2
    if POSITIVE_PATTERNS["camera_body"].search(t):
        score += 2
    if any(b in t for b in BRANDS):
        score += 2
    if POSITIVE_PATTERNS["model_hint"].search(t):
        score += 2
    if POSITIVE_PATTERNS["working_hint"].search(t):
        score += 1

    if "accessories" in t:
        score -= 3
    if "mixed" in t:
        score -= 3
    if "collection" in t and score < 4:
        score -= 2

    return score

def fetch_search(url: str) -> List[Dict]:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    items = []
    for li in soup.select("li.s-item"):
        a = li.select_one("a.s-item__link")
        title_el = li.select_one(".s-item__title")
        price_el = li.select_one(".s-item__price")
        if not a or not title_el or not price_el:
            continue

        title = title_el.get_text(" ", strip=True)
        link = a.get("href", "")
        price = price_el.get_text(" ", strip=True)
        item_id = link.split("?")[0].strip()

        if title.lower() in ["shop on ebay", "sponsored"] or len(title) < 6:
            continue

        items.append({"id": item_id, "title": title, "price": price, "link": link})

    return items

def main():
    seen = load_seen()
    alerts = []

    for url in EBAY_SEARCH_URLS:
        try:
            results = fetch_search(url)
        except Exception as e:
            print("Fetch failed:", url, e)
            continue

        for it in results:
            if it["id"] in seen:
                continue

            s = score_listing(it["title"])
            seen.add(it["id"])

            if s >= 4:
                alerts.append((s, it))

        time.sleep(2)

    save_seen(seen)

    alerts.sort(key=lambda x: x[0], reverse=True)
    alerts = alerts[:5]

    for s, it in alerts:
        msg = f"✅ Camera-lot candidate (score {s})\n{it['title']}\n{it['price']}\n{it['link']}"
        tg_send(msg)

    print(f"Run done. New seen total: {len(seen)}. Alerts sent: {len(alerts)}")

if __name__ == "__main__":
    main()
