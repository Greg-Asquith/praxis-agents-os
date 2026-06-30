import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 3000,
    // Bind mounts don't emit native FS events in containers; poll so HMR works.
    watch: { usePolling: true },
  },
  preview: {
    host: true,
    port: 8080,
  },
})
