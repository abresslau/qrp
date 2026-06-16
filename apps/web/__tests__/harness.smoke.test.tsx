import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

// Smoke test: proves jsdom + RTL + jest-dom matchers are wired (Story QH.7 AC1).
describe("test harness", () => {
  it("renders a component into jsdom and matches with jest-dom", () => {
    render(<div role="status">ok</div>);
    expect(screen.getByRole("status")).toHaveTextContent("ok");
  });
});
