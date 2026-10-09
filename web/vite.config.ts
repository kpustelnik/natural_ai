import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { metroData } from "./plugins/metroData.ts";

// Data in public/data/ is written by scripts/06_export_web.py and served as-is.
// metroData: live reload of that data (and the Python watcher with `npm run model`).
export default defineConfig({
  plugins: [react(), metroData()],
  build: { target: "es2022", chunkSizeWarningLimit: 1500 },
});
