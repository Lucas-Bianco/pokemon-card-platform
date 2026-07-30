import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addToCollection,
  confirmScan,
  correctScan,
  getResolvedPrice,
  recognize,
  recordScan,
  refreshPrice,
} from "../api/client";
import type { RecognizeResponse } from "../api/types";

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
