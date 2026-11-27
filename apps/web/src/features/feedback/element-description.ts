import type { FeedbackElement } from "@/lib/api/contract";

import type { PickedTarget } from "./feedback-reducer";

/** Marks the picker's own chrome, so it is never picked and never photographed. */
export const FEEDBACK_UI_ATTRIBUTE = "data-feedback-ui";

/** What a person means when they point inside it: the button, not its icon. */
const MEANINGFUL_SELECTOR = [
  "button",
  "a[href]",
  "input",
  "select",
  "textarea",
  "label",
  "summary",
  '[role]:not([role="presentation"]):not([role="none"]):not([role="group"])',
  "[aria-label]",
  "[data-testid]",
  "[data-card-id]",
].join(",");

const MAX_ANCESTOR_STEPS = 6;
const MAX_SELECTOR_PARTS = 6;
const MAX_TEXT = 200;
const MAX_NAME_LABEL = 60;

const CARD_KIND_NAMES: Record<string, string> = {
  operator: "Node",
  artifact: "Artifact card",
  collection: "Sequence card",
  annotation: "Note",
  agent: "Agent",
};

const ROLE_NAMES: Record<string, string> = {
  button: "Button",
  link: "Link",
  textbox: "Text field",
  combobox: "Dropdown",
  checkbox: "Checkbox",
  switch: "Switch",
  slider: "Slider",
  tab: "Tab",
  menuitem: "Menu item",
  dialog: "Dialog",
  radio: "Option",
  img: "Image",
  heading: "Heading",
  navigation: "Navigation",
};

const TAG_NAMES: Record<string, string> = {
  h1: "Heading",
  h2: "Heading",
  h3: "Heading",
  h4: "Heading",
  img: "Image",
  svg: "Graphic",
  canvas: "Drawing",
  table: "Table",
  td: "Table cell",
  th: "Table header",
  p: "Text",
  span: "Text",
};

/** The page element under a point, looking through the picker's own layer. */
export function elementAtPoint(x: number, y: number): Element | null {
  for (const element of document.elementsFromPoint(x, y)) {
    if (element.closest(`[${FEEDBACK_UI_ATTRIBUTE}]`)) continue;
    return element;
  }
  return null;
}

/**
 * The nearest ancestor a person means when they point inside it: a button rather
 * than the icon in it, a canvas card rather than one of its text runs.
 */
export function meaningfulTarget(hit: Element): Element {
  let candidate: Element | null = hit;
  for (let step = 0; candidate && step <= MAX_ANCESTOR_STEPS; step += 1) {
    if (candidate.matches(MEANINGFUL_SELECTOR)) return candidate;
    candidate = candidate.parentElement;
  }
  return hit.closest("[data-card-id]") ?? hit;
}

function squash(value: string | null | undefined, max: number): string | null {
  const text = (value ?? "").replace(/\s+/g, " ").trim();
  if (text === "") return null;
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function accessibleLabel(element: Element): string | null {
  const labelledBy = element.getAttribute("aria-labelledby");
  if (labelledBy) {
    const text = labelledBy
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" ");
    const label = squash(text, MAX_TEXT);
    if (label) return label;
  }
  for (const attribute of ["aria-label", "title", "alt", "placeholder"]) {
    const label = squash(element.getAttribute(attribute), MAX_TEXT);
    if (label) return label;
  }
  if (
    element instanceof HTMLInputElement ||
    element instanceof HTMLTextAreaElement ||
    element instanceof HTMLSelectElement
  ) {
    return squash(element.labels?.[0]?.textContent, MAX_TEXT);
  }
  return null;
}

function implicitRole(element: Element): string | null {
  const tag = element.tagName.toLowerCase();
  if (tag === "button") return "button";
  if (tag === "a" && element.hasAttribute("href")) return "link";
  if (tag === "select") return "combobox";
  if (tag === "textarea") return "textbox";
  if (tag === "input") {
    const type = (element.getAttribute("type") ?? "text").toLowerCase();
    if (type === "checkbox" || type === "radio") return type;
    if (type === "range") return "slider";
    if (type === "button" || type === "submit") return "button";
    return "textbox";
  }
  return null;
}

/** Ids React makes up (`:r1:`, `«r1»`) change between visits, so they never anchor a path. */
function stableId(element: Element): string | null {
  const id = element.id;
  if (!id || /[:«»]/.test(id)) return null;
  return id;
}

function cssPath(element: Element): string {
  const parts: string[] = [];
  let current: Element | null = element;
  while (
    current &&
    current !== document.documentElement &&
    parts.length < MAX_SELECTOR_PARTS
  ) {
    const id = stableId(current);
    if (id) {
      parts.unshift(`[id="${id.replaceAll('"', '\\"')}"]`);
      break;
    }
    const testId = current.getAttribute("data-testid");
    if (testId) {
      parts.unshift(`[data-testid="${testId.replaceAll('"', '\\"')}"]`);
      break;
    }
    const tag = current.tagName.toLowerCase();
    const parent: Element | null = current.parentElement;
    if (!parent) {
      parts.unshift(tag);
      break;
    }
    const tagName = current.tagName;
    const siblings = [...parent.children].filter(
      (child) => child.tagName === tagName,
    );
    parts.unshift(
      siblings.length > 1
        ? `${tag}:nth-of-type(${siblings.indexOf(current) + 1})`
        : tag,
    );
    current = parent;
  }
  return parts.join(" > ").slice(0, 1000) || element.tagName.toLowerCase();
}

/** Text as laid out, so separate blocks stay separate words; jsdom has no innerText. */
function visibleText(element: Element): string | null {
  if (element instanceof HTMLElement && typeof element.innerText === "string") {
    return element.innerText;
  }
  return element.textContent;
}

/** Describe the picked element for the report and name it for the person. */
export function describeTarget(element: Element): PickedTarget {
  const rect = element.getBoundingClientRect();
  const tag = element.tagName.toLowerCase();
  const role = element.getAttribute("role") ?? implicitRole(element);
  const card = element.closest("[data-card-id]");
  const label = accessibleLabel(element);
  const text = squash(visibleText(element), MAX_TEXT);
  // A card reads as one block of its contents; its first line is its title.
  const cardTitle =
    card === element
      ? squash(
          visibleText(card.querySelector("[data-card-header]") ?? card)?.split(
            "\n",
            1,
          )[0],
          MAX_NAME_LABEL,
        )
      : null;
  const description: FeedbackElement = {
    tag: tag.slice(0, 32),
    selector: cssPath(element),
    label,
    role: role ? role.slice(0, 64) : null,
    test_id: element.getAttribute("data-testid")?.slice(0, 200) ?? null,
    canvas_item_id: card?.getAttribute("data-card-id")?.slice(0, 200) ?? null,
    text,
    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
  };

  const shown =
    label ?? cardTitle ?? (text && text.length <= MAX_NAME_LABEL ? text : null);
  const cardKind = card
    ? (CARD_KIND_NAMES[card.getAttribute("data-card-kind") ?? ""] ?? "Card")
    : null;
  const kind =
    card === element
      ? (cardKind ?? "Card")
      : ((role ? ROLE_NAMES[role] : undefined) ?? TAG_NAMES[tag] ?? "Area");
  let name = shown ? `${kind} “${squash(shown, MAX_NAME_LABEL)}”` : kind;
  if (card && card !== element && cardKind) name = `${name} · ${cardKind}`;
  return { element: description, name };
}
