import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    // Proxy API requests to the FastAPI backend during development
    proxy: {
      "/api": {
        target: process.env.VITE_API_URL || "http://localhost:8000",
        changeOrigin: true,
        // No rewrite needed — backend routes already start with /api
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    // Code splitting per route for smaller initial bundle
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom", "react-router-dom"],
          query: ["@tanstack/react-query"],
          charts: ["recharts", "d3"],
        },
      },
    },
  },
  // Ensure JSON imports work (for potential static mode)
  assetsInclude: ["**/*.json"],
});
