import { useEffect, useRef, useState } from "react";

// Animates a number from 0 → target over `duration` ms using requestAnimationFrame.
// - reduced=true (prefers-reduced-motion) → returns target instantly (no animation).
// - No requestAnimationFrame (very old jsdom) → returns target instantly.
// - target <= 0 → returns target instantly (never animates a "—"/empty).
// Deterministic in tests: the reduced path is synchronous; the animated path settles
// to `target` on the final frame, so a `waitFor` on the final value always passes.
export function useCountUp(target: number, duration = 900, reduced = false): number {
  const [value, setValue] = useState(reduced || target <= 0 ? target : 0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (reduced || target <= 0) {
      setValue(target);
      return;
    }
    if (typeof requestAnimationFrame === "undefined") {
      setValue(target);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      // easeOutCubic
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(target * eased);
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setValue(target);
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [target, duration, reduced]);

  return value;
}