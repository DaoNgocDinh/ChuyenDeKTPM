import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const { PLATFORM_PORT = "8000" } = loadEnv(mode, process.cwd(), "PLATFORM_");
  const target = `http://127.0.0.1:${PLATFORM_PORT}`;
  return {
    server: {
      proxy: {
        "/health": target,
        "/projects": target,
        "/runs": target,
        "/artifacts": target,
      },
    },
  };
});
