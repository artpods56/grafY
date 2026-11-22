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
 * 4. `features/workbench` is a set of vertical slices with an explicit allowed-import
 *    matrix, so a card change cannot reach into the collaboration transport.
 * 5. An extracted `*-reducer.ts` state machine stays framework-free, so it is testable
 *    without a renderer and reusable from another host.
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
    const specifier = match[1];
    if (!specifier) continue;
    const resolved = resolveSpecifier(file, specifier);
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
      if (!frame) break;
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

const WORKBENCH = "features/workbench";

/** The vertical slices the workbench is allowed to be made of. */
const WORKBENCH_SLICES = [
  "agents",
  "artifacts",
  "authoring",
  "cell-canvas",
  "collaboration",
  "config-ui",
  "execution",
  "shell",
  "test",
];

/**
 * Which slices each slice may import, besides itself. Only `shell` composes,
 * so it is the sole slice allowed to reach `cell-canvas` (the canvas engine),
 * and nothing imports `shell` or `test`. `test` is shared test support and
 * imports no product code at all.
 */
const SLICE_IMPORTS: Record<string, string[]> = {
  shell: WORKBENCH_SLICES.filter((slice) => slice !== "test"),
  "cell-canvas": ["cell-canvas", "artifacts", "authoring", "config-ui"],
  artifacts: ["artifacts", "authoring", "config-ui", "agents"],
  authoring: ["authoring", "artifacts", "config-ui"],
  "config-ui": ["config-ui", "artifacts", "authoring"],
  execution: ["execution", "authoring", "collaboration", "config-ui"],
  collaboration: [
    "collaboration",
    "agents",
    "artifacts",
    "authoring",
    "execution",
  ],
  agents: ["agents", "artifacts", "authoring"],
  test: [],
};

/**
 * `features/workbench/routes.ts` is the feature's own route table and a leaf, so the two
 * slices that build links may read it. The feature barrel `index.ts` is outward-facing:
 * nothing inside the feature may import it, or every slice would close a cycle through it.
 */
const WORKBENCH_ROUTE_TABLE = `${WORKBENCH}/routes.ts`;
const WORKBENCH_ROUTE_READERS = ["collaboration", "shell"];

/** `agents`, for `features/workbench/agents/stream.ts`; `null` outside the feature. */
function workbenchSlice(module: string): string | null {
  if (!module.startsWith(`${WORKBENCH}/`)) return null;
  const rest = module.slice(WORKBENCH.length + 1);
  if (!rest.includes("/")) return "root";
  return rest.slice(0, rest.indexOf("/"));
}

/** A reducer the framework-free rule cannot apply to: the React host that runs them. */
const REDUCER_REACT_HOST = "lib/state/use-effect-reducer.ts";

const UI_FRAMEWORK_PACKAGES = ["react", "react-dom", "next"];

function importsUiFramework(file: string): string[] {
  const offenders: string[] = [];
  for (const [, specifier] of readFileSync(file, "utf8").matchAll(
    IMPORT_SPECIFIER,
  )) {
    if (!specifier) continue;
    const bare = specifier.split("/").slice(0, 2).join("/");
    const isUi = UI_FRAMEWORK_PACKAGES.some(
      (pkg) => specifier === pkg || bare === pkg || bare.startsWith(`${pkg}/`),
    );
    if (isUi) offenders.push(specifier);
  }
  return offenders;
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

  it("keeps the web app free of React Flow and its handle/node shims", () => {
    const retiredShims =
      /\b(?:encodeHandleId|decodeHandleId|canonicalHandleId|CanvasNodeBase|CanvasEdgeBase|CanvasConnection|CanvasNodeChange|CanvasEdgeChange|WORKFLOW_NODE_TYPE|WORKFLOW_EDGE_TYPE)\b/;
    const offenders: string[] = [];
    for (const file of allSourceFiles(SRC_ROOT)) {
      const rel = relative(file);
      if (rel === "architecture.test.ts") continue;
      const source = readFileSync(file, "utf8");
      for (const [, specifier] of source.matchAll(IMPORT_SPECIFIER)) {
        if (specifier?.startsWith("@xyflow/")) {
          offenders.push(`${rel} -> ${specifier}`);
        }
      }
      const shimMatch = source.match(retiredShims);
      if (shimMatch) {
        offenders.push(`${rel} (${shimMatch[0]})`);
      }
    }
    expect(offenders).toEqual([]);
    const manifest = readFileSync(
      path.resolve(SRC_ROOT, "../package.json"),
      "utf8",
    );
    expect(manifest).not.toContain('"@xyflow/react"');
  });

  it("reaches the generated OpenAPI types only through lib/api/contract.ts", () => {
    const generated = `${GENERATED}/grafy`;
    const offenders = allSourceFiles(SRC_ROOT)
      .filter((file) => relative(file) !== "lib/api/contract.ts")
      .filter((file) => directImports(file).includes(generated))
      .map(relative);
    expect(offenders).toEqual([]);
  });

  it("keeps features/workbench split into exactly its vertical slices", () => {
    const workbenchRoot = path.join(SRC_ROOT, WORKBENCH);
    const folders = readdirSync(workbenchRoot)
      .filter((entry) =>
        statSync(path.join(workbenchRoot, entry)).isDirectory(),
      )
      .sort();
    expect(folders).toEqual([...WORKBENCH_SLICES].sort());
  });

  it("keeps workbench slice imports within their allowed slice boundaries", () => {
    const offenders: string[] = [];
    for (const [from, targets] of graph) {
      const slice = workbenchSlice(from);
      if (slice === null || slice === "root") continue;
      const allowed = SLICE_IMPORTS[slice];
      expect(allowed, `no rule for the ${slice} slice`).toBeDefined();
      for (const to of targets) {
        const target = workbenchSlice(to);
        if (target === null) continue;
        if (target === "root") {
          if (
            to === WORKBENCH_ROUTE_TABLE &&
            WORKBENCH_ROUTE_READERS.includes(slice)
          ) {
            continue;
          }
          offenders.push(`${from} -> ${to} (feature root)`);
          continue;
        }
        if (allowed && !allowed.includes(target)) {
          offenders.push(`${from} -> ${to}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("keeps extracted reducers free of the UI framework", () => {
    const reducers = allSourceFiles(SRC_ROOT)
      .map((file) => relative(file))
      .filter((name) => name.endsWith("-reducer.ts"))
      .filter((name) => !name.endsWith(".test.ts"))
      .filter((name) => name !== REDUCER_REACT_HOST);
    expect(reducers.length).toBeGreaterThan(0);
    const offenders: string[] = [];
    for (const name of reducers) {
      for (const specifier of importsUiFramework(path.join(SRC_ROOT, name))) {
        offenders.push(`${name} -> ${specifier}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
