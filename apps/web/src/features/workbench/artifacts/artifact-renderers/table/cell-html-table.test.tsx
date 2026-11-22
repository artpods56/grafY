// @vitest-environment jsdom

import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { CellHtmlTable } from "./cell-html-table";

const draw = (html: string) =>
  renderToStaticMarkup(<CellHtmlTable html={html} />);

it("keeps the structure and spans of a table", () => {
  const out = draw(
    '<table><tr><th rowspan="2" colspan="3">A<br/>B</th></tr><tr><td>1</td></tr></table>',
  );
  expect(out).toContain('rowSpan="2"');
  expect(out).toContain('colSpan="3"');
  expect(out).toContain("A<br/>B");
  expect(out).toContain("<td");
});

it("carries over nothing that could run, load or restyle", () => {
  const out = draw(
    '<table style="background:navy" onclick="x()"><tr><td onmouseover="y()"><img src="https://evil.example/a.png"><script>z()</script><a href="javascript:w()">words</a></td></tr></table>',
  );
  expect(out).not.toMatch(/navy|onclick|onmouseover|<img|evil|<a |javascript/);
  expect(out).toContain("words");
});

it("ignores a span that is not a number", () => {
  const out = draw('<table><tr><td rowspan="x;">1</td></tr></table>');
  expect(out).not.toContain("rowSpan");
});
