// Which parts of the component kit the app actually leans on.
//
// The kit lab draws every size and variant the types declare. That is the wrong
// thing to look at first: a variant with zero call sites and one with fifty get
// the same amount of screen. This prints the other axis — how often each option
// is chosen, and how often it is not chosen at all.
//
//   bun apps/web/src/sandbox/spikes/ui-kit/usage.mjs
//
// Run it from anywhere; it walks `apps/web/src` relative to this file. Four
// things keep the counts honest:
//
// * Tests and the sandbox itself are skipped — they assert on the kit and draw
//   it, they do not use it.
// * `src/components/ui` is skipped, so the kit composing itself (`DialogContent`
//   rendering an `IconButton`) and its JSDoc examples are not call sites.
// * Comments are blanked out before scanning, and the contents of string and
//   template literals are skipped, so a `<Button variant="x" />` in a JSDoc
//   block or in a snippet string is not counted either. URLs survive intact:
//   the tokenizer never cuts a `//` out of `"https://…"`.
// * A prop written as an expression is counted as `dynamic`, and a tag carrying
//   a `{...spread}` has its un-set props counted as `spread` — those are choices
//   made somewhere this script cannot see, not decisions to take the default.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// Props worth counting per component. `variant` on a `Switch` is not a thing, so
// asking for it there only invents a row.
const COMPONENT_PROPS = {
  Button: ["variant", "size"],
  ButtonLink: ["variant", "size"],
  IconButton: ["variant", "size"],
  Notice: ["tone", "variant"],
  Surface: ["tone", "shape"],
  DialogContent: ["size"],
  MenuContent: ["side", "align"],
  Field: ["size"],
  TextInput: ["size"],
  TextArea: ["size"],
  Select: ["size"],
  Checkbox: ["size"],
  Switch: ["size"],
  Slider: ["size"],
  ColorWell: ["size"],
  ColorField: ["size"],
  SegmentedControl: ["size"],
};

const COMPONENTS = Object.keys(COMPONENT_PROPS);

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, "../../..");

function sourceFiles(dir, found = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      sourceFiles(path, found);
    } else if (entry.endsWith(".tsx") || entry.endsWith(".ts")) {
      // Tests assert on the kit; the sandbox is the lab itself; the kit folder
      // is the kit composing itself. None is a call site a designer or a
      // reviewer is trying to predict.
      const excluded =
        entry.includes(".test.") ||
        path.startsWith(join(SRC, "sandbox")) ||
        path.startsWith(join(SRC, "components", "ui"));
      if (!excluded) found.push(path);
    }
  }
  return found;
}

const QUOTES = ["'", '"', "`"];

/** Index just past the string literal that starts at `start` (its closing quote + 1). */
function skipString(text, start) {
  const quote = text[start];
  for (let i = start + 1; i < text.length; i += 1) {
    if (text[i] === "\\") i += 1;
    else if (text[i] === quote) return i + 1;
    // `${` opens an expression that may itself contain the quote character.
    else if (quote === "`" && text[i] === "$" && text[i + 1] === "{")
      i = matchBrace(text, i + 1) - 1;
  }
  return text.length;
}

/**
 * Blank every comment, and report where the string literals are.
 *
 * A state machine rather than a regex, for two reasons. `//` shows up inside
 * `"https://…"`, so cutting there would mint a fake tag out of a URL; and the
 * contents of a literal are prose rather than markup, so `<Button …>` inside a
 * prompt or a snippet string is not a call site either. Comments are replaced
 * with spaces instead of removed so every offset stays put, and a template's
 * `${…}` is left open — real JSX can be built in there.
 *
 * Returns `{ code, literals }`, `literals` holding `[start, end)` over the text
 * of each literal, quotes excluded.
 */
function maskNonCode(text) {
  // split("") not spread: an emoji is one element when spread but two UTF-16
  // units in `text`, and every offset after it would drift by one.
  const chars = text.split("");
  const literals = [];
  const stack = [{ mode: "code", depth: 0 }];
  let i = 0;

  const blank = (from, to) => {
    for (let n = from; n < to; n += 1) if (chars[n] !== "\n") chars[n] = " ";
  };

  while (i < text.length) {
    const frame = stack[stack.length - 1];
    const char = chars[i];
    const next = chars[i + 1];

    if (frame.mode === "template") {
      if (char === "\\") i += 2;
      else if (char === "`") {
        literals.push([frame.open, i]);
        stack.pop();
        i += 1;
      } else if (char === "$" && next === "{") {
        literals.push([frame.open, i]);
        stack.push({ mode: "code", depth: 0 });
        i += 2;
      } else i += 1;
      continue;
    }

    if (char === "/" && next === "/") {
      let end = i;
      while (end < text.length && chars[end] !== "\n") end += 1;
      blank(i, end);
      i = end;
    } else if (char === "/" && next === "*") {
      let end = text.indexOf("*/", i + 2);
      end = end === -1 ? text.length : end + 2;
      blank(i, end);
      i = end;
    } else if (char === "{") {
      frame.depth += 1;
      i += 1;
    } else if (char === "}") {
      // A `}` at depth 0 below the root closes a template expression.
      if (frame.depth === 0 && stack.length > 1) {
        stack.pop();
        stack[stack.length - 1].open = i + 1;
      } else frame.depth -= 1;
      i += 1;
    } else if (char === "`") {
      stack.push({ mode: "template", open: i + 1 });
      i += 1;
    } else if (char === '"' || char === "'") {
      const end = skipString(text, i);
      literals.push([i + 1, end - 1]);
      i = end;
    } else {
      i += 1;
    }
  }

  return {
    code: chars.join(""),
    literals: literals.sort((a, b) => a[0] - b[0]),
  };
}

function insideLiteral(literals, index) {
  for (const [start, end] of literals) {
    if (index < start) return false;
    if (index < end) return true;
  }
  return false;
}

/** Index of the `}` matching the `{` at `start`. */
function matchBrace(text, start) {
  let depth = 0;
  for (let i = start; i < text.length; i += 1) {
    const char = text[i];
    if (QUOTES.includes(char)) i = skipString(text, i) - 1;
    else if (char === "{") depth += 1;
    else if (char === "}") {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  return text.length;
}

/** The attribute span of the opening tag whose `<` sits at `openIndex`. */
function attributesOf(text, openIndex) {
  let depth = 0;
  for (let i = openIndex + 1; i < text.length; i += 1) {
    const char = text[i];
    if (QUOTES.includes(char)) i = skipString(text, i) - 1;
    else if (char === "{") depth += 1;
    else if (char === "}") depth -= 1;
    else if (char === ">" && depth === 0) return text.slice(openIndex + 1, i);
  }
  return "";
}

const NAME = /^[A-Za-z_$][\w$-]*/;

/**
 * The attributes of one opening tag, as `{ name, kind, value }`.
 *
 * `kind` is `literal` (a quoted string, bare or in braces), `dynamic` (any other
 * expression), `spread` (a top-level `{...x}`), or `bare` (`disabled`). Walking
 * braces whole is what keeps `action={<Button variant="ghost" />}` a Notice with
 * no variant and a Button with one.
 */
function parseAttributes(span) {
  const attrs = [];
  let i = 0;
  const space = () => {
    while (i < span.length && /\s/.test(span[i])) i += 1;
  };

  while (i < span.length) {
    const char = span[i];
    if (/\s/.test(char)) {
      i += 1;
    } else if (char === "{") {
      const end = matchBrace(span, i);
      const inner = span.slice(i + 1, end).trim();
      attrs.push({
        name: null,
        kind: inner.startsWith("...") ? "spread" : "dynamic",
        value: inner,
      });
      i = end + 1;
    } else {
      const name = NAME.exec(span.slice(i))?.[0];
      if (!name) {
        i += 1;
      } else {
        i += name.length;
        const after = i;
        space();
        if (span[i] !== "=") {
          attrs.push({ name, kind: "bare", value: null });
          if (i === after) i += 1;
          continue;
        }
        i += 1;
        space();
        const value = span[i];
        if (value === '"' || value === "'") {
          const end = skipString(span, i);
          attrs.push({
            name,
            kind: "literal",
            value: span.slice(i + 1, end - 1),
          });
          i = end;
        } else if (value === "{") {
          const end = matchBrace(span, i);
          attrs.push({ name, ...classify(span.slice(i + 1, end)) });
          i = end + 1;
        } else if (value === "<") {
          attrs.push({ name, kind: "dynamic", value: null });
          i += 1;
        } else {
          attrs.push({ name, kind: "bare", value: null });
        }
      }
    }
  }
  return attrs;
}

/** `{'x'}` / `{"x"}` are still a chosen string; anything else is an expression. */
function classify(inner) {
  const trimmed = inner.trim();
  const quote = trimmed[0];
  const plain =
    (quote === '"' || quote === "'" || quote === "`") &&
    trimmed.length > 1 &&
    trimmed.endsWith(quote) &&
    !trimmed.endsWith(`\\${quote}`) &&
    trimmed.indexOf(quote, 1) === trimmed.length - 1;
  if (plain && !trimmed.includes("${")) {
    return { kind: "literal", value: trimmed.slice(1, -1) };
  }
  if (trimmed.startsWith("...")) return { kind: "spread", value: trimmed };
  return { kind: "dynamic", value: trimmed };
}

const rows = new Map();

function rowFor(component, prop) {
  const key = `${component}.${prop}`;
  if (!rows.has(key)) {
    rows.set(key, {
      chosen: new Map(),
      dynamic: 0,
      spread: 0,
      unset: 0,
      calls: 0,
    });
  }
  return rows.get(key);
}

const TAG = new RegExp(`<(${COMPONENTS.join("|")})(?=[\\s/>])`, "g");

for (const path of sourceFiles(SRC)) {
  const { code, literals } = maskNonCode(readFileSync(path, "utf8"));
  for (const match of code.matchAll(TAG)) {
    // Markup that only exists as text — a snippet in a string — is not a call
    // site, whatever the tag looks like.
    if (insideLiteral(literals, match.index)) continue;
    const component = match[1];
    const attributes = parseAttributes(
      attributesOf(code, match.index).slice(match[0].length - 1),
    );
    const spread = attributes.some((attr) => attr.kind === "spread");

    for (const prop of COMPONENT_PROPS[component]) {
      const row = rowFor(component, prop);
      row.calls += 1;
      const attr = attributes.find((candidate) => candidate.name === prop);
      if (attr?.kind === "literal") {
        const value = attr.value || "(empty)";
        row.chosen.set(value, (row.chosen.get(value) ?? 0) + 1);
      } else if (attr?.kind === "dynamic") {
        row.dynamic += 1;
      } else if (spread) {
        row.spread += 1;
      } else {
        row.unset += 1;
      }
    }
  }
}

console.log(
  "| component | sites | chosen explicitly | dynamic / spread | left to the default |",
);
console.log("| --- | --- | --- | --- | --- |");
for (const [key, row] of [...rows].sort(
  (a, b) => b[1].calls - a[1].calls || a[0].localeCompare(b[0]),
)) {
  const [component, prop] = key.split(".");
  const chosen = [...row.chosen]
    .sort((a, b) => b[1] - a[1])
    .map(([value, count]) => `\`${value}\` ${count}`)
    .join(", ");
  const implied = [
    row.dynamic ? `dynamic ${row.dynamic}` : null,
    row.spread ? `spread ${row.spread}` : null,
  ]
    .filter(Boolean)
    .join(", ");
  console.log(
    `| ${component} \`${prop}\` | ${row.calls} | ${chosen || "—"} | ${implied || "—"} | ${row.unset} |`,
  );
}
