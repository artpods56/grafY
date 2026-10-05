/**
 * Compile every source module with the project's own Babel + StyleX configuration.
 *
 * `tsc` resolves imports with TypeScript's rules and Vitest resolves them with Vite's
 * aliases, so both stay green on an import the StyleX Babel plugin cannot resolve. When
 * that happens the plugin reports "Could not resolve the path to the imported file" and
 * the production build fails, while the unit tests and the type check pass.
 *
 * The plugin only follows cross-module style imports that it can classify, so a plain
 * constant exported next to a `stylex.create` call is enough to break a module that
 * imports it. Keep shared style objects in a module that exports styles, and keep plain
 * constants file-local, which is the convention elsewhere in the app.
 *
 * Run with: npm run check:stylex
 */
import * as babel from "@babel/core";
import { readdirSync, readFileSync, statSync } from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import babelConfig from "../babel.config.js";

const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE_ROOT = path.join(APP_ROOT, "src");
const SKIPPED_DIRECTORIES = new Set(["generated", "node_modules"]);

function sourceFiles(directory) {
  const found = [];
  for (const entry of readdirSync(directory)) {
    const full = path.join(directory, entry);
    if (statSync(full).isDirectory()) {
      if (SKIPPED_DIRECTORIES.has(entry)) continue;
      found.push(...sourceFiles(full));
    } else if (/\.(ts|tsx)$/.test(entry)) {
      found.push(full);
    }
  }
  return found;
}

const files = sourceFiles(SOURCE_ROOT);
const failures = [];

for (const file of files) {
  try {
    // A file that only exists to be imported still has to compile.
    babel.transformSync(readFileSync(file, "utf8"), {
      ...babelConfig,
      filename: file,
      cwd: APP_ROOT,
    });
  } catch (error) {
    failures.push({ file, message: String(error.message).split("\n")[0] });
  }
}

for (const failure of failures) {
  console.error(
    `${path.relative(APP_ROOT, failure.file)}: ${failure.message}`,
  );
}

if (failures.length > 0) {
  console.error(
    `\n${failures.length} of ${files.length} modules fail the StyleX compile.`,
  );
  process.exit(1);
}

console.log(`StyleX compile clean: ${files.length} modules.`);
