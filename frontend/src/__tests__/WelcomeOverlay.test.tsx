import { describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";

import WelcomeOverlay from "../components/WelcomeOverlay";

// The overlay is presentational: the show/hide gate lives in AppShell +
// lib/welcome, so these tests pin only what the component itself renders and
// the do-not-break contract that no button here is named exactly "Scan".
describe("WelcomeOverlay", () => {
  it("renders the three-step collector loop", () => {
    const { container } = render(<WelcomeOverlay onDismiss={() => {}} />);

    expect(container.querySelector(".welcome-overlay")).not.toBeNull();
    const text = container.textContent ?? "";
    expect(text).toContain("Welcome to Card Scan");
    expect(text).toContain("Scan a card");
    expect(text).toContain("See its value, grade, and proven sales");
    expect(text).toContain("Find it in your Vault, build your Binder");
  });

  it("dismisses via the primary 'Start scanning' button", () => {
    const onDismiss = vi.fn();
    const { container, getByText } = render(<WelcomeOverlay onDismiss={onDismiss} />);

    fireEvent.click(getByText("Start scanning"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
    // The overlay element is still in this render's container (unmounting is
    // AppShell's job via the flag); we only assert the callback fired.
    expect(container.querySelector(".welcome-overlay")).not.toBeNull();
  });

  it("dismisses via the Skip link too", () => {
    const onDismiss = vi.fn();
    const { getByText } = render(<WelcomeOverlay onDismiss={onDismiss} />);

    fireEvent.click(getByText("Skip"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("never offers a button named exactly 'Scan' (unique-Scan-button contract)", () => {
    const { container } = render(<WelcomeOverlay onDismiss={() => {}} />);

    const scanButtons = [...container.querySelectorAll("button")].filter(
      (b) => (b.textContent ?? "").trim() === "Scan",
    );
    expect(scanButtons).toEqual([]);
    // The primary dismiss is the distinct verb-phrase "Start scanning".
    const startButtons = [...container.querySelectorAll("button")].filter(
      (b) => (b.textContent ?? "").trim() === "Start scanning",
    );
    expect(startButtons).toHaveLength(1);
  });
});