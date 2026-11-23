import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react(), tailwindcss()],
    server: { proxy: { "/api": env.PENTEST_AGENT_API_PROXY ?? "http://127.0.0.1:8000" } },
  };
});
