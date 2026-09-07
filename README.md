# Card Scan — a local-first Pokémon card platform

A local-first app for identifying, valuing, and managing a Pokémon card
collection. Scan a card with your camera, get an honest market price backed by
**proven eBay sold comps** (real transactions, not listed estimates), track your
holdings, hunt deals, and share a binder of your best cards — all on your own
machine. Your collection and 105 real reference scans live under `data/` and
never leave the device unless you push the repo yourself.

> **Honest by design.** The app never fabricates a `$0` price. Missing values
> render as an em dash (`—`), every price names its source and staleness, and a
> "grade predictor" is impossible with zero labelled scans — so the grading
> surface is a transparent, user-assisted grade-band calculator instead. Read
> the [honest-price invariants](#honest-price-invariants) before changing price
> code.

## What it does

- **Scan** — camera recognition matches a card to the catalog and surfaces a
  market price with proven eBay sold comps behind it.
- **Vault** — your holdings, market value, cost basis, allocation, top movers,
  value-over-time, price-freshness, acquisition timeline, CSV/JSON export &
  import, and a sold-lot ledger for realized gains.
- **Binder** — a curated, ordered showcase where every slot is backed by a
  *proven* eBay sale; exports as a standalone self-contained HTML page.
- **Sets** — per-set completion checklists with an honest cost-to-finish.
- **Sealed** — sealed-product catalog with honest MSRP, plus live eBay sealed
  listings ranked by flip edge.
- **Deals** — live eBay card listings ranked by flip edge (RIP vs FLIP).
- **Prices / Browse / Catalog / Shop / Wants / Alerts / Ledger** — price lookup
  & history, full catalog browse, sealed catalog, paste-an-EBay-listing deal
  assessor, a want/hunt list, pull-not-push price & restock alerts, and a sealed
  purchase ledger.

Two app modes: **Key** (a curated 7-tab collector loop, the default) and
**Full** (all 15 tabs). Toggle in **More**; the choice persists.

## Stack

- **Frontend:** Vite 8, React 19, TypeScript 5.9, vitest 4, framer-motion.
  Installable PWA (service worker + manifest).
- **Backend:** Python 3.12 FastAPI, SQLite, ONNX + FAISS for recognition.
- **ML:** a local recognition model + FAISS index over 20k card images.

## Quickstart

### Prerequisites

- **Python 3.12** (the project pins `>=3.12,<3.13`; system Python 3.13+ lacks
  the ML wheels). Create a venv from 3.12 specifically.
- **Node 20+** for the frontend.
- **Git.**

### Backend

```bash
cd backend
python3.12 -m venv .venv
# Windows: .venv\Scripts\activate     | macOS/Linux: source .venv/bin/activate
.venv/Scripts/python.exe -m pip install -e .   # or: pip install -e .

# Configure env (see .env.example)
cp ../.env.example ../.env   # then edit .env — at minimum CARDPLATFORM_DATA_DIR

# Run
.venv/Scripts/uvicorn.exe cardplatform.api:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev -- --host --port 5175
```

Open <http://localhost:5175>. For phone testing on the same network, the host
flag serves the build at your machine's LAN address (e.g.
`https://10.0.0.175:5175`).

### Tests

```bash
# Backend (985 tests)
cd backend && .venv/Scripts/python.exe -m pytest

# Frontend (428 tests)
cd frontend && npx vitest run
```

## Configuration

Copy `.env.example` to `.env` and fill in what you have. Everything except
`CARDPLATFORM_DATA_DIR` is optional — the app degrades honestly (an empty /
"not configured" state, never a fabricated value) when a key is absent.

| Variable | Required | Purpose |
|---|---|---|
| `CARDPLATFORM_DATA_DIR` | yes | Path to `data/` (the SQLite db, FAISS index, card images). |
| `CARDPLATFORM_LISTINGS_API_KEY` | no | eBay Finding API key — powers live Deals, Sealed deals, restock alerts, the shop assessor. |
| `CARDPLATFORM_GRADED_PRICE_API_KEY` | no | Graded-price reference for the grading upside surface. |
| `CARDPLATFORM_VAPID_PUBLIC_KEY` | no | Web Push VAPID public key (run `gen-vapid`). |
| `CARDPLATFORM_VAPID_PRIVATE_KEY` | no | Web Push VAPID private key. |
| `CARDPLATFORM_VAPID_SUBJECT` | no | VAPID subject (a `mailto:` URL). |
| `CARDPLATFORM_GOOGLE_SHEET_ID` | no | Google Sheet id for the optional Sheets sync of sealed purchases. |
| `CARDPLATFORM_GOOGLE_SHEET_TAB` | no | Sheet tab name for the sync. |

> Email alerts (`CARDPLATFORM_SMTP_*`) are a reserved channel — the UI surfaces
> the hint, but the backend transport is not yet wired.

## Project layout

```
backend/        FastAPI app, recognition, prices, alerts, sealed, shop
  cardplatform/   the package (api, prices, alerts, sealed, shop, sold, …)
  test/           pytest suite
frontend/       Vite + React app
  src/components/   UI surfaces
  src/lib/          routing, format, app-mode, hooks
  src/__tests__/    vitest suite
data/           NEVER committed — SQLite db, FAISS index, 20k card images, 105 real scans
docs/           roadmap and design notes
site/           the public roadmap site
```

## Honest-price invariants

These are load-bearing. Breaking them silently is a regression:

1. **Never fabricate `$0`.** A missing/unknown price is an em dash `—`, never
   `0` or `$0.00`.
2. **Always surface source + staleness** alongside a price.
3. **Sold comps are proven transactions** (completed eBay sales), not listed
   estimates. The "Proof of sales" toggle shows the actual sales behind a
   median.
4. **Snapshots are immutable** — insert, never update.
5. Use `PriceService.latest_price`, not ad-hoc price reads.
6. `func.lower(col).like(...)` for case-insensitive SQL (no `ilike`).
7. `UtcDateTime` rejects naive datetimes — pass timezone-aware values.

## Do-not-break contract

- `getByRole("button", { name: "Scan" })` must resolve to **exactly one**
  element. New tab labels must not collide with existing nav tabs
  (Home, Scan, Vault, Binder, Wants, Alerts, Deals, Prices, Sealed, Catalog,
  Ledger, Browse, Sets, Shop, More are all taken), and Dashboard CTAs must be
  distinct verb-phrases — never an exact nav-tab name.
- **Literal-before-parametric routing:** every new literal
  `GET/POST /collection/<literal>` route is registered *before*
  `PATCH /collection/{item_id}`.
- **Never delete anything under `data/`.** The 20k card images, the FAISS index,
  and the 105 real reference scans are irreplaceable.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the test workflow, the invariants
above as enforceable rules, and commit conventions.

## License

MIT © 2026 Lucas Bianco. See [LICENSE](LICENSE).