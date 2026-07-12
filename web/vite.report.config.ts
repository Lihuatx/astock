import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "report-dist",
    emptyOutDir: true,
    cssCodeSplit: false,
    lib: {
      entry: "src/report.tsx",
      name: "AstockReviewReport",
      formats: ["iife"],
      fileName: () => "report.js",
    },
  },
});
