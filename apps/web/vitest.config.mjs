import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

const webRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      "@": webRoot,
    },
  },
  test: {
    environment: "jsdom",
    environmentOptions: {
      jsdom: {
        pretendToBeVisual: true,
      },
    },
    include: ["tests/**/*.test.tsx"],
    setupFiles: ["./tests/setup.ts"],
    restoreMocks: true,
    clearMocks: true,
  },
});
