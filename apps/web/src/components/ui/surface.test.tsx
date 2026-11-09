// @vitest-environment jsdom

import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import * as stylex from "@stylexjs/stylex";

import { Surface, type SurfaceTone } from "./surface";

const tones: SurfaceTone[] = ["raised", "floating", "sunken"];

describe("Surface", () => {
  it.each(tones)("draws a %s surface around its children", (tone) => {
    const html = renderToStaticMarkup(
      <Surface tone={tone}>
        <button type="button">Fit bounds</button>
      </Surface>,
    );
    expect(html).toContain("<div");
    expect(html).toContain("Fit bounds");
  });

  it("gives each tone its own chrome class, so a call site never writes a background", () => {
    const classOf = (tone: SurfaceTone) => {
      const html = renderToStaticMarkup(<Surface tone={tone}>x</Surface>);
      return html.match(/class="([^"]+)"/)?.[1] ?? "";
    };
    const seen = new Set(tones.map(classOf));
    expect(seen.size).toBe(tones.length);
  });

  it("leaves layout to the caller and keeps their classes and overrides last", () => {
    const lift = stylex.create({ lift: { position: "absolute", top: "8px" } });
    const html = renderToStaticMarkup(
      <Surface className="nodrag nopan" xstyle={lift.lift}>
        x
      </Surface>,
    );
    expect(html).toContain("nodrag");
    expect(html).toContain("nopan");
  });
});
