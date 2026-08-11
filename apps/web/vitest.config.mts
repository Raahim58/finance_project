import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["**/node_modules/**", "**/test-results/**", "**/*.spec.{ts,tsx}"],
  },
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } }
});
