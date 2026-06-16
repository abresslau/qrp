// QH.7 test harness setup: jest-dom matchers (augments vitest's expect) + auto-cleanup so each
// test renders into a fresh DOM. Imported once via vitest.config.ts setupFiles.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
