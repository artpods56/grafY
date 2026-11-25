// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ScalarSchemaField } from "../../config-ui/config-schema";
import { fieldDisplayTitle } from "../../config-ui/config-schema";
import type { CellConfigFieldSpec } from "../cell-contracts";
import { schemaFieldDenseRows } from "../cell-config-plan";

import { CellConfigBand } from "./CellConfigFields";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots: ReturnType<typeof createRoot>[] = [];

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
});

/** A prompt long enough that a card's 78px box is not where one reads it. */
const SYSTEM_PROMPT: ScalarSchemaField = {
  type: "string",
  name: "system_prompt",
  title: "System Prompt",
  description: "Reads the page and answers about it.",
  required: true,
  nullable: false,
  widget: "textarea",
  maxLength: 200,
  defaultValue: "You read documents.",
};

const TITLE: ScalarSchemaField = {
  type: "string",
  name: "title",
  title: "Title",
  required: true,
  nullable: false,
};

const PROMPT = "You read invoices.\nTotal the lines.\nAnswer in JSON.";

/** A band entry as the operator adapter builds one: rows from the same plan. */
function specField(
  field: ScalarSchemaField,
  rawValue: string,
): CellConfigFieldSpec {
  return {
    id: field.name,
    label: fieldDisplayTitle(field),
    kind: "schema",
    value: rawValue,
    denseRows: schemaFieldDenseRows(field, rawValue, field.name, {}),
    schemaField: field,
    rawValue,
  };
}

function mountBand(fields: readonly CellConfigFieldSpec[], editable = true) {
  const onChange = vi.fn();
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  React.act(() => {
    root.render(
      <CellConfigBand
        fields={fields}
        style={{}}
        onChange={editable ? onChange : undefined}
      />,
    );
  });
  return { container, onChange };
}

/** A textarea field and a single-line one, as one card's band holds them. */
function promptBand(editable = true) {
  return mountBand(
    [specField(SYSTEM_PROMPT, PROMPT), specField(TITLE, "Invoices")],
    editable,
  );
}

/**
 * Interactions flush with an async `act`: Base UI keeps a closed popup in the
 * tree until its exit animation settles, which only a flushed act lets it do.
 */
async function click(element: Element | null | undefined) {
  expect(element).not.toBeNull();
  await React.act(async () => {
    (element as HTMLElement).click();
  });
}

async function type(element: Element | null | undefined, value: string) {
  expect(element).not.toBeNull();
  await React.act(async () => {
    const input = element as HTMLTextAreaElement;
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function popup(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[role="dialog"]');
}

/** The modal's own editor: the card keeps a dense one behind the popup. */
function openPrompt(): HTMLTextAreaElement {
  const editor = popup()?.querySelector<HTMLTextAreaElement>(
    'textarea[aria-label="System Prompt"]',
  );
  expect(editor).not.toBeNull();
  return editor as HTMLTextAreaElement;
}

function buttonIn(scope: ParentNode, text: string): HTMLButtonElement | null {
  return (
    [...scope.querySelectorAll("button")].find(
      (button) => button.textContent === text,
    ) ?? null
  );
}

function expandControl(scope: ParentNode, field: ScalarSchemaField) {
  return scope.querySelector(
    `[aria-label="Expand ${fieldDisplayTitle(field)}"]`,
  );
}

function kitClose(): Element | null {
  return document.querySelector('button[aria-label="Close"]');
}

function stats(): string | undefined {
  return document
    .querySelector("[data-workbench-modal-footer]")
    ?.querySelector(".stats")?.textContent;
}

describe("TextareaFieldModal", () => {
  it("expands a textarea field from its label row", async () => {
    const { container } = promptBand();

    const trigger = expandControl(container, SYSTEM_PROMPT);
    expect(trigger).not.toBeNull();
    expect(trigger?.classList.contains("nodrag")).toBe(true);
    // The control rides the label row, so the field keeps the rows it counted.
    expect(
      container.querySelector('[data-config-field="system_prompt"]')?.outerHTML,
    ).toContain('data-config-rows="4"');
    expect(popup()).toBeNull();
  });

  it("gives a single-line field nothing to expand into", async () => {
    const { container } = promptBand();
    expect(expandControl(container, TITLE)).toBeNull();
  });

  it("opens with the field's title, description, and current value", async () => {
    const { container } = promptBand();
    await click(expandControl(container, SYSTEM_PROMPT));

    const dialog = popup();
    expect(dialog?.textContent).toContain("System Prompt");
    expect(dialog?.textContent).toContain(
      "Reads the page and answers about it.",
    );
    expect(openPrompt().value).toBe(PROMPT);
    expect(openPrompt().getAttribute("placeholder")).toBe(
      "You read documents.",
    );
    expect(stats()).toContain("51/200 characters · 3 lines");
  });

  it("counts as the draft changes, then applies it and closes", async () => {
    const { container, onChange } = promptBand();
    await click(expandControl(container, SYSTEM_PROMPT));

    const dialog = popup()!;
    const editor = openPrompt();
    expect(buttonIn(dialog, "Apply")?.disabled).toBe(true);

    await type(editor, "You read receipts.");
    expect(stats()).toContain("18/200 characters · 1 line");
    expect(buttonIn(dialog, "Apply")?.disabled).toBe(false);

    await click(buttonIn(dialog, "Apply"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(
      "system_prompt",
      "You read receipts.",
    );
    expect(popup()).toBeNull();
  });

  it("applies and closes on Cmd+Enter", async () => {
    const { container, onChange } = promptBand();
    await click(expandControl(container, SYSTEM_PROMPT));

    const editor = openPrompt();
    await type(editor, "You read tickets.");
    await React.act(async () => {
      editor.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          metaKey: true,
          bubbles: true,
        }),
      );
    });

    expect(onChange).toHaveBeenCalledWith("system_prompt", "You read tickets.");
    expect(popup()).toBeNull();
  });

  it("refuses to apply a draft past the field's maximum length", async () => {
    const field: ScalarSchemaField = { ...SYSTEM_PROMPT, maxLength: 5 };
    const { container, onChange } = mountBand([specField(field, "one")]);
    await click(expandControl(container, field));

    const dialog = popup()!;
    // The DOM attribute stops a person typing past the limit; the guard still
    // reads the draft the card would be handed.
    await type(
      dialog.querySelector('textarea[aria-label="System Prompt"]'),
      "way too long",
    );

    expect(stats()).toContain("12/5 characters");
    expect(dialog.querySelector('[role="alert"]')?.textContent).toContain(
      "At most 5 characters.",
    );
    expect(buttonIn(dialog, "Apply")?.disabled).toBe(true);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("asks before a close that would lose the draft, then discards", async () => {
    const { container, onChange } = promptBand();
    await click(expandControl(container, SYSTEM_PROMPT));

    await type(openPrompt(), "Unapplied work.");

    await click(kitClose());
    expect(
      document.querySelector("[data-workbench-modal-discard]")?.textContent,
    ).toContain("Unsaved changes");
    expect(popup()).not.toBeNull();

    await click(buttonIn(popup()!, "Keep editing"));
    expect(openPrompt().value).toBe("Unapplied work.");

    await click(kitClose());
    await click(buttonIn(popup()!, "Discard"));

    expect(onChange).not.toHaveBeenCalled();
    expect(popup()).toBeNull();

    // Reopening starts from what the card holds, not from the lost draft.
    await click(expandControl(container, SYSTEM_PROMPT));
    expect(openPrompt().value).toBe(PROMPT);
  });

  it("drops the draft on Cancel without writing it", async () => {
    const { container, onChange } = promptBand();
    await click(expandControl(container, SYSTEM_PROMPT));

    await type(openPrompt(), "Unapplied work.");
    await click(buttonIn(popup()!, "Cancel"));

    expect(onChange).not.toHaveBeenCalled();
    expect(popup()).toBeNull();
  });

  it("closes straight away from a modal with nothing to lose", async () => {
    const { container } = promptBand();
    await click(expandControl(container, SYSTEM_PROMPT));
    await click(kitClose());

    expect(document.querySelector("[data-workbench-modal-discard]")).toBeNull();
    expect(popup()).toBeNull();
  });

  it("reads the value without an editor on a card that cannot write it", async () => {
    const { container, onChange } = promptBand(false);
    // Reading a long prompt is not an edit, so the control stays.
    expect(expandControl(container, SYSTEM_PROMPT)).not.toBeNull();

    await click(expandControl(container, SYSTEM_PROMPT));
    const dialog = popup()!;

    expect(openPrompt().disabled).toBe(true);
    expect(buttonIn(dialog, "Apply")).toBeNull();
    expect(buttonIn(dialog, "Cancel")).toBeNull();

    await click(buttonIn(dialog, "Close"));
    expect(popup()).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
  });
});
