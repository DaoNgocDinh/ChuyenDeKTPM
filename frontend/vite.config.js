import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const { PLATFORM_PORT = "8000" } = loadEnv(mode, process.cwd(), "PLATFORM_");
  return {
    server: { proxy: { "/health": `http://127.0.0.1:${PLATFORM_PORT}` } },
  };
});
