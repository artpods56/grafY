// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Menu } from "@base-ui/react/menu";
import * as stylex from "@stylexjs/stylex";

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

import {
  Button,
  type ButtonSize,
  type ButtonVariant,
  IconButton,
  type IconButtonSize,
  type IconButtonVariant,
} from "./button";

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

function onlyButton(container: HTMLElement) {
  const buttons = container.querySelectorAll("button");
  expect(buttons).toHaveLength(1);
  const button = buttons.item(0);
  if (!button) throw new Error("expected exactly one button");
  return button;
}

const buttonVariants: ButtonVariant[] = [
  "primary",
  "secondary",
  "soft",
  "ghost",
  "danger",
];
const buttonSizes: ButtonSize[] = ["xs", "sm", "md", "lg"];
const iconButtonVariants: IconButtonVariant[] = [
  "ghost",
  "soft",
  "primary",
  "danger",
];
const iconButtonSizes: IconButtonSize[] = ["xs", "sm", "md", "lg"];
const iconButtonShapes = ["square", "round"] as const;

describe("Button", () => {
  it("defaults to a secondary md button of type button", async () => {
    const container = await mount(<Button>Save</Button>);
    const button = onlyButton(container);

    expect(button.className).toBe("base secondary md");
    expect(button.textContent).toBe("Save");
    expect(button.getAttribute("type")).toBe("button");
  });

  it.each(
    buttonVariants.flatMap((variant) =>
      buttonSizes.map((size) => [variant, size] as const),
    ),
  )("renders the %s variant at size %s", async (variant, size) => {
    const container = await mount(
      <Button variant={variant} size={size}>
        Save
      </Button>,
    );

    expect(onlyButton(container).className).toBe(`base ${variant} ${size}`);
  });

  it("keeps a submit type", async () => {
    const container = await mount(<Button type="submit">Send</Button>);

    expect(onlyButton(container).getAttribute("type")).toBe("submit");
  });

  it("appends plain class names after the StyleX ones", async () => {
    const container = await mount(<Button className="nodrag nopan">x</Button>);

    expect(onlyButton(container).className).toBe(
      "base secondary md nodrag nopan",
    );
  });

  it("applies xstyle last", async () => {
    const xstyle = {
      __styleName: "override",
    } as unknown as stylex.StyleXStyles;
    const container = await mount(<Button xstyle={xstyle}>x</Button>);

    expect(onlyButton(container).className).toBe("base secondary md override");
  });

  it("is disabled and calls onClick only when enabled", async () => {
    const onClick = vi.fn();

    const enabled = await mount(<Button onClick={onClick}>Save</Button>);
    const enabledButton = onlyButton(enabled);
    await act(async () => enabledButton.click());
    expect(onClick).toHaveBeenCalledTimes(1);

    const disabled = await mount(
      <Button onClick={onClick} disabled>
        Save
      </Button>,
    );
    const disabledButton = onlyButton(disabled);
    expect(disabledButton.disabled).toBe(true);
    await act(async () => disabledButton.click());
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("IconButton", () => {
  it("labels itself", async () => {
    const container = await mount(
      <IconButton label="Configure">
        <svg />
      </IconButton>,
    );
    const button = onlyButton(container);

    expect(button.getAttribute("aria-label")).toBe("Configure");
    expect(button.getAttribute("title")).toBe("Configure");
    expect(button.className).toBe("base ghost sm square");
    expect(button.hasAttribute("aria-pressed")).toBe(false);
  });

  it("lets title differ from the label", async () => {
    const container = await mount(
      <IconButton label="Configure" title="Open settings">
        <svg />
      </IconButton>,
    );
    const button = onlyButton(container);

    expect(button.getAttribute("aria-label")).toBe("Configure");
    expect(button.getAttribute("title")).toBe("Open settings");
  });

  it.each(
    iconButtonVariants.flatMap((variant) =>
      iconButtonSizes.flatMap((size) =>
        iconButtonShapes.map((shape) => [variant, size, shape] as const),
      ),
    ),
  )(
    "renders the %s variant at size %s with the %s shape",
    async (variant, size, shape) => {
      const container = await mount(
        <IconButton
          label="Configure"
          variant={variant}
          size={size}
          shape={shape}
        >
          <svg />
        </IconButton>,
      );

      expect(onlyButton(container).className).toBe(
        `base ${variant} ${size} ${shape}`,
      );
    },
  );

  it("shows the pressed state", async () => {
    const on = await mount(
      <IconButton label="Fullscreen" pressed>
        <svg />
      </IconButton>,
    );
    const onButton = onlyButton(on);
    expect(onButton.getAttribute("aria-pressed")).toBe("true");
    expect(onButton.className.endsWith(" pressed")).toBe(true);

    const off = await mount(
      <IconButton label="Fullscreen" pressed={false}>
        <svg />
      </IconButton>,
    );
    const offButton = onlyButton(off);
    expect(offButton.getAttribute("aria-pressed")).toBe("false");
    expect(offButton.className.includes("pressed")).toBe(false);
  });

  it("works as a Base UI trigger's render target", async () => {
    const container = await mount(
      <Menu.Root>
        <Menu.Trigger render={<IconButton label="Actions" />}>
          <svg data-icon="more" />
        </Menu.Trigger>
      </Menu.Root>,
    );
    const button = onlyButton(container);

    expect(button.getAttribute("aria-label")).toBe("Actions");
    expect(button.querySelector('svg[data-icon="more"]')).not.toBeNull();
    expect(button.getAttribute("aria-haspopup")).toBe("menu");
    expect(button.className).toBe("base ghost sm square");
  });
});
