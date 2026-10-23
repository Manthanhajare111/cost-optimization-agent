import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
    server: {
    port: 4173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: { port: 4173 },
  test: {
    environment: "jsdom",
    pool: "forks",
    maxWorkers: 1,
    setupFiles: "./src/test/setup.ts",
    include: ["src/test/**/*.test.{ts,tsx}"],
    css: true,
  },
});
