import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import VaultImport from "../components/VaultImport";

// A fetch router that returns the import report JSON for POST /collection/import
// and captures the request body so tests can assert the format + payload.
function makeFetcher(report: any = { total: 0, added: 0, skipped: [], caveat: "honest" }) {
  const calls: { url: string; method: string; body?: string }[] = [];
  const spy = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body as string | undefined });
    return {
      ok: true,
      status: 200,
      json: async () => report,
      text: async () => "",
    };
  });
  vi.stubGlobal("fetch", spy);
  return { calls };
}

afterEach(() => vi.unstubAllGlobals());

describe("VaultImport", () => {
  it("renders the honest note (preserves date, skips reported, never $0)", () => {
    makeFetcher();
    render(<VaultImport />);
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/import into your vault/i);
    expect(text).toMatch(/never \$0/i);
    expect(text).toMatch(/purchase date is preserved/i);
  });

  it("imports a chosen CSV file and renders an all-added report", async () => {
    const { calls } = makeFetcher({ total: 2, added: 2, skipped: [], caveat: "honest" });
    render(<VaultImport />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["card_id,quantity\nbase1-4,1\n"], "vault.csv", { type: "text/csv" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => {
      expect(document.body.textContent ?? "").toContain("Imported 2 of 2 rows");
    });
    expect(document.body.textContent ?? "").toContain("no skips");
    // POSTed to the import route with format=csv and the file body.
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toContain("/collection/import?format=csv");
    expect(post.body).toContain("card_id,quantity");
    expect(post.body).toContain("base1-4");
  });

  it("imports a .json file using the json format", async () => {
    const { calls } = makeFetcher({ total: 1, added: 1, skipped: [], caveat: "honest" });
    render(<VaultImport />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['{"items":[{"card_id":"base1-4"}]}', ""], "vault.json", {
      type: "application/json",
    });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => {
      expect(document.body.textContent ?? "").toContain("Imported 1 of 1 row");
    });
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toContain("/collection/import?format=json");
    expect(post.body).toContain('"items"');
  });

  it("lists every skipped row with its honest reason — never a silent drop", async () => {
    makeFetcher({
      total: 3,
      added: 1,
      skipped: [
        { row_number: 2, card_id: "nope", reason: "unknown card: nope" },
        { row_number: 3, card_id: null, reason: "missing card id" },
      ],
      caveat: "honest skips",
    });
    render(<VaultImport />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "vault.csv", { type: "text/csv" })] },
    });
    await waitFor(() => {
      expect(document.body.textContent ?? "").toContain("Imported 1 of 3 rows");
    });
    const text = document.body.textContent ?? "";
    expect(text).toContain("2 skipped");
    expect(text).toContain("unknown card: nope");
    expect(text).toContain("missing card id");
    // The skip table has a row per skip.
    expect(document.querySelectorAll(".import-skip-table tbody tr").length).toBe(2);
  });

  it("imports via the paste form with the chosen format", async () => {
    const { calls } = makeFetcher({ total: 1, added: 1, skipped: [], caveat: "honest" });
    render(<VaultImport />);
    // Open the paste form.
    fireEvent.click(document.querySelector(".vault-import-paste summary")!);
    const textarea = document.querySelector('textarea[aria-label="Paste body"]') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '{"items":[]}' } });
    const select = document.querySelector('select[aria-label="Format"]') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "json" } });
    const submit = [...document.querySelectorAll("button")].find((b) =>
      /import pasted body/i.test(b.textContent ?? ""),
    )!;
    fireEvent.click(submit);
    await waitFor(() => {
      expect(document.body.textContent ?? "").toContain("Imported 1 of 1 row");
    });
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toContain("/collection/import?format=json");
    expect(post.body).toBe('{"items":[]}');
  });

  it("rejects an empty paste with an honest error (no POST)", async () => {
    const { calls } = makeFetcher();
    render(<VaultImport />);
    fireEvent.click(document.querySelector(".vault-import-paste summary")!);
    const submit = [...document.querySelectorAll("button")].find((b) =>
      /import pasted body/i.test(b.textContent ?? ""),
    )!;
    fireEvent.click(submit);
    await waitFor(() => {
      expect(document.body.textContent ?? "").toMatch(/paste a csv or json body/i);
    });
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows the server's error message on a failed import (never a silent failure)", async () => {
    const spy = vi.fn().mockImplementation(async () => ({
      ok: false,
      status: 400,
      json: async () => ({}),
      text: async () => "",
    }));
    vi.stubGlobal("fetch", spy);
    render(<VaultImport />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "vault.csv", { type: "text/csv" })] },
    });
    await waitFor(() => {
      expect(document.body.textContent ?? "").toContain("request failed: 400");
    });
    expect(document.querySelector(".error")).not.toBeNull();
  });
});