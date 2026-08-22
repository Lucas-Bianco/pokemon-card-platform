import { useCallback, useEffect, useState } from "react";

import { parseRoute, routeToSearch, type Route } from "./route";

// History entries this app pushed are stamped `appNav`, so a Back affordance
// can tell "there is an app view behind me" from "this view was deep-linked,
// reloaded, or opened from a home-screen shortcut". The first case walks the
// history entry back (so the in-app Back button and the browser Back button
// agree and history does not grow on every close); the second rewrites in
// place, so browser Back still leaves the app instead of stranding the user.
interface HistoryState {
  appNav?: boolean;
}

export interface RouteApi {
  route: Route;
  navigate: (next: Route, opts?: { replace?: boolean }) => void;
  /** Close the top overlay: step back if this app pushed the entry, else rewrite to `fallback`. */
  back: (fallback: Route) => void;
}

function currentSearch(): string {
  return window.location.search;
}

function urlFor(route: Route): string {
  return `${window.location.pathname}${routeToSearch(route)}`;
}

export function useRoute(): RouteApi {
  // Parsed synchronously in the initialiser, never in an effect. The very first
  // render is already the correct view, so there is no async hydration step and
  // no post-mount redirect — a test that renders <App/> and immediately queries
  // the nav sees the same DOM it always did.
  const [route, setRoute] = useState<Route>(() => parseRoute(currentSearch()));

  // Rewrite the entry URL to its canonical form once on mount: `?view=portfolio`
  // becomes `?view=vault`, an unknown `?view=` becomes a bare "/". This keeps the
  // invariant the rest of the hook relies on — the URL always equals
  // routeToSearch(route) — so navigate can compare the two to avoid pushing a
  // duplicate entry. replaceState, not push, so the shortcut URL is not left
  // behind as a Back target. The parsed route is unchanged by this, so it never
  // re-renders or flashes a different view, and it is idempotent under
  // StrictMode's double-invoked effects.
  useEffect(() => {
    const canonical = routeToSearch(parseRoute(currentSearch()));
    if (canonical !== currentSearch()) {
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${canonical}`,
      );
    }
  }, []);

  // Back/forward (and the programmatic history.back() below) land here: the URL
  // has already changed, so the route is re-derived from it.
  useEffect(() => {
    function onPopState() {
      setRoute(parseRoute(currentSearch()));
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  // Stable across renders (it reads the live URL rather than closing over
  // `route`), so callers can hold it in an effect with an empty dep list
  // without going stale.
  const navigate = useCallback((next: Route, opts?: { replace?: boolean }) => {
    const url = urlFor(next);
    // Re-selecting the tab you are already on should not stack a duplicate
    // history entry, but it must still apply the route (it is how tapping the
    // active tab closes an open card).
    if (url !== `${window.location.pathname}${currentSearch()}`) {
      const state: HistoryState = { appNav: true };
      if (opts?.replace) window.history.replaceState(state, "", url);
      else window.history.pushState(state, "", url);
    }
    setRoute(next);
  }, []);

  const back = useCallback(
    (fallback: Route) => {
      const state = window.history.state as HistoryState | null;
      if (state?.appNav) {
        // popstate fires and re-derives the route from the restored URL.
        window.history.back();
        return;
      }
      navigate(fallback, { replace: true });
    },
    [navigate],
  );

  return { route, navigate, back };
}
