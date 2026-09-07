# Contributing to Card Scan

Thanks for digging in. This is a solo local-first project with a strong
"honest price" philosophy and a few load-bearing contracts — read these before
opening a PR. Setup is covered in the [README](README.md); this doc is about
*how* to change things without breaking them.

## Development setup

See the [Quickstart](README.md#quickstart). The two constraints that bite:

- **Python 3.12 only**, via `backend/.venv`. The project pins
  `>=3.12,<3.13`; system Python 3.13+ does not have the ML wheels (ONNX,
  FAISS, opencv). Create the venv from a 3.12 interpreter specifically.
- **Never delete anything under `data/`.** The 20k card images, the FAISS
  index, the SQLite db, and the 105 real reference scans are irreplaceable.
  Tests rely on the 105-scan baseline staying intact.

## Test workflow

Run both suites before committing:

```bash
# Backend (985 tests)
cd backend && .venv/Scripts/python.exe -m pytest

# Frontend (428 tests)
cd frontend && npx vitest run            # watch: npx vitest
cd frontend && npx tsc --noEmit          # typecheck
cd frontend && npx vite build            # production build must stay clean
```

House test style (frontend): `container.querySelector` + `getByText` /
`screen.getByRole`, `.toBeTruthy()`; stub global `fetch` with
`vi.stubGlobal("fetch", spy)` routed by URL substring; `expectJson<T>` throws
on non-ok. `vitest.setup.ts` clears `localStorage` and resets the URL before
each test. Component tests live in `frontend/src/__tests__/` (lib tests too —
not under `src/lib/__tests__`).

## Honest-price invariants (enforceable)

A PR that silently breaks any of these is a regression, even if tests pass:

1. **Never fabricate `$0`.** Missing/unknown price → em dash `—`, never `0` or
   `$0.00`. Empty collections render an empty state, not a block of zeros.
2. **Always surface price `source` + staleness** next to the number.
3. **Sold comps are proven transactions** (completed eBay sales), never listed
   estimates. The "Proof of sales" toggle must show the actual sales behind a
   median.
4. **Snapshots are immutable** — insert, never update.
5. Use `PriceService.latest_price`, not ad-hoc price reads.
6. `func.lower(col).like(...)` for case-insensitive SQL — no `ilike`.
7. `UtcDateTime` rejects naive datetimes; pass timezone-aware values. The `""`
   sentinel coerces to `None` on the wire.

## Do-not-break contract

- **`getByRole("button", { name: "Scan" })` resolves to exactly one element.**
  New tab labels must not collide with existing nav tabs: Home, Scan, Vault,
  Binder, Wants, Alerts, Deals, Prices, Sealed, Catalog, Ledger, Browse, Sets,
  Shop, More are all taken. Dashboard CTAs must be distinct verb-phrases —
  never an exact nav-tab name.
- **Literal-before-parametric routing:** every new literal
  `GET/POST /collection/<literal>` route is registered *before*
  `PATCH /collection/{item_id}`.
- **Frontend price-source labels:** the `sourceLabel` helper leaves unrecognized
  slugs unchanged (preserves case-sensitive test pins) and maps only known
  slugs to friendly labels. The compact `PriceLine` branch deliberately shows
  the raw slug — do not "friendly-ify" it.

## Git conventions

- Commit every meaningful change; small, focused commits beat big ones.
- End commit messages with `Co-Authored-By: Claude <noreply@anthropic.com>` if
  Claude paired on the work.
- If you commit from the Claude Code **Bash** tool specifically, that shell is
  Git Bash (POSIX sh), not PowerShell — use a heredoc for multi-line messages:

  ```bash
  git commit -F - <<'EOF'
  feat(ui): summary line

  Body paragraphs…

  Co-Authored-By: Claude <noreply@anthropic.com>
  EOF
  ```

- After committing, run `git status --short` to confirm the working tree is
  clean — a partial staging that omits touched feature files is a recurring
  footgun.

## Working mode

The standing loop after a major change: run the backend and frontend dev servers
(`--host` so the app is reachable on a phone on the same network), let the user
test, and stop on the next instruction. Don't push without reason, and don't
re-run one-time scaffolding skills mid-stream.