import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CommandPalette } from "../components/CommandPalette";

afterEach(() => vi.unstubAllGlobals());

function stubCards(cards: { id: string; name: string; set_name: string }[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async (url: string) => {
      if (String(url).includes("/cards?")) {
        return { ok: true, status: 200, json: async () => cards };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    }),
  );
}

describe("CommandPalette", () => {
  it("shows tab commands when open with no query", () => {
    render(<CommandPalette open={true} onClose={() => {}} onNavigate={() => {}} onSelectCard={() => {}} />);
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeDefined();
    expect(screen.getByText("Go to Scan")).toBeDefined();
  });

  it("navigates to a tab on command click", () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    render(<CommandPalette open={true} onClose={onClose} onNavigate={onNavigate} onSelectCard={() => {}} />);
    fireEvent.click(screen.getByText("Go to Vault"));
    expect(onNavigate).toHaveBeenCalledWith("vault");
    expect(onClose).toHaveBeenCalled();
  });

  it("searches cards and opens a result", async () => {
    stubCards([{ id: "base1-4", name: "Charizard", set_name: "Base" }]);
    const onSelectCard = vi.fn();
    const onClose = vi.fn();
    render(<CommandPalette open={true} onClose={onClose} onNavigate={() => {}} onSelectCard={onSelectCard} />);
    fireEvent.change(screen.getByLabelText("Command palette search"), { target: { value: "Char" } });
    await waitFor(() => expect(screen.getByText("Charizard")).toBeDefined());
    fireEvent.click(screen.getByText("Charizard"));
    expect(onSelectCard).toHaveBeenCalledWith("base1-4");
    expect(onClose).toHaveBeenCalled();
  });

  it("shows an honest empty note when search has no results", async () => {
    stubCards([]);
    render(<CommandPalette open={true} onClose={() => {}} onNavigate={() => {}} onSelectCard={() => {}} />);
    fireEvent.change(screen.getByLabelText("Command palette search"), { target: { value: "zzz" } });
    await waitFor(() => expect(screen.getByText("No matching cards.")).toBeDefined());
  });

  it("renders nothing when closed", () => {
    const { container } = render(<CommandPalette open={false} onClose={() => {}} onNavigate={() => {}} onSelectCard={() => {}} />);
    expect(container.querySelector(".palette-overlay")).toBeNull();
  });
});