import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The development server proxies /api to the Python backend, so the browser
// talks to a single origin in development and in production alike. That is why
// the API needs no CORS configuration.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
