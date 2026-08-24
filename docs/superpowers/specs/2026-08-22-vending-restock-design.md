# Vending-machine restock tracker — Design Spec

> Status: design 2026-08-22. Roadmap row 18. Decisions taken with the user:
> observations are the user's own logged sightings (local-first, no community
> feed, no social scraping); a detected pattern is **shown**, and arming an
> alert stays a manual one-tap action.

## Goal

Help the owner work out **when a Pokémon vending machine actually restocks**, so
they can be there. Today the app can already alert on a drop — `Watch` supports
`alert_type="drop_time"` with a `subject_label` for non-card subjects (the code's
own example is "a Pokémon Center vending drop"), a `lead_time_min` reminder, and
a fire-then-stop sequence. What is missing is the half that works out *what time
to put in*: today the user must already know it and type it by hand.

## The honesty stance (read this before designing anything else)

**There is no API for vending-machine restocks.** They are irregular,
location-specific, and crowd-reported. Any design that produces a restock time
from nothing would be exactly the confidently-wrong output this project refuses
in recognition, grading, and counterfeit detection.

So this feature does what the grading-label and counterfeit-label work does:
**record what actually happened, describe the pattern in that record, and stay
silent until there is enough of it.**

Three rules follow, and they are the feature:

1. **Never a point in time. Always a window.** The output is
   "the last 6 restocks were Tuesdays between 08:40 and 11:10", never
   "restocks at 09:30". This mirrors "centering allows up to PSA 9" and
   "a spread, not a prediction".
2. **Always show `n`.** Every readout states how many sightings it rests on.
   A pattern from 4 sightings must not look like a pattern from 40.
3. **Below the threshold, say so and stop.** `insufficient_data` is a
   first-class state, exactly like `sold_comps_unavailable`. It is not an error
   and it is never padded with a guess.

### The tension worth naming

Everything this project has shipped so far is a *measurement* (centering is a
distance) or an *observation* (a sold comp is a completed sale). This is the
first thing that points at the future, and that is a genuine departure. The
mitigations are the three rules above plus one more: **the raw sightings are
always one tap away**, so the user can overrule the summary with their own eyes.
If that is not enough, the feature should ship as a plain log with no inference
at all rather than soften the rules.

### Interval censoring — the modelling detail that makes this honest

A sighting of "restocked" does not mean the restock happened *then*. It means it
happened at some point between the previous "empty" sighting and this one. So a
restock is not a timestamp — it is an interval `[last_empty_at, observed_at]`.

This matters: a user who checks once a week will otherwise "learn" that restocks
happen on the day they happen to shop. Recording `empty` sightings as well as
`restocked` ones is what bounds the estimate, and the width of that bound is
carried into the reported window rather than being quietly discarded.

**Consequence for the UI:** logging "still empty" must be as easy as logging
"restocked", and the copy must explain why a negative sighting is worth logging.

## Scope

### Backend

1. **`vending_machines`** (user-editable) — `id`, `label` ("Westfield L2, by
   the food court"), `place_note`, `machine_type`
   (`pokemon_center` | `tcg_pack` | `other`), `active` (default True),
   `created_at`. No geocoding, no map, no external lookup.

2. **`restock_sightings`** (append-only, immutable — same discipline as
   `PriceSnapshot`) — `id`, `machine_id` FK, `observed_at` (tz-aware,
   `UtcDateTime`), `state` (`restocked` | `stocked` | `empty`), `note`,
   `created_at`. Insert, never update; a mistaken sighting is deleted, not
   edited, so the log stays a record of what was seen.

3. **`vending/pattern.py` — `RestockPatternService`** (read-only, computes on
   demand, writes nothing; mirrors `DealEngine`):

   - `restock_events(machine_id)` — walk the sightings oldest-first and emit one
     event per `empty → restocked` transition, each carrying its censoring
     bound `[last_empty_at, observed_at]`.
   - `pattern(machine_id) -> RestockPattern` — a frozen dataclass:
     - `sightings: int`, `restocks: int`
     - `kind: "weekly" | "interval" | None`
     - `window: (start, end) | None` — the next expected window, or None
     - `confidence: "high" | "medium" | "low"`
     - `basis: str` — the sentence the UI shows verbatim
       ("6 of 6 restocks fell on a Tuesday, 08:40–11:10")
     - `insufficient_data: bool`, `no_pattern: bool`
     - `caveats: list[str]`

   Two candidate patterns are computed and the better-supported one is
   reported; **when they disagree the service says so rather than picking**:

   - **Weekly** — day-of-week concentration plus an hour band. Reported only
     when a clear majority of restocks share a weekday and the hour band is
     narrower than the day.
   - **Interval** — median gap between restocks, with the IQR as the window
     width. Reported when gaps are consistent regardless of weekday.

   Honest gates, stated as starting points because **there is no data to
   calibrate them against yet** (the same footing as `_MIN_OCR_CONFIDENCE`,
   which is calibrated on 39 samples and documented as such):
   - `restocks < 3` → `insufficient_data`, with "log N more sightings" in the
     basis line.
   - window wider than the median gap → `no_pattern` (a window that wide
     carries no information).
   - censoring bounds wider than the reported window → `confidence: "low"`
     and a caveat naming it.

4. **Routes** (all read-only except the two writes):
   - `GET /vending/machines`, `POST /vending/machines`,
     `PATCH /vending/machines/{id}` (label/active), `DELETE /vending/machines/{id}`
   - `POST /vending/machines/{id}/sightings` — log one sighting
   - `GET /vending/machines/{id}/sightings` — the raw log, newest first
   - `GET /vending/machines/{id}/pattern` — the `RestockPattern` above
   - `DELETE /vending/sightings/{id}` — remove a mis-logged sighting

5. **CLI** — `log-sighting --machine <id> --state restocked`,
   `list-machines`, `show-pattern <machine-id>`. Keeps parity with the other
   surfaces and makes the feature testable without the UI.

### Frontend

6. **`Machines.tsx`** — a sub-tab under **Money** in the reorganised navigation
   (it is about getting product, and it is not a card). List of machines, each
   showing its pattern line and last sighting. Honest empty: "No machines yet."

7. **`MachineDetail.tsx`** — the pattern readout (window, `n`, basis sentence,
   confidence pill reusing `--ok`/`--warn`/`--down`), the caveat list, two large
   log buttons — **"Restocked"** and **"Still empty"** — given equal weight, and
   the raw sighting log beneath, each row deletable.

8. **Arming an alert** — when `window` is non-null, a single
   **"Remind me before the next one"** button creates a `drop_time` watch with
   `subject_label` = the machine label, `drop_at` = the window start, and a
   default `lead_time_min`. This reuses the existing watch, engine, and
   notification path unchanged — **no new alert type, no engine change.**
   With no window the button is absent, not disabled-with-a-tooltip.

## Do-not-break contract

- New tab name is **"Machines"**, distinct from every existing nav name, so
  `getByRole("button", {name: "Scan"})` still resolves to exactly one element.
- All new CSS classes are `.vending-*` / `.machine-*`; no existing rule renamed.
- No change to `Watch`, `AlertEngine`, `NotificationService`, or any alert type.
  The integration is a caller of the existing `POST /watchlist`.
- New chrome must never render a `$0.00` — `BulkScan.test.tsx` scans the whole
  document body. Nothing here shows money at all, which keeps that trivially true.

## Sacred constraints held

- **Honest empty states** — `insufficient_data` and `no_pattern` are distinct and
  both explained; never a fabricated time, never a point estimate.
- **Sightings are immutable** — insert, never update (delete to correct).
- **Read-only inference** — the pattern service writes nothing and has no table.
- **Uncertainty is surfaced, not hidden** — `n`, the censoring bound, and the
  confidence are all on screen, and the raw log is one tap away.
- **No new external API, no new key.** Nothing leaves the machine.
- Recognition, detection, and the scan baseline are untouched.

## Tests

- **Pattern service:** a clean weekly cadence is detected; a random cadence
  returns `no_pattern`; fewer than 3 restocks returns `insufficient_data`;
  `empty → restocked` transitions are counted once, not per sighting; censoring
  widens the window and drops confidence; weekly and interval disagreeing
  produces the both-shown state, not an arbitrary pick.
- **API:** create/list/patch/delete a machine; log each of the three states;
  unknown machine → 404; pattern on a machine with no sightings →
  `insufficient_data`; deleting a sighting changes the pattern.
- **Frontend:** the empty state; a pattern renders its basis sentence and `n`;
  `insufficient_data` renders the "log N more" line and no window; the arm
  button is absent when `window` is null; both log buttons are present and
  equally weighted.

## Out of scope (recorded, not solved)

- **Community reports** — needs a shared server and breaks local-first. The
  honest version of it would also need trust/abuse handling.
- **Social-feed scraping** — noisy, ToS-risky, and hard to tie to one machine.
  Rejected on the grounds that it would produce confident-wrong times.
- **Auto-arming a watch** — deliberately manual for now; the app should not act
  on an inference this thin.
- **Geolocation / maps / "machines near me"** — no location data leaves the
  device, and none is collected.
- **Stock-level tracking** (how full it is) — sightings are three states only.
- **Calibrating the thresholds.** Cannot be done until real sightings exist.
  Re-check them once any machine has ~20 sightings, and record the result here.

## Build order

1. Schema + `RestockPatternService` + tests (TDD; the censoring logic first).
2. Routes + wire models + tests.
3. CLI parity.
4. Frontend list + detail + logging + tests.
5. Arm-a-watch integration (reuses `POST /watchlist`).
6. Full suite, then update `AI_CONTEXT.md` §2 and `PROJECT.md`.
