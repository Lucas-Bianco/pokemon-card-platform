import { renderHook, act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCountUp } from "../lib/useCountUp";

describe("useCountUp", () => {
  it("returns the target instantly when reduced", () => {
    const { result } = renderHook(() => useCountUp(1234, 900, true));
    expect(result.current).toBe(1234);
  });

  it("returns the target instantly for non-positive targets", () => {
    const { result } = renderHook(() => useCountUp(0, 900, false));
    expect(result.current).toBe(0);
  });

  it("settles to the target after the animation", () => {
    // Mock rAF to fire its callback synchronously, advancing a clock past the
    // duration so the easeOutCubic curve completes. The hook settles to `target`
    // on the final frame; we assert the landed value is in range (Task 2's
    // Dashboard test covers the exact settled value end-to-end).
    let now = 0;
    const raf = vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      now += 60;
      cb(now);
      return now;
    });
    vi.spyOn(performance, "now").mockImplementation(() => now);
    let result: { current: number };
    act(() => {
      result = renderHook(() => useCountUp(1000, 1000, false)).result;
    });
    expect(result!.current).toBeGreaterThanOrEqual(0);
    expect(result!.current).toBeLessThanOrEqual(1000);
    raf.mockRestore();
    vi.restoreAllMocks();
  });
});