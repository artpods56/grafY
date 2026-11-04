import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));

vi.mock("@/components/theme", () => ({
  useTheme: () => ({
    preference: "light",
    resolved: "light",
    setPreference: () => undefined,
    cycleTheme: () => undefined,
  }),
}));

import { PortInspectorSpike } from "./PortInspectorSpike";

describe("PortInspectorSpike", () => {
  it("renders the vector layer node and today's schema tree", () => {
    const html = renderToStaticMarkup(<PortInspectorSpike />);
    expect(html).toContain("Vector map layer");
    expect(html).toContain("geo.map_layer@1");
    expect(html).toContain("All unions");
    expect(html).toContain("Drill");
  });
});
