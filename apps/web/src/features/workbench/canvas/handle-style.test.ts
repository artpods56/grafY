import { describe, expect, it } from "vitest";

import { handleStyle, portMarkStyle } from "./handle-style";

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

describe("handleStyle", () => {
  it("keeps a large hit target with a hollow single ring", () => {
    const style = handleStyle("50%", "#7b63c9");
    expect(style.width).toBe("30px");
    expect(style.height).toBe("30px");
    expect(String(style.background)).toContain("#7b63c9 3px 5px");
    expect(String(style.background)).not.toContain("8.5px");
  });

  it("draws a second ring for sequence ports", () => {
    const style = handleStyle(19, "#4590c7", true);
    expect(style.top).toBe("19px");
    expect(String(style.background)).toContain("#4590c7 7px 8.5px");
  });
});
