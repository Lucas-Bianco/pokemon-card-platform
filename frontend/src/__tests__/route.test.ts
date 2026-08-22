import { describe, expect, it } from "vitest";

import { HOME_ROUTE, parseRoute, routeToSearch, type Route } from "../lib/route";

describe("parseRoute", () => {
  it("defaults to home when there is no query", () => {
    expect(parseRoute("")).toEqual(HOME_ROUTE);
    expect(parseRoute("?")).toEqual(HOME_ROUTE);
  });

  it("reads a tab from ?view=", () => {
    expect(parseRoute("?view=scan").view).toBe("scan");
    expect(parseRoute("?view=sealed").view).toBe("sealed");
    expect(parseRoute("?view=more").view).toBe("more");
  });

  // The live bug this routing work fixes: the manifest has shipped
  // `/?view=scan` and `/?view=portfolio` shortcuts that nothing read, so both
  // landed on Home.
  it("resolves the manifest's shipped shortcut URLs", () => {
    expect(parseRoute("?view=scan").view).toBe("scan");
    expect(parseRoute("?view=portfolio").view).toBe("vault");
  });

  it("falls back to home for an unknown or empty view", () => {
    expect(parseRoute("?view=nonsense").view).toBe("home");
    expect(parseRoute("?view=").view).toBe("home");
  });

  it("is case- and whitespace-insensitive on the view", () => {
    expect(parseRoute("?view=SCAN").view).toBe("scan");
    expect(parseRoute("?view=%20Portfolio%20").view).toBe("vault");
  });

  it("reads an open card, with and without a variant", () => {
    expect(parseRoute("?card=base1-4").card).toEqual({ cardId: "base1-4" });
    expect(parseRoute("?card=base1-4&variant=holofoil").card).toEqual({
      cardId: "base1-4",
      variant: "holofoil",
    });
  });

  it("reads an open set", () => {
    expect(parseRoute("?view=sets&set=base1").set).toBe("base1");
  });

  // Opening a card from inside a set keeps the set underneath it, so both can
  // be present at once and unwind one layer at a time.
  it("keeps the set and the card independent", () => {
    const route = parseRoute("?view=sets&set=base1&card=base1-4");
    expect(route.view).toBe("sets");
    expect(route.set).toBe("base1");
    expect(route.card).toEqual({ cardId: "base1-4" });
  });

  it("treats an empty card or set param as nothing open", () => {
    expect(parseRoute("?card=").card).toBeNull();
    expect(parseRoute("?set=").set).toBeNull();
  });
});

describe("routeToSearch", () => {
  it("encodes home with nothing open as a bare path", () => {
    expect(routeToSearch(HOME_ROUTE)).toBe("");
  });

  it("encodes a tab", () => {
    expect(routeToSearch({ view: "scan", set: null, card: null })).toBe("?view=scan");
  });

  it("normalises the portfolio alias to the canonical tab id", () => {
    expect(routeToSearch(parseRoute("?view=portfolio"))).toBe("?view=vault");
  });

  it("encodes a card over a tab, and a card over a set", () => {
    expect(
      routeToSearch({ view: "vault", set: null, card: { cardId: "base1-4" } }),
    ).toBe("?view=vault&card=base1-4");
    expect(
      routeToSearch({ view: "sets", set: "base1", card: { cardId: "base1-4" } }),
    ).toBe("?view=sets&set=base1&card=base1-4");
  });

  it("omits the variant when there is none", () => {
    expect(routeToSearch({ view: "home", set: null, card: { cardId: "base1-4" } })).toBe(
      "?card=base1-4",
    );
  });
});

describe("route round-tripping", () => {
  const cases: Route[] = [
    HOME_ROUTE,
    { view: "scan", set: null, card: null },
    { view: "vault", set: null, card: null },
    { view: "home", set: null, card: { cardId: "base1-4" } },
    { view: "alerts", set: null, card: { cardId: "base1-4", variant: "reverseHolofoil" } },
    { view: "sets", set: "base1", card: null },
    { view: "sets", set: "base1", card: { cardId: "base1-4" } },
  ];

  it.each(cases)("survives serialise → parse: %j", (route) => {
    expect(parseRoute(routeToSearch(route))).toEqual(route);
  });

  // Two real catalog ids are `ex10-!` and `ex10-?`. An unencoded `?` would
  // truncate the query string and silently open the wrong card (or none).
  it.each(["ex10-!", "ex10-?", "sv3pt5-1", "base1-4"])(
    "round-trips the awkward card id %s",
    (cardId) => {
      const search = routeToSearch({ view: "browse", set: null, card: { cardId } });
      expect(parseRoute(search).card).toEqual({ cardId });
    },
  );
});
