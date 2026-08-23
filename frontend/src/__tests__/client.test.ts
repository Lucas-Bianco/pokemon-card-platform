import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addToCollection,
  confirmScan,
  correctScan,
  getCardLookup,
  getPriceHistory,
  getResolvedPrice,
  getPortfolio,
  getSealedDeals,
  getSealedLedger,
  getSealedProduct,
  getSealedProductMarket,
  getSealedProducts,
  getSealedSoldComps,
  getShopAssessment,
  logSealedFromCatalog,
  logSealedPurchase,
  patchCollectionItem,
  recognize,
  recordScan,
  refreshPrice,
  removeFromCollection,
  syncSealedLedger,
  valuateSealedLedger,
} from "../api/client";
import type { RecognizeResponse, ShopAssessment } from "../api/types";

function mockFetch(status: number, body?: unknown) {
  const spy = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("recognize", () => {
  it("posts multipart to the proxied endpoint", async () => {
    const spy = mockFetch(200, { status: "confident", candidates: [] });

    await recognize(new Blob(["x"]), { rectify: true, variant: "normal" });

    const [url, init] = spy.mock.calls[0];
    expect(url).toContain("/api/recognize");
    expect(url).toContain("rectify=true");
    expect(url).toContain("variant=normal");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("defaults rectify to true", async () => {
    const spy = mockFetch(200, { status: "not_found", candidates: [] });

    await recognize(new Blob(["x"]), {});

    expect(spy.mock.calls[0][0]).toContain("rectify=true");
  });

  it("serialises manual corners as a flat list", async () => {
    const spy = mockFetch(200, { status: "confident", candidates: [] });

    await recognize(new Blob(["x"]), {
      corners: [
        [10, 20],
        [110, 20],
        [110, 160],
        [10, 160],
      ],
    });

    expect(spy.mock.calls[0][0]).toContain("corners=10%2C20%2C110%2C20%2C110%2C160%2C10%2C160");
  });

  it("omits corners when none were placed", async () => {
    const spy = mockFetch(200, { status: "not_found", candidates: [] });

    await recognize(new Blob(["x"]), {});

    expect(spy.mock.calls[0][0]).not.toContain("corners");
  });

  it("throws with the status on failure", async () => {
    mockFetch(500);

    await expect(recognize(new Blob(["x"]), {})).rejects.toThrow(/500/);
  });
});

describe("getResolvedPrice", () => {
  it("returns null on 204 rather than throwing", async () => {
    mockFetch(204);

    expect(await getResolvedPrice("base1-4", "normal")).toBeNull();
  });

  it("returns the price on 200", async () => {
    mockFetch(200, { market: 800.43, source: "tcgplayer", source_updated_at: "2026/07/29" });

    const price = await getResolvedPrice("base1-4", "normal");

    expect(price?.market).toBe(800.43);
  });

  it("throws on a real error", async () => {
    mockFetch(500);

    await expect(getResolvedPrice("base1-4", "normal")).rejects.toThrow(/500/);
  });
});

describe("refreshPrice", () => {
  it("returns null when the source has nothing", async () => {
    mockFetch(204);

    expect(await refreshPrice("base1-58", "normal")).toBeNull();
  });

  it("posts rather than gets", async () => {
    const spy = mockFetch(204);

    await refreshPrice("base1-58", "normal");

    expect(spy.mock.calls[0][1].method).toBe("POST");
  });
});

describe("recordScan", () => {
  const result: RecognizeResponse = {
    status: "confident",
    confidence: 0.97,
    visual_margin: 0.14,
    card: {
      id: "base1-4",
      name: "Charizard",
      number: "4",
      rarity: null,
      set_id: "base1",
      set_name: "Base",
      image_small: null,
      image_large: null,
    },
    price: null,
    candidates: [],
    collector_number_read: "4",
    centering: null,
  };

  it("sends the predicted card and the ocr reading", async () => {
    const spy = mockFetch(201, { id: 7 });

    await recordScan(new Blob(["x"]), result);

    const url = spy.mock.calls[0][0] as string;
    expect(url).toContain("status=confident");
    expect(url).toContain("predicted_card_id=base1-4");
    expect(url).toContain("collector_number_read=4");
  });

  it("omits the card id when nothing was identified", async () => {
    const spy = mockFetch(201, { id: 8 });

    await recordScan(new Blob(["x"]), { ...result, card: null, status: "not_found" });

    expect(spy.mock.calls[0][0]).not.toContain("predicted_card_id");
  });
});

describe("scan feedback", () => {
  it("confirms a scan", async () => {
    const spy = mockFetch(200, { id: 1, confirmed: true });

    await confirmScan(1);

    expect(spy.mock.calls[0][0]).toContain("/api/scans/1/confirm");
  });

  it("sends the corrected card id", async () => {
    const spy = mockFetch(200, { id: 1, corrected_card_id: "base4-4" });

    await correctScan(1, "base4-4");

    expect(spy.mock.calls[0][0]).toContain("card_id=base4-4");
  });
});

describe("addToCollection", () => {
  it("posts json", async () => {
    const spy = mockFetch(201, {});

    await addToCollection("base1-4", "holofoil");

    const [url, init] = spy.mock.calls[0];
    expect(url).toContain("/api/collection");
    expect(JSON.parse(init.body)).toEqual({
      card_id: "base1-4",
      variant: "holofoil",
      quantity: 1,
    });
  });
});

describe("getPortfolio", () => {
  it("calls /api/collection/portfolio", async () => {
    const spy = mockFetch(200, { summary: { allocation: [] }, items: [] });

    await getPortfolio();

    expect(spy.mock.calls[0][0]).toContain("/api/collection/portfolio");
  });
});

describe("patchCollectionItem", () => {
  it("PATCHes /api/collection/{id} with a json body", async () => {
    const spy = mockFetch(200, {
      id: 5,
      card_id: "base1-4",
      card_name: "Charizard",
      variant: "holofoil",
      quantity: 1,
      acquired_price: 42.0,
    });

    await patchCollectionItem(5, { acquired_price: 42.0, notes: "backfill" });

    const [url, init] = spy.mock.calls[0];
    expect(url).toContain("/api/collection/5");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ acquired_price: 42.0, notes: "backfill" });
  });

  it("throws on a non-ok response", async () => {
    mockFetch(404);

    await expect(patchCollectionItem(999, { acquired_price: 1.0 })).rejects.toThrow(/404/);
  });
});

describe("removeFromCollection", () => {
  it("DELETEs /api/collection with card_id, variant, quantity", async () => {
    const spy = mockFetch(204);

    await removeFromCollection("base1-4", "holofoil", 1);

    const [url, init] = spy.mock.calls[0];
    expect(url).toContain("/api/collection?");
    expect(url).toContain("card_id=base1-4");
    expect(url).toContain("variant=holofoil");
    expect(url).toContain("quantity=1");
    expect(init.method).toBe("DELETE");
  });
});

describe("getPriceHistory", () => {
  it("calls /api/cards/{id}/prices/history?variant=&days=", async () => {
    const spy = mockFetch(200, { card_id: "base1-4", variant: "holofoil", points: [] });

    await getPriceHistory("base1-4", "holofoil", 30);

    const url = spy.mock.calls[0][0] as string;
    expect(url).toContain("/api/cards/base1-4/prices/history");
    expect(url).toContain("variant=holofoil");
    expect(url).toContain("days=30");
  });

  it("omits days when not given", async () => {
    const spy = mockFetch(200, { card_id: "base1-4", variant: "holofoil", points: [] });

    await getPriceHistory("base1-4", "holofoil");

    expect(spy.mock.calls[0][0]).not.toContain("days");
  });

  it("returns the points array on 200", async () => {
    mockFetch(200, {
      card_id: "base1-4",
      variant: "holofoil",
      points: [
        {
          fetched_at: "2026-07-29T12:00:00Z",
          source: "tcgplayer",
          variant: "holofoil",
          market: 100.0,
          source_updated_at: "2026/07/29",
        },
      ],
    });

    const history = await getPriceHistory("base1-4", "holofoil");

    expect(history.points).toHaveLength(1);
    expect(history.points[0].market).toBe(100.0);
  });
});

describe("getSealedDeals", () => {
  it("calls /api/sealed/deals?q=&limit=", async () => {
    const spy = mockFetch(200, {
      query: "scarlet violet booster box",
      limit: 20,
      listings_unavailable: false,
      listings_empty: false,
      comps_unavailable: false,
      comps_empty: false,
      sealed_market: null,
      deals: [],
      thresholds: { sealed_flip_min_abs: 20.0, sealed_flip_min_pct: 0.05 },
    });

    await getSealedDeals("scarlet violet booster box", 20);

    const url = spy.mock.calls[0][0] as string;
    expect(url).toContain("/api/sealed/deals");
    expect(url).toContain("q=scarlet+violet+booster+box");
    expect(url).toContain("limit=20");
  });

  it("defaults limit to 20", async () => {
    const spy = mockFetch(200, {
      query: "box",
      limit: 20,
      listings_unavailable: false,
      listings_empty: false,
      comps_unavailable: false,
      comps_empty: false,
      sealed_market: null,
      deals: [],
      thresholds: { sealed_flip_min_abs: 20.0, sealed_flip_min_pct: 0.05 },
    });

    await getSealedDeals("box");

    const url = spy.mock.calls[0][0] as string;
    expect(url).toContain("limit=20");
  });

  it("throws with the backend detail on 422", async () => {
    mockFetch(422, { detail: "query must be at least 2 non-space chars" });

    await expect(getSealedDeals("  ")).rejects.toThrow(
      /query must be at least 2 non-space chars/,
    );
  });

  it("returns the sealed deals response on 200", async () => {
    mockFetch(200, {
      query: "box",
      limit: 20,
      listings_unavailable: false,
      listings_empty: false,
      comps_unavailable: false,
      comps_empty: false,
      sealed_market: { price: 120.0, source: "ebay", source_updated_at: null },
      deals: [
        {
          query: "box",
          listing_id: "1",
          title: "Booster Box",
          listing_price: 95.0,
          currency: "USD",
          url: "https://ebay/1",
          condition: "New",
          listing_type: "fixed_price",
          auction_end_at: null,
          fetched_at: "2026-08-19T00:00:00Z",
          sealed_market: { price: 120.0, source: "ebay", source_updated_at: null },
          flip_edge: 25.0,
          deal_score: 25.0,
          is_flip: true,
        },
      ],
      thresholds: { sealed_flip_min_abs: 20.0, sealed_flip_min_pct: 0.05 },
    });

    const res = await getSealedDeals("box");

    expect(res.deals).toHaveLength(1);
    expect(res.deals[0].flip_edge).toBe(25.0);
    expect(res.sealed_market?.price).toBe(120.0);
  });
});

describe("getSealedSoldComps", () => {
  const soldCompsBody = {
    query: "scarlet violet booster box",
    limit: 6,
    sold_comps: [
      {
        query: "scarlet violet booster box",
        listing_id: "a",
        price: 118.0,
        title: "Scarlet & Violet Booster Box",
        currency: "USD",
        url: "https://ebay/itm/a",
        condition: "New",
        sold_at: "2026-07-30T18:30:00Z",
        source: "ebay",
      },
    ],
    sold_comps_unavailable: false,
    sold_comps_empty: false,
  };

  it("calls /api/sealed/sold-comps?q=&limit=", async () => {
    const spy = mockFetch(200, soldCompsBody);
    await getSealedSoldComps("scarlet violet booster box", 6);
    const url = spy.mock.calls[0][0] as string;
    expect(url).toContain("/api/sealed/sold-comps");
    expect(url).toContain("q=scarlet+violet+booster+box");
    expect(url).toContain("limit=6");
  });

  it("defaults limit to 6", async () => {
    const spy = mockFetch(200, { ...soldCompsBody, limit: 6 });
    await getSealedSoldComps("box");
    const url = spy.mock.calls[0][0] as string;
    expect(url).toContain("limit=6");
  });

  it("throws with the backend detail on 422", async () => {
    mockFetch(422, { detail: "query must be at least 2 non-space chars" });
    await expect(getSealedSoldComps("  ")).rejects.toThrow(
      /query must be at least 2 non-space chars/,
    );
  });

  it("returns the sold comps on 200", async () => {
    mockFetch(200, soldCompsBody);
    const res = await getSealedSoldComps("scarlet violet booster box");
    expect(res.sold_comps).toHaveLength(1);
    expect(res.sold_comps[0].price).toBe(118.0);
    expect(res.sold_comps[0].url).toBe("https://ebay/itm/a");
    expect(res.sold_comps_unavailable).toBe(false);
  });
});

describe("getSealedProducts", () => {
  const body = {
    products: [
      {
        slug: "base-booster-pack",
        name: "Base Set Booster Pack",
        era: "Base",
        product_type: "booster_pack",
        msrp: null,
        msrp_currency: "USD",
        print_status: "out_of_print",
        source_url: null,
        image_url: null,
        released_at: "1999-01-09",
        source: "manual",
        created_at: "2026-08-22T00:00:00Z",
      },
    ],
    count: 1,
    product_type: null,
    print_status: null,
  };

  it("calls /api/sealed/products with q/type/status/limit", async () => {
    const spy = mockFetch(200, body);
    await getSealedProducts("booster", "etb", "in_print", 25);
    const url = spy.mock.calls[0][0] as string;
    expect(url).toContain("/api/sealed/products");
    expect(url).toContain("q=booster");
    expect(url).toContain("type=etb");
    expect(url).toContain("status=in_print");
    expect(url).toContain("limit=25");
  });

  it("omits q/type/status when not provided but always sends limit", async () => {
    const spy = mockFetch(200, body);
    await getSealedProducts();
    const url = spy.mock.calls[0][0] as string;
    expect(url).toContain("limit=50");
    expect(url).not.toContain("q=");
    expect(url).not.toContain("type=");
  });

  it("throws with the backend detail on 422 (unknown type)", async () => {
    mockFetch(422, { detail: "type must be one of (...)" });
    await expect(getSealedProducts(undefined, "mega-tin" as never)).rejects.toThrow(
      /type must be one of/,
    );
  });

  it("returns the catalog on 200", async () => {
    mockFetch(200, body);
    const res = await getSealedProducts();
    expect(res.products).toHaveLength(1);
    expect(res.products[0].msrp).toBeNull(); // honest null, never 0
    expect(res.count).toBe(1);
  });
});

describe("getSealedProduct", () => {
  it("calls /api/sealed/products/{slug}", async () => {
    const spy = mockFetch(200, {
      slug: "base-booster-pack",
      name: "Base Set Booster Pack",
      era: "Base",
      product_type: "booster_pack",
      msrp: null,
      msrp_currency: "USD",
      print_status: "out_of_print",
      source_url: null,
      image_url: null,
      released_at: "1999-01-09",
      source: "manual",
      created_at: "2026-08-22T00:00:00Z",
    });
    await getSealedProduct("base-booster-pack");
    expect(String(spy.mock.calls[0][0])).toContain("/api/sealed/products/base-booster-pack");
  });
});

describe("sealed ledger client", () => {
  it("getSealedLedger hits /api/sealed/ledger", async () => {
    const spy = mockFetch(200, { purchases: [], listings_unavailable: false });
    vi.stubGlobal("fetch", spy);
    await getSealedLedger();
    expect(String(spy.mock.calls[0][0])).toContain("/api/sealed/ledger");
    vi.unstubAllGlobals();
  });

  it("logSealedPurchase POSTs JSON to /api/sealed/ledger", async () => {
    const spy = mockFetch(201, { id: 1, query: "x", product_type: null, quantity: 1, cost_per_unit: 1, source: null, listing_url: null, notes: null, bought_at: "", created_at: "" });
    vi.stubGlobal("fetch", spy);
    await logSealedPurchase({ query: "box", cost_per_unit: 10 });
    const call = spy.mock.calls[0];
    expect(String(call[0])).toContain("/api/sealed/ledger");
    expect(call[1]?.method).toBe("POST");
    expect(JSON.parse(call[1]?.body as string).query).toBe("box");
    vi.unstubAllGlobals();
  });

  it("valuateSealedLedger POSTs /api/sealed/ledger/valuate", async () => {
    const spy = mockFetch(200, { valued: 1, skipped_no_comps: 0, skipped_no_key: false });
    vi.stubGlobal("fetch", spy);
    await valuateSealedLedger();
    expect(String(spy.mock.calls[0][0])).toContain("/api/sealed/ledger/valuate");
    expect(spy.mock.calls[0][1]?.method).toBe("POST");
    vi.unstubAllGlobals();
  });

  it("syncSealedLedger POSTs /api/sealed/ledger/sync", async () => {
    const spy = mockFetch(200, { synced: true, rows: 1, reason: null });
    vi.stubGlobal("fetch", spy);
    await syncSealedLedger();
    expect(String(spy.mock.calls[0][0])).toContain("/api/sealed/ledger/sync");
    expect(spy.mock.calls[0][1]?.method).toBe("POST");
    vi.unstubAllGlobals();
  });
});

describe("getSealedProductMarket", () => {
  const body = {
    slug: "scarlet-violet-elite-trainer-box",
    name: "Scarlet & Violet Elite Trainer Box",
    msrp: 39.99,
    msrp_currency: "USD",
    market_median: 40.0,
    market_source: "ebay",
    market_source_updated_at: null,
    sold_comps_count: 3,
    delta: -0.01,
    unavailable: false,
    empty: false,
  };

  it("calls /api/sealed/products/{slug}/market", async () => {
    const spy = mockFetch(200, body);
    await getSealedProductMarket("scarlet-violet-elite-trainer-box");
    expect(String(spy.mock.calls[0][0])).toContain(
      "/api/sealed/products/scarlet-violet-elite-trainer-box/market",
    );
  });

  it("returns the MSRP-vs-market body on 200", async () => {
    mockFetch(200, body);
    const res = await getSealedProductMarket("scarlet-violet-elite-trainer-box");
    expect(res.msrp).toBe(39.99);
    expect(res.market_median).toBe(40.0);
    expect(res.delta).toBe(-0.01);
    expect(res.unavailable).toBe(false);
  });

  it("throws on 404 (unknown slug)", async () => {
    mockFetch(404, { detail: "sealed product not found" });
    await expect(
      getSealedProductMarket("does-not-exist"),
    ).rejects.toThrow(/sealed product not found/);
  });
});

describe("logSealedFromCatalog", () => {
  const echo = {
    id: 7,
    query: "Scarlet & Violet Elite Trainer Box",
    product_type: "etb",
    quantity: 2,
    cost_per_unit: 39.99,
    source: "Pokémon Center",
    listing_url: null,
    notes: null,
    bought_at: "",
    created_at: "",
  };

  it("POSTs JSON to /api/sealed/ledger/from-catalog with the slug + purchase facts", async () => {
    const spy = mockFetch(201, echo);
    await logSealedFromCatalog({
      slug: "scarlet-violet-elite-trainer-box",
      quantity: 2,
      cost_per_unit: 39.99,
      source: "Pokémon Center",
    });
    const call = spy.mock.calls[0];
    expect(String(call[0])).toContain("/api/sealed/ledger/from-catalog");
    expect(call[1]?.method).toBe("POST");
    const sent = JSON.parse(call[1]?.body as string);
    expect(sent.slug).toBe("scarlet-violet-elite-trainer-box");
    expect(sent.quantity).toBe(2);
    expect(sent.cost_per_unit).toBe(39.99);
  });

  it("throws on 404 (unknown slug)", async () => {
    mockFetch(404, { detail: "sealed product not found" });
    await expect(
      logSealedFromCatalog({ slug: "nope", cost_per_unit: 5 }),
    ).rejects.toThrow(/sealed product not found/);
  });

  it("throws on 422 (bad quantity)", async () => {
    mockFetch(422, { detail: "quantity must be >= 1" });
    await expect(
      logSealedFromCatalog({ slug: "x", quantity: 0, cost_per_unit: 5 }),
    ).rejects.toThrow(/quantity must be >= 1/);
  });
});

describe("getCardLookup", () => {
  const body = [
    {
      card_id: "base1-4",
      name: "Charizard",
      set_id: "base1",
      set_name: "Base",
      number: "4",
      rarity: "Rare",
      image_small: null,
      image_large: null,
      market: 350.0,
      source: "tcgplayer",
      source_updated_at: "2026-08-20T00:00:00Z",
    },
  ];

  it("calls /api/cards/lookup with q + limit", async () => {
    const spy = mockFetch(200, body);
    await getCardLookup("char", 20);
    const url = String(spy.mock.calls[0][0]);
    expect(url).toContain("/api/cards/lookup?");
    expect(url).toContain("q=char");
    expect(url).toContain("limit=20");
  });

  it("defaults limit to 20", async () => {
    const spy = mockFetch(200, body);
    await getCardLookup("char");
    expect(String(spy.mock.calls[0][0])).toContain("limit=20");
  });

  it("returns the matches on 200", async () => {
    mockFetch(200, body);
    const res = await getCardLookup("char");
    expect(res).toHaveLength(1);
    expect(res[0].name).toBe("Charizard");
    expect(res[0].market).toBe(350.0);
  });

  it("throws on 422 (short query)", async () => {
    mockFetch(422, { detail: "q must have at least 2 characters" });
    await expect(getCardLookup("x")).rejects.toThrow(
      /at least 2 characters/,
    );
  });
});

describe("getShopAssessment", () => {
  const body: ShopAssessment = {
    url: "https://www.ebay.com/itm/123",
    item_id: "123",
    listing_unavailable: false,
    listing_not_found: false,
    listing: {
      item_id: "123",
      title: "SV Booster Box",
      price: 95.0,
      currency: "USD",
      condition: "New",
      listing_type: "fixed_price",
      auction_end_at: null,
      seller: "power-seller",
      image_url: null,
      url: "https://www.ebay.com/itm/123",
      source: "ebay",
    },
    match: {
      kind: "sealed",
      confidence: "high",
      card_id: null,
      card_name: null,
      card_number: null,
      card_rarity: null,
      set_name: null,
      sealed_slug: "sv-booster-box",
      sealed_name: "Scarlet & Violet Booster Box",
    },
    deal: {
      market: 120.0,
      market_source: "ebay",
      market_source_updated_at: "2026-08-20",
      sold_comps_count: 5,
      edge: -25.0,
      is_deal: false,
      min_abs: 20.0,
      min_pct: 0.05,
      market_unavailable: false,
      market_empty: false,
    },
    authenticity: null,
    caveat: "A guide, not a verdict.",
  };

  it("calls /api/shop/assess with url + limit", async () => {
    const spy = mockFetch(200, body);
    await getShopAssessment("https://www.ebay.com/itm/123", 6);
    const url = String(spy.mock.calls[0][0]);
    expect(url).toContain("/api/shop/assess?");
    expect(url).toContain("url=");
    expect(url).toContain("limit=6");
  });

  it("defaults limit to 6", async () => {
    const spy = mockFetch(200, body);
    await getShopAssessment("https://www.ebay.com/itm/123");
    expect(String(spy.mock.calls[0][0])).toContain("limit=6");
  });

  it("throws with the backend detail on 422 (bad url)", async () => {
    mockFetch(422, { detail: "bad url" });
    await expect(getShopAssessment("not-a-url")).rejects.toThrow(/bad url/);
  });

  it("returns the assessment on 200", async () => {
    mockFetch(200, body);
    const res = await getShopAssessment("https://www.ebay.com/itm/123");
    expect(res.item_id).toBe("123");
    expect(res.match.kind).toBe("sealed");
    expect(res.deal?.market).toBe(120.0);
  });
});
