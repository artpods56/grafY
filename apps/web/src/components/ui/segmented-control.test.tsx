// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import * as stylex from "@stylexjs/stylex";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles extends Record<string, object>>(styles: Styles) =>
    Object.fromEntries(
      Object.entries(styles).map(([name, style]) => [
        name,
        { ...style, __styleName: name },
      ]),
    ) as Styles,
  defineVars: <Variables,>(variables: Variables) => variables,
  props: (
    ...styles: Array<{ __styleName?: string } | null | false | undefined>
  ) => ({
    className: styles
      .flatMap((style) =>
        style && style.__styleName ? [style.__styleName] : [],
      )
      .join(" "),
  }),
}));

import { SegmentedControl } from "./segmented-control";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<ReturnType<typeof createRoot>>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
});

async function mount(element: React.ReactElement) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await act(async () => root.render(element));
  return container;
}

/**
 * jsdom 26 has no `PointerEvent`, and Base UI's Radio.Root forwards a click to
 * its hidden input with `new (ownerWindow(input).PointerEvent)("click", …)`
 * (radio/root/RadioRoot.mjs:138). Without the constructor that handler throws
 * and the group value never changes, so no click can be tested at all. Both
 * `.click()` and a dispatched `MouseEvent` fail the same way. This shim gives
 * Base UI the constructor it asks for; it changes no behaviour of the component.
 */
if (!("PointerEvent" in globalThis)) {
  class PointerEventShim extends MouseEvent {}
  Object.assign(globalThis, { PointerEvent: PointerEventShim });
}

const MODEL_OPTIONS = [
  { value: "deployment", label: "Deployment default" },
  { value: "custom", label: "Custom endpoint" },
] as const;

function Controlled({
  onChange,
  options = MODEL_OPTIONS,
}: {
  onChange: (value: string) => void;
  options?: readonly { value: string; label: string; disabled?: boolean }[];
}) {
  const [value, setValue] = React.useState("deployment");
  return (
    <SegmentedControl
      aria-label="Model"
      value={value}
      options={options}
      onValueChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

function groupIn(container: HTMLElement) {
  const groups = container.querySelectorAll('[role="radiogroup"]');
  expect(groups).toHaveLength(1);
  const group = groups.item(0);
  if (!group) throw new Error("expected exactly one radiogroup");
  return group;
}

function radiosIn(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>('[role="radio"]'));
}

describe("SegmentedControl", () => {
  it("is a labelled radio group", async () => {
    const container = await mount(<Controlled onChange={() => {}} />);
    const radios = radiosIn(container);

    expect(groupIn(container).getAttribute("aria-label")).toBe("Model");
    expect(groupIn(container).className).toBe("root");
    expect(radios.map((radio) => radio.textContent)).toEqual([
      "Deployment default",
      "Custom endpoint",
    ]);
    expect(radios[0]?.getAttribute("aria-checked")).toBe("true");
    expect(radios[1]?.getAttribute("aria-checked")).toBe("false");
  });

  it("marks the chosen segment", async () => {
    const container = await mount(<Controlled onChange={() => {}} />);
    const radios = radiosIn(container);

    expect(radios[0]?.className).toBe("segment md enabled on");
    expect(radios[1]?.className).toBe("segment md enabled");
  });

  it("reports a new choice", async () => {
    const spy = vi.fn();
    const container = await mount(<Controlled onChange={spy} />);
    const second = radiosIn(container)[1];
    if (!second) throw new Error("expected a second radio");

    await act(async () => second.click());

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith("custom");
    expect(second.getAttribute("aria-checked")).toBe("true");
    expect(second.className).toBe("segment md enabled on");
  });

  it("skips a disabled option", async () => {
    const spy = vi.fn();
    const container = await mount(
      <Controlled
        onChange={spy}
        options={[
          { value: "deployment", label: "Deployment default" },
          { value: "custom", label: "Custom endpoint", disabled: true },
        ]}
      />,
    );
    const second = radiosIn(container)[1];
    if (!second) throw new Error("expected a second radio");

    expect(second.getAttribute("aria-disabled")).toBe("true");
    expect(second.className).toBe("segment md disabled");

    await act(async () => second.click());
    expect(spy).not.toHaveBeenCalled();
  });

  it("disables the whole group", async () => {
    const container = await mount(
      <SegmentedControl
        aria-label="Model"
        value="deployment"
        options={MODEL_OPTIONS}
        onValueChange={() => {}}
        disabled
      />,
    );
    const radios = radiosIn(container);

    expect(radios[0]?.getAttribute("aria-disabled")).toBe("true");
    expect(radios[1]?.getAttribute("aria-disabled")).toBe("true");
    expect(radios[0]?.className).toBe("segment md disabled on");
    expect(radios[1]?.className).toBe("segment md disabled");
  });

  it("takes a size and overrides", async () => {
    const sized = await mount(
      <SegmentedControl
        aria-label="Model"
        value="deployment"
        options={MODEL_OPTIONS}
        onValueChange={() => {}}
        size="sm"
      />,
    );
    expect(radiosIn(sized)[0]?.className).toBe("segment sm enabled on");

    const plain = await mount(
      <SegmentedControl
        aria-label="Model"
        value="deployment"
        options={MODEL_OPTIONS}
        onValueChange={() => {}}
        className="nodrag"
      />,
    );
    expect(groupIn(plain).className).toBe("root nodrag");

    const overridden = await mount(
      <SegmentedControl
        aria-label="Model"
        value="deployment"
        options={MODEL_OPTIONS}
        onValueChange={() => {}}
        xstyle={{ __styleName: "override" } as unknown as stylex.StyleXStyles}
      />,
    );
    expect(groupIn(overridden).className).toBe("root override");
  });
});
