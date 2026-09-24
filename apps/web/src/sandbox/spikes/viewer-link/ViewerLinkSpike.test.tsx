import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
  defineVars: <Vars,>(vars: Vars) => vars,
}));

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

vi.mock("@base-ui/react/popover", () => ({
  Popover: {
    Root: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Trigger: ({
      children,
      ...props
    }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
      children: React.ReactNode;
    }) => (
      <button type="button" {...props}>
        {children}
      </button>
    ),
    Portal: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Positioner: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    Popup: ({ children }: { children: React.ReactNode }) => (
      <div role="dialog">{children}</div>
    ),
  },
}));

import { ViewerLinkSpike } from "./ViewerLinkSpike";

describe("ViewerLinkSpike", () => {
  it("renders real catalog chrome and two artifact viewers without interaction ports", () => {
    const html = renderToStaticMarkup(<ViewerLinkSpike />);
    expect(html).toContain("Query parcels");
    expect(html).toContain("Artifact Viewer");
    expect(html).toContain("Map document");
    expect(html).toContain("Drag a row");
    expect(html).toContain("Link views in ⋯");
    expect(html).toContain("Send to…");
    expect(html).not.toContain("linked input");
    expect(html).not.toMatch(/>selection</);
  });
});
