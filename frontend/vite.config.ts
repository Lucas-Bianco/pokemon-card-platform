import basicSsl from "@vitejs/plugin-basic-ssl";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    // getUserMedia refuses to run outside a secure context. Over plain HTTP on a
    // phone the camera is blocked outright — not a prompt, a hard refusal. This
    // serves a self-signed cert so the LAN address qualifies.
    basicSsl(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: false, // supplied by public/manifest.webmanifest
    }),
  ],
  server: {
    host: true, // listen on the LAN so a phone can reach it
    port: 5173,
    proxy: {
      // An HTTPS page cannot fetch an HTTP API — that is mixed content, and no CORS
      // header fixes it. Proxying keeps the browser on HTTPS while Vite talks to the
      // backend server-side.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
  },
  build: {
    // Split the stable runtime vendors (React + Framer Motion) out of the
    // entry chunk. The app is a single eager-mounted shell, so this does NOT
    // reduce the total first-paint payload — every tab is imported up front
    // (route-based React.lazy splitting would, but that forces Suspense
    // fallbacks and breaks the suite's synchronous getByText/getByRole tab
    // assertions, a churny risk not worth taking silently). What this DOES do:
    //   1. Drop the entry chunk below the 500 kB warning threshold (the app
    //      code ships on its own; react/react-dom/framer-motion load from a
    //      separate, stable URL).
    //   2. Give the vendors a long-lived cache entry — a release that only
    //      touches app code reuses the cached vendor chunk, so a returning
    //      installed-PWA user re-downloads just the app slice.
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          // react-dom pulls in react; group both so the React reconciler +
          // runtime live in one cacheable slice.
          if (id.includes("/react-dom/") || id.includes("/react/")) {
            return "react-vendor";
          }
          if (id.includes("/framer-motion/") || id.includes("/motion-dom/") || id.includes("/motion-utils/")) {
            return "motion-vendor";
          }
          return undefined;
        },
      },
    },
  },
});
