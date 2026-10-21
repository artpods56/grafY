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
    // The Playwright suites have their own runner and need launcher-supplied
    // environment, so collecting them here fails at import.
    exclude: [...configDefaults.exclude, "e2e*/**"],
    setupFiles: ["./vitest.setup.ts"],
  },
});
