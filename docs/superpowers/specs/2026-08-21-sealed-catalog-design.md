# Sealed-product catalog + honest MSRP (Phase A, slice A1) — Design Spec

> Status: design approved 2026-08-21 by the user's roadmap choice ("We should do A") +
> "continue to develop the app" + auto mode. Implements roadmap row 09. Keystone for
> B (scan-to-log picks from catalog), C (MSRP vs market), D (price lookup by name), E.

## Goal

A browsable, searchable catalog of sealed Pokémon products (booster packs, booster
boxes, ETBs, collection boxes, tins, premium bundles — every product that contains
card packs, Base era → newest) with an **honest MSRP** (nullable — "no MSRP", never
$0) and an in-print / out-of-print / unknown tag. This is the foundation the later
sealed features build on.

## The honesty stance (the whole feature)

- **No "magic auto-update."** There is no official Pokémon sealed-product API with
  MSRP + print status. The realistic, honest version is a **curated starter seed**
  (shipped in-repo) plus a **semi-automated sync** from a community source
  (Pokellector / TCGplayer) with manual review — a documented follow-up, NOT claimed
  as auto-update. Claiming otherwise would violate the project's honesty ethos.
- **MSRP only where it exists.** Many sealed products have NO official US MSRP
  (booster boxes aren't sold at a fixed retail price in the US; premiums vary).
  Those rows are `msrp = NULL` → the UI shows "no MSRP", never a fabricated `$0`.
  Where a stable retail price is well-known (booster pack ≈ $4.49, ETB ≈ $39.99,
  some tins), it is included with `source = "manual"` and a caveat that it is an
  approximate retail price, not an official figure where ambiguous.
- **Print status is a best-effort tag** (`in_print` / `out_of_print` / `unknown`),
  never a guarantee — products re-enter print; `unknown` is honest, not a guess.

## Scope (slice A1 — shippable + phone-testable on its own)

### Backend

1. **New `SealedProduct` model** (`db/models.py`) — `sealed_products` table.
   String slug PK (idempotent seeding by natural key, mirrors `CardSet`):
   - `slug` (String PK, e.g. "sv-base-booster-box")
   - `name` (String, indexed) — "Scarlet & Violet Booster Box"
   - `era` (String, indexed) — "Scarlet & Violet" (the set/series umbrella)
   - `product_type` (String, indexed) — `booster_pack` | `booster_box` | `etb` |
     `collection_box` | `tin` | `premium_bundle` | `other`
   - `msrp` (Float, nullable) — honest null, never 0
   - `msrp_currency` (String, default "USD")
   - `print_status` (String, default "unknown") — `in_print` | `out_of_print` | `unknown`
   - `source_url` (String, nullable) — canonical product/source link
   - `image_url` (String, nullable)
   - `released_at` (String, nullable, indexed) — "2023-03-31" (mirrors CardSet.release_date)
   - `source` (String, default "manual") — provenance of the row
   - `created_at` (UtcDateTime, default _utcnow)
   - UniqueConstraint on `slug` (PK already unique; no extra needed). Index on
     `(product_type, print_status)` for filtered browse.

2. **`sealed/catalog_service.py`** — `SealedCatalogService(session)`:
   - `search(query=None, product_type=None, print_status=None, limit=50)` —
     `func.lower(SealedProduct.name).like(...)` (NOT `ilike`, sacred), era also matched;
     no query → newest first (released_at desc nulls last). Filters compose with AND.
     Returns `list[SealedProduct]`.
   - `get(slug)` — raises `LookupError` for unknown (route → 404).
   - `count()` — for the empty-seed check.
   - `ensure_seed(session, products)` — idempotent bulk insert: only INSERTs rows
     whose slug is not already present (skip existing). Pure-ish: caller passes the
     seed list. Does NOT delete or update (never-delete discipline).

3. **`sealed/seed_data.py`** — a curated `SEALED_PRODUCTS` list of dicts (~24 rows
   across eras: Base, Neo, EX, DP, BW, XY, SM, SWSH, SV). MSRP set only where
   well-known; most boxes/premiums are `None` (honest). Ships in-repo (not under
   `data/` — version-controlled source, not user data).

4. **Seed hook** — `_get_database()` in `api.py`: after `create_all()`, call
   `SealedCatalogService(session).ensure_seed(session, SEALED_PRODUCTS)` once iff
   `count() == 0`. Idempotent, cheap (one COUNT per process startup), never deletes.

5. **Wire models** (`sealed/api_models.py`) — `SealedProductOut`
   (`from_attributes=True`, every field, msrp nullable) + `SealedProductsResponse`
   (`products: list[SealedProductOut]`, `count: int`, `product_type: str | None`,
   `print_status: str | None` — echoes the active filters for the UI).

6. **Routes** (`api.py`):
   - `GET /sealed/products?q=&type=&status=&limit=` — `q: str | None` (no
     min_length — empty/None lists newest; whitespace stripped); `type`/`status`
     optional enum-ish (validated against the allowed sets, 422 on unknown);
     `limit: int = Query(50, ge=1, le=200)`. Read-only.
   - `GET /sealed/products/{slug}` — unknown → 404.

### Frontend

7. **Types + client** — `SealedProduct` + `SealedProductsResponse` in `types.ts`;
   `getSealedProducts(q?, type?, status?, limit=50)` + `getSealedProduct(slug)` in
   `client.ts` (mirrors `getSealedDeals`, `expectJsonOrDetail` so 422 surfaces).

8. **`SealedCatalog.tsx`** — search box (debounced) + `product_type` select +
   `print_status` select + a grid/list of product cards: name, era, type chip,
   MSRP (or "no MSRP"), print-status chip (in=green / out=muted / unknown=dim),
   source link (external, `noopener noreferrer`), released year. Honest empty:
   "No products match." / "No products seeded yet." Reuses `.deal-*` glass idiom
   + additive `.sealed-catalog-*` CSS.

9. **Mount** — new top-level **"Catalog"** nav tab (11th) in both bottom-nav +
   desktop sidebar + command palette; `CatalogGlyph` SVG. The bottom-nav already
   has `overflow-x:auto` for many tabs (the 10th-tab follow-up noted this).
   Do-not-break: tab named "Catalog" (never "Scan") so
   `getByRole("button",{name:"Scan"})` still resolves to one element.

### Do-not-break contract
- Additive `.sealed-catalog-*` classes; no existing class/input[name]/aria-label/
  button-name/empty-state string renamed. New tab name "Catalog" distinct from all
  existing nav names. No frozen test string touched. The one-element Scan-button
  invariant preserved. `SealedPurchase.product_type` (free-text) is NOT changed —
  the catalog's `product_type` enum is a new, separate column on a new table.

### Sacred constraints held
- Honest MSRP: nullable, "no MSRP" never `$0`. `func.lower().like()` not `ilike`.
- Read-only browse (no `data/` writes from routes; seed inserts only on empty).
- Never-delete: `ensure_seed` skips existing, never deletes/updates.
- Staleness not applicable (catalog rows are static reference data, no price
  snapshots here — MSRP is a fixed attribute, surfaced as-is with `source`).
- 105-scan baseline untouched (zero recognition/detection code changed).
- No new external API/keys (the seed is in-repo; community sync is a follow-up).

## Tests (TDD)
- **Backend service** (`test_sealed_catalog_service.py`): `ensure_seed` idempotent
  (re-run adds 0), `search` lowercase substring matches, era matches, type+status
  filters compose, no-query → newest first, `get` raises LookupError on unknown.
- **Backend API** (`test_sealed_catalog_api.py`): happy (returns seeded products),
  filter by type, filter by status, unknown type → 422, unknown status → 422,
  empty q → lists all (newest), `{slug}` 404, limit clamp, count echoes filters.
- **Frontend** (`SealedCatalog.test.tsx`): renders products (name/era/MSRP), "no
  MSRP" for null msrp, type filter changes the fetch params, honest empty, source
  link `noopener noreferrer`. Client test: `getSealedProducts` hits
  `/api/sealed/products?q=&type=&status=&limit=`.

## Out of scope (deferred, recorded)
- **Semi-automated sync** from Pokellector/TCGplayer (the honest "auto-update"
  follow-up — a CLI `sync-sealed-catalog <source>` with manual review; NOT magic).
- **MSRP provenance per row** (a `msrp_source` field + citation) — deferred; `source`
  covers row provenance for v1.
- **Image seeding** (image_url left null in the starter seed; populate during sync).
- **B/C/D/E** — B (scan-to-log picks a catalog row by slug), C (MSRP vs eBay market),
  D (card price lookup by name — separate from this sealed catalog), E (shopping
  assistant). Each its own slice.
- **Per-product sold-comps / market price** on the catalog row — the proof-of-sales
  plumbing (`GET /sealed/sold-comps?q=`) already exists; wiring it onto each catalog
  row is a natural follow-up once the catalog exists (deferred to keep A1 focused).

## Build order
1. Backend model + service + seed_data + ensure_seed hook + tests (TDD).
2. Backend wire models + routes + tests.
3. Frontend types + client + test.
4. `SealedCatalog` component + tests.
5. Mount as "Catalog" tab (AppShell nav + palette + glyph) + CSS.
6. Full suite: `pytest -q` + `npm --prefix frontend test -- --run` + build.
7. Commit + push `origin/main`.
8. Run dev server (backend + frontend `--host`) so the user tests on phone.