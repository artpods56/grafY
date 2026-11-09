// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import * as stylex from "@stylexjs/stylex";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Field, TextArea, TextInput } from "./field";

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

async function typeInto(
  element: HTMLInputElement | HTMLTextAreaElement,
  value: string,
) {
  const prototype =
    element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const setValue = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  await act(async () => {
    setValue?.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function Controlled({
  onChange,
  area = false,
}: {
  onChange: (value: string) => void;
  area?: boolean;
}) {
  const [value, setValue] = React.useState("");
  return (
    <Field label="Name">
      {area ? (
        <TextArea
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            onChange(event.target.value);
          }}
        />
      ) : (
        <TextInput
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            onChange(event.target.value);
          }}
        />
      )}
    </Field>
  );
}

describe("Field", () => {
  it("ties the label to the input", async () => {
    const container = await mount(
      <Field label="Name">
        <TextInput value="" onChange={() => {}} />
      </Field>,
    );

    const label = container.querySelector("label");
    const input = container.querySelector("input");

    expect(label?.htmlFor).toBeTruthy();
    expect(label?.htmlFor).toBe(input?.id);
    expect(label?.textContent).toBe("Name");
  });

  it("describes the input with its description", async () => {
    const container = await mount(
      <Field label="Endpoint" description="Write-only">
        <TextInput value="" onChange={() => {}} />
      </Field>,
    );

    const input = container.querySelector("input");
    const description = Array.from(
      container.querySelectorAll<HTMLElement>("[id]"),
    ).find((element) => element.textContent === "Write-only");

    expect(description?.id).toBeTruthy();
    expect(input?.getAttribute("aria-describedby") ?? "").toContain(
      description?.id ?? "",
    );
  });

  it("describes the control with its error instead of its hint", async () => {
    const container = await mount(
      <Field
        label="Email"
        description="Never shown"
        error="No such person in this team"
      >
        <TextInput value="" onChange={() => {}} />
      </Field>,
    );

    const input = container.querySelector("input");
    const error = container.querySelector<HTMLElement>('[role="alert"]');

    expect(error?.textContent).toBe("No such person in this team");
    expect(container.textContent).not.toContain("Never shown");
    expect(input?.getAttribute("aria-describedby") ?? "").toContain(
      error?.id ?? "\u0000",
    );
    expect(input?.getAttribute("aria-invalid")).toBe("true");
    // The label must still reach the control once an error is on the field.
    expect(container.querySelector("label")?.htmlFor).toBe(input?.id);
  });

  it("shows the aside in the label row", async () => {
    const container = await mount(
      <Field label="Name" aside={<span>Configured</span>}>
        <TextInput value="" onChange={() => {}} />
      </Field>,
    );

    const [aside] = Array.from(container.querySelectorAll("span")).filter(
      (element) => element.textContent === "Configured",
    );
    const label = container.querySelector("label");

    expect(aside?.textContent).toBe("Configured");
    expect(aside && label?.parentElement?.contains(aside)).toBe(true);
  });

  it("disables the control with the field", async () => {
    const container = await mount(
      <Field label="Name" disabled>
        <TextInput value="" onChange={() => {}} />
      </Field>,
    );

    expect(container.querySelector("input")?.disabled).toBe(true);
  });
});

describe("TextInput", () => {
  it("passes native props through", async () => {
    const container = await mount(
      <Field label="Key">
        <TextInput
          type="password"
          placeholder="Enter key"
          aria-label="API key"
          spellCheck={false}
          autoComplete="off"
          data-1p-ignore
          value=""
          onChange={() => {}}
        />
      </Field>,
    );

    const input = container.querySelector("input");

    expect(input?.type).toBe("password");
    expect(input?.placeholder).toBe("Enter key");
    expect(input?.getAttribute("aria-label")).toBe("API key");
    expect(input?.getAttribute("spellcheck")).toBe("false");
    expect(input?.getAttribute("autocomplete")).toBe("off");
    expect(input?.hasAttribute("data-1p-ignore")).toBe(true);
  });

  it("reports typing", async () => {
    const spy = vi.fn();
    const container = await mount(<Controlled onChange={spy} />);
    const input = container.querySelector("input");
    expect(input).toBeInstanceOf(HTMLInputElement);

    await typeInto(input as HTMLInputElement, "hello");

    expect(spy).toHaveBeenCalledWith("hello");
    expect((input as HTMLInputElement).value).toBe("hello");
  });

  it("composes its classes", async () => {
    const plain = await mount(
      <Field label="x">
        <TextInput value="" onChange={() => {}} />
      </Field>,
    );
    expect(plain.querySelector("input")?.className).toBe("control");

    const monospaced = await mount(
      <Field label="x">
        <TextInput mono value="" onChange={() => {}} />
      </Field>,
    );
    expect(monospaced.querySelector("input")?.className).toBe("control mono");

    const withClass = await mount(
      <Field label="x">
        <TextInput className="nodrag" value="" onChange={() => {}} />
      </Field>,
    );
    expect(withClass.querySelector("input")?.className).toBe("control nodrag");

    const rootWithClass = await mount(
      <Field label="x" className="nodrag nopan nowheel">
        <TextInput value="" onChange={() => {}} />
      </Field>,
    );
    // React Flow looks up from the event target, so the root carries these for
    // the label row as well as for the control inside it.
    expect(rootWithClass.firstElementChild?.className).toBe(
      "root nodrag nopan nowheel",
    );

    const withXstyle = await mount(
      <Field label="x">
        <TextInput
          xstyle={{ __styleName: "override" } as unknown as stylex.StyleXStyles}
          value=""
          onChange={() => {}}
        />
      </Field>,
    );
    expect(withXstyle.querySelector("input")?.className).toBe(
      "control override",
    );
  });
});

describe("TextArea", () => {
  it("renders a labelled textarea", async () => {
    const container = await mount(
      <Field label="Instructions">
        <TextArea value="" onChange={() => {}} />
      </Field>,
    );

    const textarea = container.querySelector("textarea");
    const label = container.querySelector("label");

    expect(textarea).toBeInstanceOf(HTMLTextAreaElement);
    expect(textarea?.getAttribute("rows")).toBe("4");
    expect(textarea?.className).toBe("control textarea");
    expect(textarea?.id).toBeTruthy();
    expect(label?.htmlFor).toBe(textarea?.id);
    expect(container.querySelector("input")).toBeNull();
  });

  it("takes rows and reports typing", async () => {
    const container = await mount(
      <Field label="x">
        <TextArea rows={6} value="" onChange={() => {}} />
      </Field>,
    );
    expect(container.querySelector("textarea")?.getAttribute("rows")).toBe("6");

    const spy = vi.fn();
    const typed = await mount(<Controlled area onChange={spy} />);
    const textarea = typed.querySelector("textarea");
    expect(textarea).toBeInstanceOf(HTMLTextAreaElement);

    await typeInto(textarea as HTMLTextAreaElement, "be brief");

    expect(spy).toHaveBeenCalledWith("be brief");
  });

  it("shrinks itself and the control it is given at the dense step", async () => {
    const container = await mount(
      <Field label="Stroke width" size="dense">
        <TextInput value="" onChange={() => {}} />
      </Field>,
    );

    expect(container.querySelector("label")?.className).toBe(
      "label labelDense",
    );
    expect(container.querySelector("input")?.className).toBe(
      "control controlDense",
    );
  });

  it("leaves a control that chose its own size alone", async () => {
    const container = await mount(
      <Field label="Stroke width" size="dense">
        <TextInput size="md" value="" onChange={() => {}} />
      </Field>,
    );

    expect(container.querySelector("input")?.className).toBe("control");
  });

  it("keeps a dense textarea multiline", async () => {
    const container = await mount(
      <Field label="Notes" size="dense">
        <TextArea value="" onChange={() => {}} />
      </Field>,
    );

    expect(container.querySelector("textarea")?.className).toBe(
      "control textarea controlDense textareaDense",
    );
  });

  it("forwards its ref to the textarea", async () => {
    const ref = React.createRef<HTMLTextAreaElement>();

    await mount(
      <Field label="x">
        <TextArea ref={ref} value="" onChange={() => {}} />
      </Field>,
    );

    expect(ref.current).toBeInstanceOf(HTMLTextAreaElement);
  });
});
