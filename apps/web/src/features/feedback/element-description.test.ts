// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import { describeTarget, meaningfulTarget } from "./element-description";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("meaningfulTarget", () => {
  it("climbs from an icon to its button", () => {
    document.body.innerHTML =
      '<main><button aria-label="Run"><svg><path id="icon"></path></svg></button></main>';
    const icon = document.getElementById("icon")!;
    expect(meaningfulTarget(icon).tagName).toBe("BUTTON");
  });

  it("falls back to the canvas card around deep plain markup", () => {
    document.body.innerHTML =
      '<div data-card-id="card-7" data-card-kind="operator"><div><div><div><div><div><div><div><span id="deep">x</span></div></div></div></div></div></div></div></div>';
    const deep = document.getElementById("deep")!;
    expect(meaningfulTarget(deep).getAttribute("data-card-id")).toBe("card-7");
  });
});

describe("describeTarget", () => {
  it("describes a labelled button inside a card", () => {
    document.body.innerHTML =
      '<div data-card-id="card-7" data-card-kind="operator"><section><button id="b" data-testid="run-node">Run   now</button></section></div>';
    const button = document.getElementById("b")!;
    const { element, name } = describeTarget(button);
    expect(element).toMatchObject({
      tag: "button",
      role: "button",
      label: null,
      text: "Run now",
      test_id: "run-node",
      canvas_item_id: "card-7",
    });
    expect(element.selector).toBe('[id="b"]');
    expect(name).toBe("Button “Run now” · Node");
  });

  it("builds a positional selector when nothing anchors it", () => {
    document.body.innerHTML = "<main><p>a</p><p><em>b</em></p></main>";
    const em = document.querySelector("em")!;
    expect(describeTarget(em).element.selector).toBe(
      "body > main > p:nth-of-type(2) > em",
    );
  });

  it("names a card by its kind and reads a text field label", () => {
    document.body.innerHTML =
      '<div id="c" data-card-id="n1" data-card-kind="artifact"></div><label for="q">Search projects</label><input id="q" />';
    expect(describeTarget(document.getElementById("c")!).name).toBe(
      "Artifact card",
    );
    const input = describeTarget(document.getElementById("q")!);
    expect(input.element.label).toBe("Search projects");
    expect(input.name).toBe("Text field “Search projects”");
  });

  it("skips ids React generates", () => {
    document.body.innerHTML = '<div><button id=":r3:">Go</button></div>';
    const button = document.querySelector("button")!;
    expect(describeTarget(button).element.selector).toBe("body > div > button");
  });
});
