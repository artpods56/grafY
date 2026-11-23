// Which parts of the component kit the app actually leans on.
//
// The kit lab draws every size and variant the types declare. That is the wrong
// thing to look at first: a variant with zero call sites and one with fifty get
// the same amount of screen. This prints the other axis — how often each option
// is chosen, and how often it is left unset and so comes from the kit's default.
//
//   bun apps/web/src/sandbox/spikes/ui-kit/usage.mjs
//
// Run it from anywhere; it walks `apps/web/src` relative to this file. It counts
// the attribute on the opening tag, so a size passed through a variable is
// counted as unset rather than guessed at.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const COMPONENTS = [
  "Button",
  "ButtonLink",
  "IconButton",
  "Checkbox",
  "Switch",
  "Slider",
  "Select",
  "Field",
  "ColorWell",
  "ColorField",
  "SegmentedControl",
  "Notice",
  "Surface",
];

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, "../../..");

function sourceFiles(dir, found = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      sourceFiles(path, found);
    } else if (entry.endsWith(".tsx") || entry.endsWith(".ts")) {
      // Tests assert on the kit; the sandbox is the lab itself. Neither is a
      // call site a designer or a reviewer is trying to predict.
      if (!entry.includes(".test.") && !path.startsWith(join(SRC, "sandbox"))) {
        found.push(path);
      }
    }
  }
  return found;
}

/**
 * Drop the contents of `{…}` blocks from an attribute span.
 *
 * A control passed as a prop belongs to itself: `action={<Button variant="ghost" />}`
 * is a Notice with no variant and a Button with one. Without this the Notice
 * swallows the Button's props, and both get counted.
 */
function outsideInterpolations(attributes) {
  let kept = "";
  let depth = 0;
  for (const char of attributes) {
    if (char === "{") {
      depth += 1;
    } else if (char === "}") {
      depth = Math.max(0, depth - 1);
    } else if (depth === 0) {
      kept += char;
    }
  }
  return kept;
}

/** The attribute span of an opening tag, tracking braces so `xstyle={{...}}` ends it correctly. */
function attributesOf(text, openIndex) {
  let depth = 0;
  for (let i = openIndex + 1; i < text.length; i += 1) {
    const char = text[i];
    if (char === "{") depth += 1;
    else if (char === "}") depth -= 1;
    else if (char === ">" && depth === 0) return text.slice(openIndex + 1, i);
  }
  return "";
}

const rows = new Map();

for (const path of sourceFiles(SRC)) {
  const text = readFileSync(path, "utf8");
  const tagStart = new RegExp(`<(${COMPONENTS.join("|")})(?=[\\s/>])`, "g");
  for (const match of text.matchAll(tagStart)) {
    const component = match[1];
    const attributes = outsideInterpolations(
      attributesOf(text, match.index + match[0].length - 1),
    );
    for (const prop of ["variant", "size"]) {
      const key = `${component}.${prop}`;
      if (!rows.has(key)) {
        rows.set(key, { chosen: new Map(), unset: 0, calls: 0 });
      }
      const row = rows.get(key);
      row.calls += 1;
      const literal = new RegExp(`${prop}="([^"]+)"`).exec(attributes);
      if (literal) {
        row.chosen.set(literal[1], (row.chosen.get(literal[1]) ?? 0) + 1);
      } else {
        row.unset += 1;
      }
    }
  }
}

console.log("| component | sites | chosen explicitly | left to the default |");
console.log("| --- | --- | --- | --- |");
for (const [key, row] of [...rows].sort((a, b) => b[1].calls - a[1].calls)) {
  const [component, prop] = key.split(".");
  const chosen = [...row.chosen].sort((a, b) => b[1] - a[1]);
  const spread = chosen
    .map(([value, count]) => `\`${value}\` ${count}`)
    .join(", ");
  console.log(
    `| ${component} \`${prop}\` | ${row.calls} | ${spread || "—"} | ${row.unset} |`,
  );
}
