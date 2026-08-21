import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "../components/Toast";

function Harness({ message, tone }: { message: string; tone?: "info" | "success" | "warn" }) {
  const { toast } = useToast();
  return <button onClick={() => toast(message, tone)}>fire</button>;
}

describe("Toast", () => {
  it("renders a toast when fired under the provider", async () => {
    render(<ToastProvider><Harness message="Added to collection" /></ToastProvider>);
    fireEvent.click(screen.getByRole("button", { name: "fire" }));
    await waitFor(() => expect(screen.getByText("Added to collection")).toBeDefined());
  });

  it("dismisses on close click", async () => {
    render(<ToastProvider><Harness message="Watch created" /></ToastProvider>);
    fireEvent.click(screen.getByRole("button", { name: "fire" }));
    await waitFor(() => expect(screen.getByText("Watch created")).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
    await waitFor(() => expect(screen.queryByText("Watch created")).toBeNull());
  });

  it("useToast is a noop without a provider (never throws, renders nothing)", () => {
    render(<Harness message="never shown" />);
    fireEvent.click(screen.getByRole("button", { name: "fire" }));
    expect(screen.queryByText("never shown")).toBeNull();
  });

  it("auto-dismisses after the timeout", async () => {
    vi.useFakeTimers();
    render(<ToastProvider><Harness message="Purchase logged" /></ToastProvider>);
    act(() => { fireEvent.click(screen.getByRole("button", { name: "fire" })); });
    expect(screen.getByText("Purchase logged")).toBeDefined();
    act(() => { vi.advanceTimersByTime(3600); });
    vi.useRealTimers();
    await waitFor(() => expect(screen.queryByText("Purchase logged")).toBeNull());
  });
});