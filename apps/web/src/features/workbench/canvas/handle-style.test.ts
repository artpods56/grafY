import { describe, expect, it } from "vitest";

import { portMarkStyle } from "./handle-style";

describe("portMarkStyle", () => {
  it("uses a single colored border for a single-value port", () => {
    expect(portMarkStyle("#7b63c9")).toEqual({ borderColor: "#7b63c9" });
  });

  it("adds an outer ring for a sequence port", () => {
    const style = portMarkStyle("#7b63c9", true);
    expect(style.borderColor).toBe("#7b63c9");
    expect(String(style.boxShadow)).toContain("0 0 0 3.5px #7b63c9");
  });
});
