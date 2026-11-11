import { fileURLToPath } from "node:url";

import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    // The e2e pilot has its own runner and launcher-supplied environment.
    exclude: [...configDefaults.exclude, "tests/**/*.e2e.ts"],
    setupFiles: ["./vitest.setup.ts"],
  },
});
