"""Confirms the number region crop captures the collector number on real cards."""

import io
import sys
import time

import httpx
from PIL import Image

from cardplatform.recognition.ocr import CollectorNumberReader, normalize_collector_number

# Raw regions contain rarity glyphs (star, circle) that a cp1252 console cannot encode.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CARDS = {
    "base1-4": ("https://images.pokemontcg.io/base1/4_hires.png", "4"),
    "hgss4-1": ("https://images.pokemontcg.io/hgss4/1_hires.png", "1"),
    "sv1-1": ("https://images.pokemontcg.io/sv1/1_hires.png", "1"),
    "swsh1-25": ("https://images.pokemontcg.io/swsh1/25_hires.png", "25"),
}

reader = CollectorNumberReader()
hits = 0
for card_id, (url, expected) in CARDS.items():
    raw = httpx.get(url, timeout=30, follow_redirects=True).content
    image = Image.open(io.BytesIO(raw)).convert("RGB").resize((600, 825))
    started = time.perf_counter()
    reading = reader.read(image)
    elapsed = time.perf_counter() - started
    # Compare normalized: modern cards print '001' where the catalog stores '1', and
    # fusion compares normalized values, so that is the basis that matters.
    ok = normalize_collector_number(reading.collector_number) == normalize_collector_number(
        expected
    )
    hits += ok
    print(f"{'OK  ' if ok else 'MISS'} {card_id}: read={reading.collector_number!r} "
          f"total={reading.printed_total!r} expected={expected!r} ({elapsed:.2f}s)")
    print(f"      regions: {reading.raw_regions}")
print(f"\n{hits}/{len(CARDS)} correct")
