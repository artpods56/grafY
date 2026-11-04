// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import * as stylex from "@stylexjs/stylex";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  Menu,
  MenuCheckboxItem,
  MenuContent,
  MenuGroup,
  MenuItem,
  MenuLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuSubmenu,
  MenuSubmenuTrigger,
  MenuTrigger,
} from "./menu";

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
 * Mounts an open menu and returns its popup. Base UI renders an open menu's
 * popup into `document.body` through its portal, so the mount container never
 * holds the rows; every query goes to `document.body`. The label tells one
 * menu's popup from another when a test mounts several.
 */
async function openMenu(label: string, children: React.ReactNode) {
  await mount(
    <Menu defaultOpen>
      <MenuTrigger>Open</MenuTrigger>
      <MenuContent aria-label={label}>{children}</MenuContent>
    </Menu>,
  );
  const popup = document.body.querySelector<HTMLElement>(
    `[role="menu"][aria-label="${label}"]`,
  );
  if (!popup) throw new Error(`expected an open menu labelled ${label}`);
  return popup;
}

function one<T extends Element>(list: ArrayLike<T>, what: string): T {
  if (list.length !== 1)
    throw new Error(`expected one ${what}, saw ${list.length}`);
  const [only]: T[] = Array.from(list);
  if (only === undefined) throw new Error(`expected one ${what}`);
  return only;
}

describe("Menu", () => {
  it("renders an open menu in the overlay chrome", async () => {
    await mount(
      <Menu defaultOpen>
        <MenuTrigger>Open</MenuTrigger>
        <MenuContent aria-label="Actions">
          <MenuItem>Rename</MenuItem>
        </MenuContent>
      </Menu>,
    );

    const popup = document.body.querySelector('[role="menu"]');
    expect(popup).not.toBeNull();
    expect(popup?.getAttribute("aria-label")).toBe("Actions");
    expect(popup?.className).toBe("nodrag nopan nowheel popup panel");
    expect(popup?.parentElement?.className).toBe("positioner");
  });

  it("draws an item with icon and hint", async () => {
    const popup = await openMenu(
      "Item",
      <MenuItem icon={<svg data-icon="pen" />} hint="⌘R">
        Rename
      </MenuItem>,
    );

    const item = one(popup.querySelectorAll('[role="menuitem"]'), "menuitem");
    expect(item.className).toBe("item");

    const icon = one(item.querySelectorAll("svg[data-icon='pen']"), "icon");
    const iconSlot = icon.parentElement;
    expect(iconSlot?.getAttribute("aria-hidden")).toBe("true");
    expect(iconSlot?.className).toBe("icon");

    const label = one(item.querySelectorAll("span.label"), "label");
    expect(label.textContent).toBe("Rename");

    const hint = one(item.querySelectorAll("span.hint"), "hint");
    expect(hint.textContent).toBe("⌘R");
  });

  it("marks danger and active rows", async () => {
    const danger = await openMenu("Danger", <MenuItem danger>Delete</MenuItem>);
    expect(
      one(danger.querySelectorAll('[role="menuitem"]'), "item").className,
    ).toBe("item danger");

    const active = await openMenu(
      "Active",
      <MenuItem active>Current</MenuItem>,
    );
    expect(
      one(active.querySelectorAll('[role="menuitem"]'), "item").className,
    ).toBe("item active");

    const overridden = await openMenu(
      "Overridden",
      <MenuItem
        xstyle={{ __styleName: "override" } as unknown as stylex.StyleXStyles}
      >
        Custom
      </MenuItem>,
    );
    expect(
      one(overridden.querySelectorAll('[role="menuitem"]'), "item").className,
    ).toBe("item override");

    const extra = await openMenu(
      "Extra",
      <MenuItem className="extra">Named</MenuItem>,
    );
    expect(
      one(extra.querySelectorAll('[role="menuitem"]'), "item").className,
    ).toBe("item extra");
  });

  it("runs an item's action", async () => {
    const spy = vi.fn();
    const popup = await openMenu(
      "Runs",
      <MenuItem onClick={spy}>Rename</MenuItem>,
    );

    const item = one(
      popup.querySelectorAll<HTMLElement>('[role="menuitem"]'),
      "menuitem",
    );
    await act(async () => item.click());

    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("toggles a checkbox row", async () => {
    const spy = vi.fn();
    function Toggle({ onChange }: { onChange: (checked: boolean) => void }) {
      const [checked, setChecked] = React.useState(false);
      return (
        <Menu defaultOpen>
          <MenuTrigger>Open</MenuTrigger>
          <MenuContent>
            <MenuCheckboxItem
              checked={checked}
              closeOnClick={false}
              onCheckedChange={(next) => {
                setChecked(next);
                onChange(next);
              }}
            >
              Starts a workflow
            </MenuCheckboxItem>
          </MenuContent>
        </Menu>
      );
    }

    await mount(<Toggle onChange={spy} />);
    const row = one(
      document.body.querySelectorAll<HTMLElement>('[role="menuitemcheckbox"]'),
      "menuitemcheckbox",
    );
    expect(row.getAttribute("aria-checked")).toBe("false");
    expect(row.className).toBe("item");

    await act(async () => row.click());

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith(true);
    expect(row.getAttribute("aria-checked")).toBe("true");
  });

  it("checks the chosen radio row", async () => {
    const popup = await openMenu(
      "Choice",
      <MenuRadioGroup value="b" onValueChange={() => {}}>
        <MenuRadioItem value="a">Alpha</MenuRadioItem>
        <MenuRadioItem value="b">Beta</MenuRadioItem>
      </MenuRadioGroup>,
    );

    const rows = Array.from(
      popup.querySelectorAll<HTMLElement>('[role="menuitemradio"]'),
    );
    expect(rows).toHaveLength(2);
    expect(rows.map((row) => row.textContent)).toEqual(["Alpha", "Beta"]);
    expect(rows[0]?.getAttribute("aria-checked")).toBe("false");
    expect(rows[1]?.getAttribute("aria-checked")).toBe("true");
    expect(rows[0]?.className).toBe("item");
    expect(rows[1]?.className).toBe("item");
  });

  it("separates and labels groups", async () => {
    const popup = await openMenu(
      "Groups",
      <>
        <MenuGroup>
          <MenuLabel>Add</MenuLabel>
          <MenuItem>Text</MenuItem>
        </MenuGroup>
        <MenuSeparator />
      </>,
    );

    const separator = one(
      popup.querySelectorAll('[role="separator"]'),
      "separator",
    );
    expect(separator.className).toBe("separator");

    const heading = one(popup.querySelectorAll(".groupLabel"), "group label");
    expect(heading.textContent).toBe("Add");
  });

  it("opens a submenu from its trigger", async () => {
    await mount(
      <Menu defaultOpen>
        <MenuTrigger>Open</MenuTrigger>
        <MenuContent aria-label="Add">
          <MenuSubmenu>
            <MenuSubmenuTrigger icon={<svg data-icon="plus" />}>
              Add node
            </MenuSubmenuTrigger>
            <MenuContent>
              <MenuItem>Text source</MenuItem>
            </MenuContent>
          </MenuSubmenu>
        </MenuContent>
      </Menu>,
    );

    const trigger = one(
      document.body.querySelectorAll<HTMLElement>('[role="menuitem"]'),
      "submenu trigger",
    );
    expect(trigger.textContent).toBe("Add node");
    expect(trigger.className).toBe("item");
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
    expect(trigger.querySelector("svg.chevron")).not.toBeNull();
  });
});
