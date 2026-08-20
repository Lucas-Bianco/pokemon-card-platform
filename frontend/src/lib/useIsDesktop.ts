import { useEffect, useState } from "react";

// Single source of truth for "render the desktop sidebar vs the mobile bottom-nav."
// CRITICAL: exactly one nav must be mounted at a time — tests do
//   getByRole("button", { name: "Scan" }) which throws if both navs are in the DOM.
// jsdom has no real viewport: window.matchMedia exists but returns matches:false and
// never fires listeners, so this hook returns false in tests → mobile bottom-nav only.
const QUERY = "(min-width: 1024px)";

export function useIsDesktop(): boolean {
  const [desktop, setDesktop] = useState<boolean>(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(QUERY).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mql = window.matchMedia(QUERY);
    const onChange = (e: MediaQueryListEvent) => setDesktop(e.matches);
    if (mql.addEventListener) mql.addEventListener("change", onChange);
    else mql.addListener(onChange);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener("change", onChange);
      else mql.removeListener(onChange);
    };
  }, []);

  return desktop;
}