import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";

import InstallCard from "../components/InstallCard";
import type { InstallOutcome } from "../lib/useInstallPrompt";

// InstallCard is props-driven, so each branch is a pure function of its props —
// no browser event plumbing needed here (that lives in useInstallPrompt.test.ts).
describe("InstallCard", () => {
  it("renders nothing when already installed", () => {
    const { container } = render(
      <InstallCard
        canInstall={false}
        iosInstructions={false}
        installed={true}
        onInstall={async () => "accepted"}
      />,
    );
    expect(container.querySelector(".install-card")).toBeNull();
  });

  it("renders nothing when there is no prompt and no iOS instructions", () => {
    // Desktop Chromium before beforeinstallprompt fires, or any non-iOS
    // non-Chromium browser: no honest install surface to show.
    const { container } = render(
      <InstallCard
        canInstall={false}
        iosInstructions={false}
        installed={false}
        onInstall={async () => "unavailable"}
      />,
    );
    expect(container.querySelector(".install-card")).toBeNull();
  });

  it("shows Share-sheet instructions on iOS instead of a dead Install button", () => {
    const { container } = render(
      <InstallCard
        canInstall={false}
        iosInstructions={true}
        installed={false}
        onInstall={async () => "unavailable"}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).toMatch(/Add to Home Screen/i);
    expect(text).toMatch(/Share/i);
    // No Install button on iOS — the platform can't honour it.
    const btn = [...container.querySelectorAll("button")].find((b) =>
      /install app/i.test(b.textContent ?? ""),
    );
    expect(btn).toBeUndefined();
  });

  it("shows an Install button when the prompt is captured and fires onInstall", async () => {
    const onInstall = vi.fn(async (): Promise<InstallOutcome> => "accepted");
    const { container } = render(
      <InstallCard
        canInstall={true}
        iosInstructions={false}
        installed={false}
        onInstall={onInstall}
      />,
    );
    expect(container.querySelector(".channel-on")?.textContent ?? "").toMatch(/ready/i);
    const btn = [...container.querySelectorAll("button")].find((b) =>
      /install app/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    expect(btn).toBeTruthy();
    fireEvent.click(btn);
    await waitFor(() => expect(onInstall).toHaveBeenCalledTimes(1));
    // Accepted → honest confirmation, button retired.
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/added to your home screen/i);
    });
    expect(
      [...container.querySelectorAll("button")].find((b) => /install app/i.test(b.textContent ?? "")),
    ).toBeUndefined();
  });

  it("honestly reports a dismissed prompt", async () => {
    const { container } = render(
      <InstallCard
        canInstall={true}
        iosInstructions={false}
        installed={false}
        onInstall={async () => "dismissed"}
      />,
    );
    fireEvent.click(
      [...container.querySelectorAll("button")].find((b) => /install app/i.test(b.textContent ?? "")) as HTMLButtonElement,
    );
    await waitFor(() => {
      expect(container.textContent ?? "").toMatch(/maybe later/i);
    });
  });

  it("honestly reports when the prompt call errors", async () => {
    const { container } = render(
      <InstallCard
        canInstall={true}
        iosInstructions={false}
        installed={false}
        onInstall={async () => "error"}
      />,
    );
    fireEvent.click(
      [...container.querySelectorAll("button")].find((b) => /install app/i.test(b.textContent ?? "")) as HTMLButtonElement,
    );
    await waitFor(() => {
      expect(container.querySelector(".error")).not.toBeNull();
    });
  });
});