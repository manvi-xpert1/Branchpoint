import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// In development the Vite server proxies /api to the FastAPI backend,
// so the browser sees one origin and no CORS setup is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.VITE_API_TARGET ?? "http://localhost:8000",
      "/health": process.env.VITE_API_TARGET ?? "http://localhost:8000",
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          flow: ["@xyflow/react"],
          charts: ["recharts"],
        },
      },
    },
  },
  test: { environment: "node" },
});
