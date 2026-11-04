import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { DEV_API_TARGET, devProxyOrigin } from "./src/api/devProxy";
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
  server: {
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: DEV_API_TARGET,
        changeOrigin: true,
        configure(proxy) {
          proxy.on("proxyReq", (forwarded, request) => {
            const origin = devProxyOrigin(
              request.headers.origin,
              request.headers.host,
            );
            if (origin !== undefined) forwarded.setHeader("Origin", origin);
          });
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
  },
});
