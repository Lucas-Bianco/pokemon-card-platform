/**
 * Footer — design-spec link (relative) + "Last updated 2026-08-01".
 * The href is a RELATIVE link preserved exactly from docs/index.html.
 * No "use client" needed — this is static content.
 */
export function Footer() {
  return (
    <footer className="site-footer">
      <div className="wrap">
        Design spec:{" "}
        <a href="superpowers/specs/2026-07-28-card-recognition-platform-design.md">
          Phase 0 + 1
        </a>{" "}
        · Last updated 2026-08-01
      </div>
    </footer>
  );
}