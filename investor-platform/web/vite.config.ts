import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.API_TARGET || "http://127.0.0.1:8010";
  const url = new URL(target);
  if (
    url.protocol !== "http:" ||
    !["127.0.0.1", "localhost"].includes(url.hostname)
  ) {
    throw new Error("API_TARGET must be a local HTTP address.");
  }
  const server = {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    allowedHosts: ["localhost"],
    cors: { origin: ["http://127.0.0.1:5173", "http://localhost:5173"] },
    proxy: { "/api": { target, changeOrigin: true } },
  };
  return { plugins: [react()], server, preview: server };
});
