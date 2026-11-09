// @vitest-environment jsdom

import { describe, expect, it } from "vitest";

import { isWholeHtmlTable } from "./table/cell-views";
import { disarmFrameHtml } from "./frame-html";

describe("disarmFrameHtml", () => {
  it("drops a remote href and target, and keeps a hash link", () => {
    const html = disarmFrameHtml(
      '<p><a href="https://evil.example/out" target="_blank">Leave</a> <a href="#parish" target="_blank">Stay</a></p>',
    );
    expect(html).not.toContain("evil.example");
    expect(html).not.toContain("target");
    expect(html).toContain('href="#parish"');
    expect(html).toContain("Leave");
    expect(html).toContain("Stay");
  });

  it("drops an area href and an SVG link, including xlink:href", () => {
    const html = disarmFrameHtml(
      [
        '<map name="m"><area href="https://evil.example/area" target="_blank" alt="spot"></map>',
        '<svg><a href="https://evil.example/svg">Out</a><a href="#mark">In</a></svg>',
        '<svg><a xlink:href="https://evil.example/xlink">X</a></svg>',
      ].join(""),
    );
    expect(html).not.toContain("evil.example");
    expect(html).not.toContain("target");
    expect(html).toContain('href="#mark"');
    expect(html).toContain("Out");
    expect(html).toContain("X");
  });

  it("removes base elements from a document and keeps the head style", () => {
    const html = disarmFrameHtml(
      '<!doctype html><html><head><base href="https://evil.example/base"><style>h1 { color: red; }</style></head><body><p>Hi</p></body></html>',
    );
    expect(html).not.toContain("evil.example");
    expect(html).not.toContain("<base");
    expect(html).toContain("h1 { color: red; }");
    expect(html).toContain("<p>Hi</p>");
  });

  it("leaves a bare table a bare table, with its link disarmed", () => {
    const html = disarmFrameHtml(
      '<table><tr><td><a href="https://evil.example/t">n</a></td></tr></table>',
    );
    expect(isWholeHtmlTable(html)).toBe(true);
    expect(html).not.toContain("evil.example");
    expect(html).toContain(">n<");
  });

  it("leaves nothing that would turn into a link once the frame parses it", () => {
    const html = disarmFrameHtml(
      [
        '<div><template shadowrootmode="open"><a href="https://evil.example/shadow">x</a></template></div>',
        '<svg><a><set attributeName="href" to="https://evil.example/set"></set><animate attributeName="xlink:href" values="https://evil.example/animate"></animate><rect></rect></a></svg>',
        '<link rel="dns-prefetch" href="//evil.example">',
        '<math href="https://evil.example/math"><mi>x</mi></math>',
      ].join(""),
    );
    expect(html).not.toContain("evil.example");
    expect(html).toContain("<rect>");
  });

  it("settles, so a second sweep changes nothing", () => {
    for (const html of [
      "<!doctype html><html><head><style>h1{}</style></head><body><h1>x</h1></body></html>",
      "<table><tr><td>1</td></tr></table>",
      "<p>words",
    ]) {
      const once = disarmFrameHtml(html);
      expect(once).not.toBe("");
      expect(disarmFrameHtml(once)).toBe(once);
    }
  });
});
