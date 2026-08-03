// Relative time formatter shared by the alerts feed, deal cards, and any
// surface that needs to show how stale a timestamp is without a formatting
// library. Pure function of Date.now() vs the given ISO string. Kept here so
// AlertsFeed's staleness rows and the Deals screen's market/auction staleness
// stay in lockstep. Returns "" for an unparseable date (never "NaNd").
//
// Note: this describes elapsed time in the PAST (e.g. an alert created 3m ago
// or a market price updated 2h ago). For auction countdowns ending in the
// future, use auctionCountdown in Deals.tsx which frames the same magnitude
// as "ends in …" / "ended … ago".
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const m = Math.floor(diff / 60_000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d`;
  // Older than a week → a short locale date; avoids "53d" clutter.
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}