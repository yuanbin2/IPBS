import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  // Keep the conventional Vite output path. Both the frontend Nginx image and
  // Django's local SPA fallback serve this same directory.
  base: "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "assets"
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      },
      "/media": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      }
    }
  }
});
