import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Data in public/data/ is written by scripts/06_export_web.py and served as-is.
export default defineConfig({
  plugins: [react()],
  build: { target: "es2022", chunkSizeWarningLimit: 1500 },
});
