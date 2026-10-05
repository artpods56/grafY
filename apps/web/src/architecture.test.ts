import { readFileSync, readdirSync, statSync } from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * These are the structural properties that make the app cheap to change. Each one has
 * already been broken once, so it is checked here instead of in a review comment:
 *
 * 1. The module graph is acyclic. `artifact-connections.ts` and `artifact-viewer.ts`
 *    used to import each other through a shared edge type.
 * 2. A feature never imports a route or a sandbox spike. `/sandbox` is a development
 *    host that may borrow product code, never the other way round.
 * 3. The generated OpenAPI types are reachable only through `lib/api/contract.ts`, so
 *    the wire shape is named in exactly one place.
 */

const SRC_ROOT = path.resolve(__dirname);
const GENERATED = "lib/api/generated";

const SOURCE_EXTENSIONS = [".ts", ".tsx"];

function sourceFiles(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (path.relative(SRC_ROOT, full) === GENERATED) continue;
      found.push(...sourceFiles(full));
      continue;
    }
    if (SOURCE_EXTENSIONS.some((extension) => entry.endsWith(extension))) {
      found.push(full);
    }
  }
  return found;
}

const IMPORT_SPECIFIER =
  /(?:\bfrom|\bimport|\bexport)\s*\(?\s*["']([^"']+)["']/g;

function allSourceFiles(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      found.push(...allSourceFiles(full));
      continue;
    }
    if (SOURCE_EXTENSIONS.some((extension) => entry.endsWith(extension))) {
      found.push(full);
    }
  }
  return found;
}

/** Every internal module this file names in an import or export statement. */
function directImports(file: string): string[] {
  const targets: string[] = [];
  for (const match of readFileSync(file, "utf8").matchAll(IMPORT_SPECIFIER)) {
    const resolved = resolveSpecifier(file, match[1]);
    if (resolved) targets.push(relative(resolved));
  }
  return targets;
}

function resolveSpecifier(fromFile: string, specifier: string): string | null {
  let base: string;
  if (specifier.startsWith("@/")) {
    base = path.join(SRC_ROOT, specifier.slice(2));
  } else if (specifier.startsWith(".")) {
    base = path.resolve(path.dirname(fromFile), specifier);
  } else {
    return null;
  }
  const candidates = [
    base,
    ...SOURCE_EXTENSIONS.map((extension) => base + extension),
    ...SOURCE_EXTENSIONS.map((extension) =>
      path.join(base, `index${extension}`),
    ),
  ];
  for (const candidate of candidates) {
    try {
      if (statSync(candidate).isFile()) return candidate;
    } catch {
      // Not a path on disk: a package, a subpath, or a CSS import.
    }
  }
  return null;
}

function relative(file: string): string {
  return path.relative(SRC_ROOT, file).split(path.sep).join("/");
}

function buildGraph(): Map<string, string[]> {
  const files = sourceFiles(SRC_ROOT).filter(
    (file) =>
      !relative(file).endsWith(".test.tsx") &&
      !relative(file).endsWith(".test.ts"),
  );
  const known = new Set(files.map(relative));
  const graph = new Map<string, string[]>();
  for (const file of files) {
    const from = relative(file);
    const targets = new Set<string>();
    for (const to of directImports(file)) {
      if (to === from || !known.has(to)) continue;
      targets.add(to);
    }
    graph.set(from, [...targets].sort());
  }
  return graph;
}

/** The first cycle found, as the module path that closes on itself. */
function findCycle(graph: Map<string, string[]>): string[] | null {
  const visited = new Set<string>();
  const onPath = new Set<string>();
  const stack: { from: string; targets: string[]; index: number }[] = [];

  for (const start of graph.keys()) {
    if (visited.has(start)) continue;
    stack.push({ from: start, targets: graph.get(start) ?? [], index: 0 });
    visited.add(start);
    onPath.add(start);
    while (stack.length > 0) {
      const frame = stack[stack.length - 1];
      if (frame.index >= frame.targets.length) {
        stack.pop();
        onPath.delete(frame.from);
        continue;
      }
      const next = frame.targets[frame.index];
      frame.index += 1;
      if (next === undefined) continue;
      if (onPath.has(next)) {
        const cycleStart = stack.findIndex((entry) => entry.from === next);
        return [...stack.slice(cycleStart).map((entry) => entry.from), next];
      }
      if (visited.has(next)) continue;
      visited.add(next);
      onPath.add(next);
      stack.push({ from: next, targets: graph.get(next) ?? [], index: 0 });
    }
  }
  return null;
}

describe("module architecture", () => {
  const graph = buildGraph();

  it("reads every source module under src", () => {
    expect(graph.size).toBeGreaterThan(150);
  });

  it("has no import cycles", () => {
    const cycle = findCycle(graph);
    expect(cycle).toBeNull();
  });

  it("keeps features independent of routes and sandbox spikes", () => {
    const offenders: string[] = [];
    for (const [from, targets] of graph) {
      if (!from.startsWith("features/")) continue;
      for (const to of targets) {
        if (to.startsWith("app/") || to.startsWith("sandbox/")) {
          offenders.push(`${from} -> ${to}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("reaches the generated OpenAPI types only through lib/api/contract.ts", () => {
    const generated = `${GENERATED}/grafy`;
    const offenders = allSourceFiles(SRC_ROOT)
      .filter((file) => relative(file) !== "lib/api/contract.ts")
      .filter((file) => directImports(file).includes(generated))
      .map(relative);
    expect(offenders).toEqual([]);
  });
});
