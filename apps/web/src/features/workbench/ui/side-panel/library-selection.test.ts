import { describe, expect, it } from "vitest";

import type { LibraryFolder, PlacedLibraryItem } from "@/lib/api";

import {
  applyLibrarySelection,
  emptyLibrarySelection,
  libraryBulkDeleteSummary,
  libraryClickGesture,
  librarySelectionSummary,
  orderedLibrarySelection,
  pruneLibrarySelection,
  removeFromLibrarySelection,
  type LibrarySelection,
} from "./library-selection";
import { buildLibraryTree, flattenLibraryRows } from "./library-tree";

const TREE_ORDER = ["a", "b", "c", "d", "e"];

function select(
  current: LibrarySelection,
  artifactId: string,
  gesture: "plain" | "toggle" | "range",
  visible: readonly string[] = TREE_ORDER,
): LibrarySelection {
  return applyLibrarySelection({
    selection: current,
    artifactId,
    gesture,
    visible,
  });
}

function selection(ids: readonly string[], anchor: string | null = null) {
  return { ids: [...ids], anchor } satisfies LibrarySelection;
}

describe("libraryClickGesture", () => {
  it("separates the three gestures the tree answers", () => {
    expect(libraryClickGesture({})).toBe("plain");
    expect(libraryClickGesture({ metaKey: true })).toBe("toggle");
    expect(libraryClickGesture({ ctrlKey: true })).toBe("toggle");
    expect(libraryClickGesture({ shiftKey: true })).toBe("range");
  });

  it("treats the operating systems alike", () => {
    expect(libraryClickGesture({ metaKey: true, shiftKey: true })).toBe(
      "range",
    );
    expect(libraryClickGesture({ ctrlKey: true, shiftKey: true })).toBe(
      "range",
    );
  });
});

describe("applyLibrarySelection", () => {
  it("a plain click is the only one that starts over", () => {
    const start = selection(["a", "c"], "a");

    expect(select(start, "d", "plain")).toEqual(selection(["d"], "d"));
  });

  it("adds rows one at a time, each one becoming where a range starts", () => {
    let current = emptyLibrarySelection;
    current = select(current, "c", "plain");
    expect(current).toEqual(selection(["c"], "c"));

    current = select(current, "a", "toggle");
    expect(current).toEqual(selection(["c", "a"], "a"));

    current = select(current, "e", "toggle");
    expect(current).toEqual(selection(["c", "a", "e"], "e"));
  });

  it("takes a toggle back out without disturbing the other rows", () => {
    const start = selection(["c", "a", "e"], "c");

    expect(select(start, "a", "toggle")).toEqual(selection(["c", "e"], "a"));
    // Removing the last row leaves nothing behind, anchor included.
    expect(select(selection(["c"], "c"), "c", "toggle")).toEqual(
      emptyLibrarySelection,
    );
  });

  it("measures a range from the anchor, in either direction", () => {
    const start = selection(["d"], "d");

    expect(select(start, "b", "range")).toEqual(
      selection(["b", "c", "d"], "d"),
    );
    // The anchor holds its place, so the next shift click measures from the same
    // row and replaces what the last range had selected.
    expect(select(select(start, "b", "range"), "e", "range")).toEqual(
      selection(["d", "e"], "d"),
    );
  });

  it("a shift click with no anchor selects the row it landed on", () => {
    expect(select(emptyLibrarySelection, "c", "range")).toEqual(
      selection(["c"], "c"),
    );
  });

  it("counts a range in the order the tree shows, not the order of the data", () => {
    // The same five artifacts, listed bottom to top on screen.
    const reversed = [...TREE_ORDER].reverse();
    const start = selection(["b"], "b");

    // `d` sits above `b` here, and the range comes back top to bottom.
    expect(select(start, "d", "range", reversed).ids).toEqual(["d", "c", "b"]);
  });

  it("counts a range over the rows on screen only", () => {
    // A folder is collapsed, or a filter hides these: d is nowhere to be clicked.
    const onScreen = ["a", "b", "c", "e"];
    const start = selection(["a"], "a");

    const next = select(start, "e", "range", onScreen);
    expect(next.ids).toEqual(["a", "b", "c", "e"]);
    expect(next.ids).not.toContain("d");
  });

  it("starts over when the anchor the range would measure from is gone", () => {
    // A refresh took the anchor away; the shift click lands on a row that is
    // still there, and selects it rather than everything above it.
    expect(
      select(selection(["gone"], "gone"), "c", "range", TREE_ORDER),
    ).toEqual(selection(["c"], "c"));
  });
});

describe("pruneLibrarySelection", () => {
  it("drops rows that are gone and the anchor with them", () => {
    const pruned = pruneLibrarySelection(
      selection(["a", "b", "c"], "b"),
      new Set(["a", "c"]),
    );

    expect(pruned.ids).toEqual(["a", "c"]);
    expect(pruned.anchor).toBeNull();
  });

  it("keeps an anchor that is still there", () => {
    const pruned = pruneLibrarySelection(
      selection(["a", "b", "c"], "a"),
      new Set(["a", "c"]),
    );

    expect(pruned).toEqual(selection(["a", "c"], "a"));
  });

  it("hands back the same selection when a refresh changed nothing", () => {
    const start = selection(["a", "b"], "a");
    const pruned = pruneLibrarySelection(start, new Set(["a", "b", "c"]));

    expect(pruned).toBe(start);
  });
});

describe("removeFromLibrarySelection", () => {
  const picked: LibrarySelection = { ids: ["a", "b", "c"], anchor: "b" };

  it("takes the listed ids out and keeps the rest", () => {
    expect(removeFromLibrarySelection(picked, ["a", "c"])).toEqual({
      ids: ["b"],
      anchor: "b",
    });
  });

  it("forgets an anchor that went with them", () => {
    expect(removeFromLibrarySelection(picked, ["b"])).toEqual({
      ids: ["a", "c"],
      anchor: null,
    });
  });

  it("is empty once everything is gone", () => {
    expect(removeFromLibrarySelection(picked, ["a", "b", "c"])).toBe(
      emptyLibrarySelection,
    );
  });

  it("returns the same selection when none of them were in it", () => {
    expect(removeFromLibrarySelection(picked, ["z"])).toBe(picked);
  });
});

describe("orderedLibrarySelection", () => {
  it("puts a bulk action in tree order whatever order the clicks came in", () => {
    const clicked = selection(["e", "a", "c"], "e");

    expect(orderedLibrarySelection(clicked, TREE_ORDER)).toEqual([
      "a",
      "c",
      "e",
    ]);
  });

  it("keeps a row the tree is not showing, at the end", () => {
    const selected = selection(["z", "b"], "z");

    expect(orderedLibrarySelection(selected, TREE_ORDER)).toEqual(["b", "z"]);
  });
});

describe("librarySelectionSummary", () => {
  it("counts a selection only when counting it says something", () => {
    expect(librarySelectionSummary(emptyLibrarySelection)).toBeNull();
    expect(librarySelectionSummary(selection(["a"]))).toBeNull();
    expect(librarySelectionSummary(selection(["a", "b", "c"]))).toBe(
      "3 selected",
    );
  });
});

describe("libraryBulkDeleteSummary", () => {
  it("says nothing when the whole batch went away", () => {
    expect(libraryBulkDeleteSummary(3, [])).toBeNull();
  });

  it("answers the refusal the server gave when one artifact refused", () => {
    expect(
      libraryBulkDeleteSummary(4, [
        { name: "Field study", detail: "Still used by: Field study." },
      ]),
    ).toBe("Deleted 4. 1 still used by: Field study.");
  });

  it("names every artifact that refused when more than one did", () => {
    const summary = libraryBulkDeleteSummary(2, [
      { name: "sales.csv", detail: "Still used by: Sales" },
      { name: "map.png", detail: "Still used by: Salt maps" },
    ]);

    expect(summary).toBe(
      "Deleted 2. 2 refused — sales.csv: Still used by: Sales; map.png: Still used by: Salt maps.",
    );
  });

  it("says so when nothing at all was deleted", () => {
    const summary = libraryBulkDeleteSummary(0, [
      { name: "sales.csv", detail: "Still used by: Sales" },
      { name: "map.png", detail: "Still used by: Salt maps" },
    ]);

    expect(summary).toContain("Nothing deleted. 2 refused");
  });

  it("keeps a long list of refusals to three names and a count", () => {
    const summary = libraryBulkDeleteSummary(
      1,
      ["a", "b", "c", "d", "e"].map((id) => ({
        name: id,
        detail: "Still used by: Sales",
      })),
    );

    expect(summary).toBe(
      "Deleted 1. 5 refused — a: Still used by: Sales; b: Still used by: Sales; c: Still used by: Sales; 2 more.",
    );
  });

  it("cuts a long explanation instead of letting it push the footer off", () => {
    const summary = libraryBulkDeleteSummary(0, [
      { name: "a", detail: "Still used by: Sales" },
      {
        name: "b",
        detail: `Still used by: ${"pipeline ".repeat(20)}`.trim(),
      },
    ]);

    expect(summary).toContain("…");
    expect(summary!.length).toBeLessThan(200);
  });
});

describe("selection over the rows the Library actually renders", () => {
  const folders: LibraryFolder[] = [
    {
      folder_id: "fieldwork",
      workspace_id: "w",
      parent_id: null,
      name: "Fieldwork",
      created_at: "2026-09-01T00:00:00Z",
      updated_at: "2026-09-01T00:00:00Z",
    },
  ];

  function artifact(id: string, folderId: string | null): PlacedLibraryItem {
    return {
      artifact: {
        artifact_id: id,
        artifact_type: "file.png",
        schema_version: 1,
        sha256: `hash-${id}`,
        content_url: `/v1/artifacts/${id}/content`,
        content_type: "image/png",
        byte_size: 10,
        download_formats: [],
        metadata: {},
      },
      name: id,
      provenance: {
        source: "upload",
        saved_at: "2026-09-11T12:00:00Z",
        original_filename: `${id}.png`,
      },
      run: null,
      folder_id: folderId,
    };
  }

  const items = [
    artifact("top", null),
    artifact("one", "fieldwork"),
    artifact("two", "fieldwork"),
    artifact("three", "fieldwork"),
  ];

  function onScreen(collapsed: boolean, query = ""): string[] {
    const tree = buildLibraryTree({ folders, items, query, sort: "name" });
    return flattenLibraryRows(tree, {
      collapsed: collapsed ? new Set(["folder:fieldwork"]) : new Set<string>(),
    })
      .filter((row) => row.kind === "file")
      .map((row) => (row.kind === "file" ? row.item.artifact.artifact_id : ""));
  }

  // Fieldwork holds one, three and two, sorted by name; `top` sits at the root,
  // which the tree lists after the folders.
  it("a shift range stops at a closed folder", () => {
    expect(onScreen(false)).toEqual(["one", "three", "two", "top"]);
    expect(onScreen(true)).toEqual(["top"]);

    const start = selection(["top"], "top");
    // With the folder closed there is nothing above `top` to reach, so the range
    // is the one row it landed on; open, it takes the folder's rows with it.
    expect(select(start, "top", "range", onScreen(true)).ids).toEqual(["top"]);
    expect(select(start, "one", "range", onScreen(false)).ids).toEqual([
      "one",
      "three",
      "two",
      "top",
    ]);
  });

  it("a shift range stops at what the filter hides", () => {
    expect(onScreen(false, "t")).toEqual(["three", "two", "top"]);

    const start = selection(["top"], "top");
    const next = select(start, "three", "range", onScreen(false, "t"));
    expect(next.ids).toEqual(["three", "two", "top"]);
    expect(next.ids).not.toContain("one");
  });
});
