import json
import os
import re
import time
from typing import List, Dict, Set, Optional
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlencode

# ============================================================
# EBAY UK FILTERS (important):
# - _sacat=625 => Cameras & Photography category
# - LH_Lots=1  => Listed as lots
# - LH_PrefLoc=2 => Worldwide item location
# - LH_AvailTo=3 => Available to United Kingdom
# - LH_BIN=1 => Buy It Now only (optional; keeps it simpler)
# ============================================================

EBAY_BASE = "https://www.ebay.co.uk/sch/i.html"

# Căutări eficiente (loturi mici + mari, toate tipurile de camere)
SEARCH_TERMS = [
    "camera job lot",
    "digital camera job lot",
    "film camera job lot",
    "compact camera job lot",
    "dslr camera job lot",
    "slr camera job lot",
    "vintage camera job lot",
    "camera collection job lot",
    "huge camera job lot",
    "large camera job lot",
    "bulk cameras lot",
]

# Categorii:
# 625 = Cameras & Photography
# 45089 = Camera Mixed Lots (Wholesale & Job Lots > Cameras)
CATEGORIES = [625, 45089]

# Dacă vrei să prinzi și licitații, pune False
BUY_IT_NOW_ONLY = True

# =========================
# BLOCKLIST (REAL JUNK ONLY)
# =========================
# IMPORTANT: NU blocăm "untested", "job lot", "for parts", "as is", "read description", "mixed lot"
# Blocăm doar ce e aproape sigur junk.
BLOCKLIST = [
    "junk",
    "spares",
    "broken",
    "repair",
    "parts only",
    "accessories only",
    "for spares",
]

# =========================
# BRANDS (COMPACT + DSLR + FILM + INSTANT)
# =========================
BRANDS = [
    "nikon", "canon", "olympus", "pentax", "konica", "minolta",
    "sony", "panasonic", "fujifilm", "ricoh", "casio", "kodak",
    "samsung", "jvc", "toshiba", "vivitar", "polaroid"
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
    "digital cameras",
    "camera collection",
    "collection of cameras",
    "mixed cameras",
]

BIG_LOT_HINTS = [
    "huge lot",
    "huge camera lot",
    "massive lot",
    "massive camera lot",
    "large lot",
    "large camera lot",
    "big lot",
    "big camera lot",
    "bulk lot",
    "bulk cameras",
    "bundle",
    "bundle of cameras",
    "box of cameras",
    "crate of cameras",
    "bag of cameras",
]

# =========================
# WORD-NUMBERS (seventy cameras etc.)
# =========================
WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "hundreds": 100,
}

SEEN_PATH = "seen.json"
UA = "Mozilla/5.0 (compatible; CameraLotMonitor/UK/2.0)"

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
    r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=20)
    if r.status_code != 200:
        print("Telegram error:", r.status_code, r.text)

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
        json.dump({"seen_ids": list(seen)[-2500:]}, f)

# =========================
# HELPERS
# =========================
def hard_reject(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in BLOCKLIST)

def extract_quantity(title: str) -> Optional[int]:
    t = title.lower()

    # 1) "30 cameras"
    m = re.search(r"\b(\d{1,4})\s*(?:x\s*)?(?:camera|cameras|camcorder|camcorders)\b", t)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass

    # 2) "lot of 70"
    m = re.search(r"\b(?:lot|job lot|joblot|bundle|box|crate|bag)\s+of\s+(\d{1,4})\b", t)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass

    # 3) "seventy cameras"
    for w, val in WORD_NUMBERS.items():
        if re.search(rf"\b{re.escape(w)}\s+(?:camera|cameras|camcorder|camcorders)\b", t):
            return val

    # 4) "one hundred cameras"
    if re.search(r"\bone\s+hundred\s+(?:camera|cameras|camcorder|camcorders)\b", t):
        return 100

    return None

def score_listing(title: str) -> int:
    t = title.lower()

    if hard_reject(t):
        return -999

    score = 0

    # UK hints (job lot / untested / clearance)
    for w in UK_POSITIVE_HINTS:
        if w in t:
            score += 1

    # Big lot hints ("huge", "bulk", "box of cameras", "bundle")
    for w in BIG_LOT_HINTS:
        if w in t:
            score += 2

    # Core camera words
    if re.search(r"\b(camera|cameras|compact|dslr|slr|tlr|rangefinder|film|camcorder)\b", t):
        score += 2

    # Brand presence
    if any(b in t for b in BRANDS):
        score += 2

    # Model hints (bonus)
    if re.search(r"\b(ftn?|nikkormat|ae-1|srt|om-1|om-10|k1000|spotmatic)\b", t):
        score += 2

    # Working hints (rare, but great)
    if re.search(r"\b(shutter working|shutters working|tested working|fully working)\b", t):
        score += 2

    # Quantity boosts
    qty = extract_quantity(title)
    if qty is not None:
        score += 2  # any explicit quantity helps
        if qty >= 20:
            score += 3
        if qty >= 50:
            score += 4
        if qty >= 100:
            score += 5

    return score

def build_search_url(term: str, category: int) -> str:
    params = {
        "_nkw": term,
        "_sacat": str(category),
        "LH_Lots": "1",       # listed as lots
        "LH_PrefLoc": "2",    # worldwide
        "LH_AvailTo": "3",    # available to UK
    }
    if BUY_IT_NOW_ONLY:
        params["LH_BIN"] = "1"
    return f"{EBAY_BASE}?{urlencode(params)}"

# =========================
# EBAY FETCH
# =========================
def fetch_search(url: str) -> List[Dict]:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=35)
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

        # remove eBay boilerplate
        if len(title) < 6 or title.lower() in ("shop on ebay", "sponsored"):
            continue

        items.append({"id": link, "title": title, "price": price, "link": link})

    return items

# =========================
# MAIN
# =========================
def main():
    seen = load_seen()
    alerts = []

    urls = []
    for cat in CATEGORIES:
        for term in SEARCH_TERMS:
            urls.append(build_search_url(term, cat))

    for url in urls:
        try:
            results = fetch_search(url)
        except Exception as e:
            print("Fetch error:", url, e)
            continue

        for it in results:
            if it["id"] in seen:
                continue

            seen.add(it["id"])
            s = score_listing(it["title"])

            # prag: 3 (UK job-lot friendly, dar tot selectiv)
            if s >= 3:
                alerts.append((s, it))

        time.sleep(1.5)

    save_seen(seen)

    # top alerts
    alerts.sort(key=lambda x: x[0], reverse=True)
    alerts = alerts[:5]

    for s, it in alerts:
        qty = extract_quantity(it["title"])
        qty_txt = f"Qty: {qty}" if qty is not None else "Qty: unknown"

        msg = (
            f"📸 eBay UK Camera Lot (score {s})\n"
            f"{qty_txt}\n"
            f"{it['title']}\n"
            f"{it['price']}\n"
            f"{it['link']}"
        )
        tg_send(msg)

    print(f"Done. URLs checked: {len(urls)} | Alerts sent: {len(alerts)} | Seen: {len(seen)}")

if __name__ == "__main__":
    main()
