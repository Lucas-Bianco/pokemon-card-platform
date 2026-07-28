# Project: Technology + Trading Cards (Pokémon)

**Owner:** Lucas
**Started:** 2026-07-28
**Status:** Brainstorming / idea selection

## Vision

An app/site at the intersection of **technology and trading cards — primarily Pokémon**.
The bar: something *novel* (nobody has built it, or existing tools do it poorly) that is also
*fun* and *technically ambitious* — a deliberate excuse to work with AI, computer vision / photo
recognition, and techniques not tried before.

Background: this succeeds the ForexAI scanner work. FX turned out to be an efficient market with
no findable short-horizon edge. Collectibles are the opposite — an **inefficient** market where a
real edge exists (mispriced listings, grading arbitrage, EV on sealed product). The market-scanner
instincts transfer; the market is finally one where they can win.

## Guiding principles

- Novel or 10x better than what exists — not another basic price-lookup app.
- Lean into hard tech: computer vision, ML, AI decisioning.
- Start with ONE sharp idea, scoped to ship; expand later.
- "Is this a good deal vs. real market value?" is connective tissue that could later extend to
  Lucas's other hobbies (3D printer parts, PC/electronics, camera gear).

## Candidate ideas (under discussion — not yet chosen)

> These are the shortlist being brainstormed. See conversation for full detail; this list will be
> pruned to a single starter project, which then gets its own design spec.

1. **Grade Predictor / Pre-grade scanner** — photograph a raw card; CV scores centering, corners,
   edges, surface, then predicts a PSA/CGC grade *and* the EV of grading (cost vs. value uplift).
   Answers "should I grade this?" — a real money question.
2. **Bulk photo cataloger** — fan out cards or scan a binder page; detect + identify *every* card
   in one shot (set, number, holo/reverse, edition), auto-value the whole collection, track over time.
3. **Deal / arbitrage sniper** — monitor marketplace + local listings vs. sold comps; alert on
   underpriced listings and raw-vs-graded arbitrage. (ForexAI reborn for an inefficient market.)
4. **Counterfeit / fake detector** — CV on holo pattern, texture, print rosette, edges to flag fakes.
5. **Sealed EV / "rip vs. flip" calculator** — expected value of opening a product vs. its sealed
   market price, using pull rates + live singles prices.
6. **Set-completion optimizer** — cheapest path to finishing a target set across marketplaces
   (a traveling-purchaser / shopping-cart optimization problem).
7. **Collection portfolio tracker** — treat the collection like a stock portfolio: cost basis, P/L,
   price history, alerts. Extensible to other hobbies later.

## Next step

Pick 1 starter idea → write design spec in `docs/superpowers/specs/` → implementation plan.
