// TEMPORARY: HTTP-only dev config so the in-app browser (which rejects the
// self-signed cert from basicSsl) can drive the UI. localhost is a secure
// context over plain HTTP, so getUserMedia still works here.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
