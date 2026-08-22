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
});
