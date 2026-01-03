import json
import os
import re
import time
from typing import List, Dict, Set
import requests
from bs4 import BeautifulSoup

# =========================
# CONFIG UK – EBAY SEARCHES
# =========================

EBAY_SEARCH_URLS = [
    "https://www.ebay.co.uk/sch/i.html?_nkw=camera+job+lot&LH_BIN=1",
    "https://www.ebay.co.uk/sch/i.html?_nkw=digital+camera+job+lot&LH_BIN=1",
    "https://www.ebay.co.uk/sch/i.html?_nkw=film+camera+job+lot&LH_BIN=1",
    "https://www.ebay.co.uk/sch/i.html?_nkw=compact+camera+job+lot&LH_BIN=1",
    "https://www.ebay.co.uk/sch/i.html?_nkw=slr+camera+job+lot&LH_BIN=1",
    "https://www.ebay.co.uk/sch/i.html?_nkw=dslr+camera+job+lot&LH_BIN=1",
]

# =========================
# BLOCKLIST (REAL JUNK ONLY)
# =========================

BLOCKLIST = [
    "junk",
    "spares",
    "broken",
    "repair",
    "parts only",
    "bundle only",
    "accessories"
]

# =========================
# BRANDS (COMPACT + DSLR + FILM)
# =========================

BRANDS = [
    "nikon", "canon", "olympus", "pentax", "konica", "minolta",
    "sony", "panasonic", "fujifilm", "ricoh", "casio", "kodak"
]

# =========================
# UK POSITIVE SIGNALS
# =========================

UK_POSITIVE_HINTS = [
    "job lot",
    "untested",
    "estate",
    "house clearance",
    "loft find",
    "garage find",
    "charity",
    "vintage",
    "old camera",
    "old cameras",
    "film camera",
    "film cameras",
    "digital camera",
    "digital cameras"
]

# =========================
# REGEX PATTERNS
# =========================

POSITIVE_PATTERNS = {
    "count": re.compile(r"\b(\d+|two|three|four|five|six|seven|eight|nine|ten|x\d+)\b", re.I),
    "camera_type": re.compile(r"\b(camera|slr|tlr|dslr|rangefinder|compact)\b", re.I),
    "model_hint": re.compile(r"\b(ftn?|nikkormat|ae-1|srt|om-1|om-10|k1000|spotmatic)\b", re.I),
    "working_hint": re.compile(r"\b(shutter working|shutters working)\b", re.I),
}

SEEN_PATH = "seen.json"
UA = "Mozilla/5.0 (compatible; CameraLotMonitor/UK/1.0)"

# =========================
# TELEGRAM
# =========================

def tg_send(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Telegram secrets missing")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": text})


# =========================
# SEEN CACHE
# =========================

def load_seen() -> Set[str]:
    if not os.path.exists(SEEN_PATH):
        return set()
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f).get("seen_ids", []))
    except Exception:
        return set()


def save_seen(seen: Set[str]) -> None:
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"seen_ids": list(seen)[-2000:]}, f)


# =========================
# FILTERS & SCORING
# =========================

def hard_reject(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in BLOCKLIST)


def score_listing(title: str) -> int:
    t = title.lower()

    if hard_reject(t):
        return -999

    score = 0

    # UK positive hints
    for w in UK_POSITIVE_HINTS:
        if w in t:
            score += 1

    # quantity bonus (large lots)
    if re.search(r"\b(5|6|7|8|9|10|\d{2,})\b", t):
        score += 2

    if POSITIVE_PATTERNS["count"].search(t):
        score += 1

    if POSITIVE_PATTERNS["camera_type"].search(t):
        score += 2

    if any(b in t for b in BRANDS):
        score += 2

    if POSITIVE_PATTERNS["model_hint"].search(t):
        score += 2

    if POSITIVE_PATTERNS["working_hint"].search(t):
        score += 1

    return score


# =========================
# EBAY FETCH
# =========================

def fetch_search(url: str) -> List[Dict]:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
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
        link = a.get("href", "").split("?")[0]
        price = price_el.get_text(" ", strip=True)

        if len(title) < 6 or title.lower() == "shop on ebay":
            continue

        items.append({
            "id": link,
            "title": title,
            "price": price,
            "link": link
        })

    return items


# =========================
# MAIN
# =========================

def main():
    seen = load_seen()
    alerts = []

    for url in EBAY_SEARCH_URLS:
        try:
            results = fetch_search(url)
        except Exception as e:
            print("Fetch error:", e)
            continue

        for it in results:
            if it["id"] in seen:
                continue

            seen.add(it["id"])
            s = score_listing(it["title"])

            if s >= 3:
                alerts.append((s, it))

        time.sleep(2)

    save_seen(seen)

    alerts.sort(key=lambda x: x[0], reverse=True)
    alerts = alerts[:5]

    for s, it in alerts:
        msg = (
            f"📸 UK Camera Job Lot (score {s})\n"
            f"{it['title']}\n"
            f"{it['price']}\n"
            f"{it['link']}"
        )
        tg_send(msg)

    print(f"Done. Alerts sent: {len(alerts)}")


if __name__ == "__main__":
    main()
