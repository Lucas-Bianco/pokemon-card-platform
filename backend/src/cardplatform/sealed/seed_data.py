"""Curated starter seed for the sealed-product catalog (Phase A, roadmap row 09).

HONESTY (read before editing):
- This is a **curated manual seed**, NOT an auto-updating feed. There is no official
  Pokémon sealed-product API with MSRP + print status. The realistic, honest version
  is this starter list + a future **semi-automated sync** from a community source
  (Pokellector / TCGplayer) with manual review — a documented follow-up, never
  claimed as "magic auto-update" (that would violate the project's honesty ethos).
- `msrp` is set ONLY where a stable US retail price is well-known (booster pack ≈
  $4.49, ETB ≈ $39.99, some tins ≈ $24.99). Many products have NO official US MSRP —
  booster boxes are not sold at a fixed retail price in the US, and premium
  collections vary. Those rows are `None` → the UI shows "no MSRP", never `$0`.
  Historical-era packs (Base/Neo/EX…) have no current MSRP → `None`.
- `print_status` is a best-effort tag (`in_print` / `out_of_print` / `unknown`),
  never a guarantee — products re-enter print; `unknown` is honest, not a guess.
- `source="manual"` for every starter row. `source_url`/`image_url` left None here
  (populated during the future community sync).
- `released_at` is the set's release date (mirrors CardSet.release_date), best-effort.

Ships in-repo (version-controlled source) — NOT under `data/` (which is user data the
project never touches). `ensure_seed` inserts these once, idempotently, when the
table is empty; it never deletes or updates.
"""

from __future__ import annotations

from typing import Any

# Each dict mirrors the SealedProduct model columns. Slug is the natural key.
SEALED_PRODUCTS: list[dict[str, Any]] = [
    # --- Base era (1999) ---
    {"slug": "base-booster-pack", "name": "Base Set Booster Pack", "era": "Base",
     "product_type": "booster_pack", "msrp": None, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "1999-01-09", "source": "manual"},
    {"slug": "base-booster-box", "name": "Base Set Booster Box", "era": "Base",
     "product_type": "booster_box", "msrp": None, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "1999-01-09", "source": "manual"},
    {"slug": "jungle-booster-pack", "name": "Jungle Booster Pack", "era": "Jungle",
     "product_type": "booster_pack", "msrp": None, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "1999-06-16", "source": "manual"},
    {"slug": "fossil-booster-pack", "name": "Fossil Booster Pack", "era": "Fossil",
     "product_type": "booster_pack", "msrp": None, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "1999-10-10", "source": "manual"},
    # --- Neo / e-series (2000–2002) ---
    {"slug": "neo-genesis-booster-pack", "name": "Neo Genesis Booster Pack", "era": "Neo",
     "product_type": "booster_pack", "msrp": None, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2000-12-01", "source": "manual"},
    {"slug": "expedition-booster-pack", "name": "Expedition Booster Pack", "era": "e-Card",
     "product_type": "booster_pack", "msrp": None, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2002-09-15", "source": "manual"},
    # --- EX / Diamond & Pearl / BW / XY (2003–2014) ---
    {"slug": "ex-ruby-sapphire-booster-pack", "name": "EX Ruby & Sapphire Booster Pack", "era": "EX",
     "product_type": "booster_pack", "msrp": None, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2003-06-01", "source": "manual"},
    {"slug": "diamond-pearl-booster-pack", "name": "Diamond & Pearl Booster Pack", "era": "Diamond & Pearl",
     "product_type": "booster_pack", "msrp": None, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2007-05-23", "source": "manual"},
    {"slug": "black-white-booster-pack", "name": "Black & White Booster Pack", "era": "Black & White",
     "product_type": "booster_pack", "msrp": None, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2011-04-25", "source": "manual"},
    {"slug": "xy-booster-pack", "name": "XY Booster Pack", "era": "XY",
     "product_type": "booster_pack", "msrp": None, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2014-02-05", "source": "manual"},
    # --- Sun & Moon (2017) ---
    {"slug": "sun-moon-booster-pack", "name": "Sun & Moon Booster Pack", "era": "Sun & Moon",
     "product_type": "booster_pack", "msrp": None, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2017-02-03", "source": "manual"},
    {"slug": "sun-moon-elite-trainer-box", "name": "Sun & Moon Elite Trainer Box", "era": "Sun & Moon",
     "product_type": "etb", "msrp": 39.99, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2017-02-03", "source": "manual"},
    # --- Sword & Shield (2019–2023) ---
    {"slug": "sword-shield-booster-pack", "name": "Sword & Shield Booster Pack", "era": "Sword & Shield",
     "product_type": "booster_pack", "msrp": 4.49, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2019-11-15", "source": "manual"},
    {"slug": "sword-shield-booster-box", "name": "Sword & Shield Booster Box", "era": "Sword & Shield",
     "product_type": "booster_box", "msrp": None, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2019-11-15", "source": "manual"},
    {"slug": "sword-shield-elite-trainer-box", "name": "Sword & Shield Elite Trainer Box", "era": "Sword & Shield",
     "product_type": "etb", "msrp": 39.99, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2019-11-15", "source": "manual"},
    {"slug": "sword-shield-collection-tin", "name": "Sword & Shield Collection Tin", "era": "Sword & Shield",
     "product_type": "tin", "msrp": 24.99, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2020-08-28", "source": "manual"},
    # --- Scarlet & Violet (2023–) ---
    {"slug": "scarlet-violet-booster-pack", "name": "Scarlet & Violet Booster Pack", "era": "Scarlet & Violet",
     "product_type": "booster_pack", "msrp": 4.49, "msrp_currency": "USD",
     "print_status": "in_print", "source_url": None, "image_url": None,
     "released_at": "2023-03-31", "source": "manual"},
    {"slug": "scarlet-violet-booster-box", "name": "Scarlet & Violet Booster Box", "era": "Scarlet & Violet",
     "product_type": "booster_box", "msrp": None, "msrp_currency": "USD",
     "print_status": "in_print", "source_url": None, "image_url": None,
     "released_at": "2023-03-31", "source": "manual"},
    {"slug": "scarlet-violet-elite-trainer-box", "name": "Scarlet & Violet Elite Trainer Box", "era": "Scarlet & Violet",
     "product_type": "etb", "msrp": 39.99, "msrp_currency": "USD",
     "print_status": "in_print", "source_url": None, "image_url": None,
     "released_at": "2023-03-31", "source": "manual"},
    {"slug": "scarlet-violet-premium-collection", "name": "Scarlet & Violet Premium Collection", "era": "Scarlet & Violet",
     "product_type": "premium_bundle", "msrp": None, "msrp_currency": "USD",
     "print_status": "in_print", "source_url": None, "image_url": None,
     "released_at": "2023-08-11", "source": "manual"},
    {"slug": "paldea-evolved-booster-pack", "name": "Paldea Evolved Booster Pack", "era": "Scarlet & Violet",
     "product_type": "booster_pack", "msrp": 4.49, "msrp_currency": "USD",
     "print_status": "in_print", "source_url": None, "image_url": None,
     "released_at": "2023-06-30", "source": "manual"},
    {"slug": "obsidian-flames-booster-box", "name": "Obsidian Flames Booster Box", "era": "Scarlet & Violet",
     "product_type": "booster_box", "msrp": None, "msrp_currency": "USD",
     "print_status": "in_print", "source_url": None, "image_url": None,
     "released_at": "2023-08-11", "source": "manual"},
    {"slug": "pokemon-151-elite-trainer-box", "name": "Pokémon 151 Elite Trainer Box", "era": "Scarlet & Violet",
     "product_type": "etb", "msrp": 39.99, "msrp_currency": "USD",
     "print_status": "out_of_print", "source_url": None, "image_url": None,
     "released_at": "2023-09-22", "source": "manual"},
    {"slug": "temporal-forces-booster-pack", "name": "Temporal Forces Booster Pack", "era": "Scarlet & Violet",
     "product_type": "booster_pack", "msrp": 4.49, "msrp_currency": "USD",
     "print_status": "in_print", "source_url": None, "image_url": None,
     "released_at": "2024-03-22", "source": "manual"},
]