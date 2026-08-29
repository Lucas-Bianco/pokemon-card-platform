// The whole location of this app is three values: which tab is selected, which
// set is open over it, and which card is open over that. That is a flat shell
// with ~10 tabs and two overlay levels — not a nested-route tree — so the
// History API plus `useRoute` covers it and a router dependency would not earn
// its weight.
//
// The scheme is query-based (`/?view=scan`) rather than path-based, for two
// reasons that are specific to this app:
//   1. public/manifest.webmanifest has shipped `/?view=scan` and
//      `/?view=portfolio` shortcuts since the PWA landed. An installed
//      home-screen shortcut keeps the URL it was installed with, so parsing the
//      query form is the only way those keep working.
//   2. Every route is literally `/` with a query string, so no host needs an
//      SPA history-fallback rewrite, and the manifest's `start_url: "/"` and
//      `scope: "/"` stay accurate.

export type TabView =
  | "home"
  | "scan"
  | "vault"
  | "binder"
  | "wants"
  | "alerts"
  | "deals"
  | "prices"
  | "ledger"
  | "sealed"
  | "catalog"
  | "browse"
  | "sets"
  | "shop"
  | "more";

const TAB_VIEWS: readonly TabView[] = [
  "home",
  "scan",
  "vault",
  "binder",
  "wants",
  "alerts",
  "deals",
  "prices",
  "sealed",
  "catalog",
  "ledger",
  "browse",
  "sets",
  "shop",
  "more",
];

// The curated "key" mode nav: the six core collector-loop features plus More
// (which holds every other surface). Order is the collector's loop — capture
// (Scan), own (Vault), show off (Binder), complete (Sets), sealed (Sealed),
// deal-hunt (Deals), then settings + everything-else (More). Key mode still
// renders every view; a non-key view reached via the command palette or a
// deep link is shown with the More tab highlighted, never hidden.
export const KEY_TAB_VIEWS: readonly TabView[] = [
  "scan",
  "vault",
  "binder",
  "sets",
  "sealed",
  "deals",
  "more",
];

// `?view=` spellings that are not the canonical tab id. The manifest's
// Portfolio shortcut points at `?view=portfolio` while the tab is called
// "vault" internally — dropping this alias would land every already-installed
// Portfolio shortcut on Home, which is the exact bug this routing work fixes.
// Aliases are read but never written: parsing normalises them to the tab id.
const VIEW_ALIASES: Record<string, TabView> = {
  portfolio: "vault",
};

export interface Route {
  view: TabView;
  // A set detail open over the tab. Independent of `card` because opening a
  // card from inside a set keeps the set underneath it (sets → set → card),
  // which is the stack AppShell already renders.
  set: string | null;
  card: { cardId: string; variant?: string } | null;
}

export const HOME_ROUTE: Route = { view: "home", set: null, card: null };

function isTabView(value: string): value is TabView {
  return (TAB_VIEWS as readonly string[]).includes(value);
}

// Unknown or missing `?view=` resolves to Home rather than throwing or showing
// an error surface: a mistyped link should land somewhere useful.
export function parseRoute(search: string): Route {
  const params = new URLSearchParams(search);
  const raw = (params.get("view") ?? "").trim().toLowerCase();
  const view = isTabView(raw) ? raw : (VIEW_ALIASES[raw] ?? "home");

  const cardId = params.get("card");
  const variant = params.get("variant");

  return {
    view,
    set: params.get("set") || null,
    card: cardId ? { cardId, ...(variant ? { variant } : {}) } : null,
  };
}

// The canonical query string for a route, including the leading "?" (empty
// string for Home with nothing open, so the canonical Home URL is a bare "/").
// Home is encoded by omitting `view` entirely, so `/?card=base1-4` round-trips
// to a card open over Home.
//
// URLSearchParams handles the percent-encoding, which matters here: real card
// ids include `ex10-!` and `ex10-?`, and an unencoded `?` would truncate the
// query.
export function routeToSearch(route: Route): string {
  const params = new URLSearchParams();
  if (route.view !== "home") params.set("view", route.view);
  if (route.set) params.set("set", route.set);
  if (route.card) {
    params.set("card", route.card.cardId);
    if (route.card.variant) params.set("variant", route.card.variant);
  }
  const search = params.toString();
  return search ? `?${search}` : "";
}
