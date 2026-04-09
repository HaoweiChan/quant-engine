import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { defineConfig } from "vite";

// Backend port is configurable so prod (8000) and dev (8001) can run side by side.
const BACKEND_PORT = process.env.QE_BACKEND_PORT ?? "8000";
const proxy = {
  "/api": `http://127.0.0.1:${BACKEND_PORT}`,
  "/ws": { target: `ws://127.0.0.1:${BACKEND_PORT}`, ws: true },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
    dedupe: ["react", "react-dom"],
  },
  server: { host: "0.0.0.0", proxy },
  preview: { host: "0.0.0.0", proxy },
});
