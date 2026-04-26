import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/search": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/deserts": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/deserts/pincodes": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/population": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/analysis": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.ts"],
  },
});
