// Vite builds the console into dist/, which `tyche ui` serves (ADR-0046).
// `npm run dev` serves it with hot reload instead, and passes /api to a running
// `tyche ui --no-browser`; open the dev address with the same #token=… it printed.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // One file served from this machine: splitting it would only add requests.
    chunkSizeWarningLimit: 1500,
  },
});
