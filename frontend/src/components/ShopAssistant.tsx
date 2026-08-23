import { useState } from "react";

import { getShopAssessment } from "../api/client";
import type { ConsistencyMatch, ShopAssessment } from "../api/types";
import { formatMoney, formatStaleness } from "../lib/format";

// The one-line verdict label per consistency state. Deliberately never claims
// "fake" or "real" — a mismatch is the honest ambiguity (wrong recognition OR
// counterfeit), and the full explanation travels in the server-sourced `note`.
// Mirrors AuthenticityPanel's STATUS_LABEL verbatim so the inlined authenticity
// block reads identically to the Phase 07 panel.
const CONSISTENCY_LABEL: Record<ConsistencyMatch, string> = {
  match: "Printed number matches",
  mismatch: "Printed number mismatch",
  unread: "Could not read the printed number",
  no_card: "No card recognized",
};

// The consistency modifier class — match/mismatch/unread/no_card map to
// ok/warn/dim, NEVER red. A mismatch is "wrong recognition OR counterfeit,
// indistinguishable", so it is a warning, not an alarm.
const CONSISTENCY_CLASS: Record<ConsistencyMatch, string> = {
  match: "ok",
  mismatch: "warn",
  unread: "dim",
  no_card: "dim",
};

/**
 * Phase E — online shopping assistant. Paste an eBay listing URL, get an honest
 * assessment: the listing facts, the catalog match (card / sealed / none), a
 * deal verdict against the sold-comps market median, and (for card matches) the
 * Phase 07 authenticity guide. Read-only — no data/ writes, no new tables.
 *
 * Submit, not debounce: a URL is paste-then-submit, not a keystroke stream. The
 * honest empty states mirror the rest of the app — an em dash / "no recent sold
 * comps" / "set a listings key" / "Couldn't fetch this listing", never a
 * fabricated $0 or a faked listing.
 *
 * The component is unmounted for now (the controller wires it into the tab nav
 * later); it compiles standalone and type-checks.
 */
export default function ShopAssistant() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ShopAssessment | null>(null);
  // Scratchpad: which checklist items the collector has ticked. Never persisted
  // — like AuthenticityPanel, this is a scratchpad for one inspection.
  const [checked, setChecked] = useState<Record<string, boolean>>({});

  async function run(e?: React.FormEvent) {
    e?.preventDefault();
    const u = url.trim();
    if (u.length < 8) {
      setError("Paste a full eBay listing URL.");
      return;
    }
    setLoading(true);
    setError(null);
    setData(null);
    try {
      setData(await getShopAssessment(u));
    } catch {
      setError("Couldn't assess this listing.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="deals shop">
      <form className="deals-toolbar" onSubmit={run}>
        <input
          type="search"
          className="deals-search"
          aria-label="eBay listing URL"
          placeholder="https://www.ebay.com/itm/..."
          autoComplete="off"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <button type="submit" className="sealed-deals-btn" disabled={loading}>
          {loading ? "Assessing…" : "Assess"}
        </button>
      </form>

      {loading && <p className="muted">Assessing this listing…</p>}
      {error && <p className="error">{error}</p>}
      {!loading && !error && !data && (
        <p className="muted">Paste an eBay listing URL to assess it.</p>
      )}

      {data && (
        <>
          {data.listing_unavailable && (
            <p className="muted">
              Set CARDPLATFORM_LISTINGS_API_KEY to assess eBay listings.
            </p>
          )}
          {data.listing_not_found && (
            <p className="muted">Couldn't fetch this listing — check the URL.</p>
          )}

          {data.listing && (
            <div className="deal-card shop-listing">
              {data.listing.image_url && (
                <img
                  src={data.listing.image_url}
                  alt={data.listing.title ?? "listing"}
                />
              )}
              <div className="shop-listing-facts">
                {data.listing.title && (
                  <span className="shop-listing-title">{data.listing.title}</span>
                )}
                <span className="shop-listing-price">
                  {formatMoney(data.listing.price)}
                </span>
                {data.listing.condition && (
                  <span className="shop-listing-condition">
                    {data.listing.condition}
                  </span>
                )}
                {data.listing.seller && (
                  <span className="shop-listing-seller">
                    Seller: {data.listing.seller}
                  </span>
                )}
                {data.listing.listing_type && (
                  <span className="shop-listing-type">
                    {data.listing.listing_type}
                  </span>
                )}
                {data.listing.url && (
                  <a
                    href={data.listing.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    View on eBay
                  </a>
                )}
              </div>
            </div>
          )}

          <p className="shop-match">
            {data.match.kind === "sealed" &&
              `Matched sealed product: ${data.match.sealed_name ?? "—"}`}
            {data.match.kind === "card" &&
              `Matched card: ${data.match.card_name ?? "—"} (${data.match.set_name ?? "—"})`}
            {data.match.kind === "none" &&
              "Couldn't match this listing to the catalog — showing listing facts only."}
          </p>

          {data.deal && (
            <div className="shop-deal">
              <div className="shop-deal-market">
                {data.deal.market_unavailable
                  ? "set a listings key to see the market"
                  : data.deal.market_empty
                    ? "no recent sold comps"
                    : data.deal.market !== null && data.deal.market_source
                      ? `${formatMoney(data.deal.market)} · ${data.deal.market_source} · ${formatStaleness(data.deal.market_source_updated_at)}`
                      : formatMoney(data.deal.market)}
              </div>
              <div
                className={`deal-delta ${data.deal.edge !== null && data.deal.edge >= 0 ? "deal-delta-over" : "deal-delta-under"}`}
              >
                {formatMoney(data.deal.edge)}
              </div>
              <p className="shop-deal-verdict">
                {data.deal.is_deal
                  ? "Below market — looks like a deal"
                  : data.deal.edge !== null && data.deal.edge >= 0
                    ? "At or below market, under the deal threshold"
                    : data.deal.edge !== null && data.deal.edge < 0
                      ? "Above market"
                      : "No market price to compare"}
              </p>
            </div>
          )}

          {data.authenticity && (
            <section className="authenticity-panel">
              <h3 className="authenticity-headline">
                Authenticity check — guide, not a verdict
              </h3>
              <p className="authenticity-caveat muted small">
                {data.authenticity.caveat}
              </p>

              <div
                className={`authenticity-consistency ${CONSISTENCY_CLASS[data.authenticity.consistency.match]}`}
              >
                <span className="consistency-status">
                  {CONSISTENCY_LABEL[data.authenticity.consistency.match]}
                </span>
                <p className="consistency-note">
                  {data.authenticity.consistency.note}
                </p>
              </div>

              <ul className="authenticity-checklist">
                {data.authenticity.checklist.map((item) => (
                  <li
                    key={item.id}
                    className={`checklist-item${item.applies ? "" : " na"}`}
                  >
                    <div className="checklist-head">
                      <span className="checklist-title">{item.title}</span>
                      {!item.applies && (
                        <span className="checklist-na muted small">
                          N/A for this card type
                        </span>
                      )}
                    </div>
                    {item.applies ? (
                      <label className="checklist-row">
                        <input
                          type="checkbox"
                          checked={!!checked[item.id]}
                          onChange={(e) =>
                            setChecked((prev) => ({
                              ...prev,
                              [item.id]: e.target.checked,
                            }))
                          }
                        />
                        <span className="checklist-body">
                          <span className="checklist-what">
                            {item.what_to_check}
                          </span>
                          <span className="checklist-caveat muted small">
                            {item.caveat}
                          </span>
                        </span>
                      </label>
                    ) : (
                      <p className="checklist-what muted small">
                        {item.what_to_check}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <p className="shop-caveat muted small">{data.caveat}</p>
        </>
      )}
    </section>
  );
}