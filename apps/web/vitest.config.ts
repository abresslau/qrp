import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

// Console unit-test harness (Story QH.7). jsdom + RTL; the `@/*` alias is honoured via
// vite-tsconfig-paths so tests import exactly as the app does. Test globals are NOT enabled —
// tests import { describe, it, expect, vi } from "vitest" explicitly, which keeps the files
// clean under the same eslint flat config the app uses (no per-file env carve-outs).
export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
    css: false,
  },
});
