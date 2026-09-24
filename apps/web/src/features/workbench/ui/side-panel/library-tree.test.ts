import { describe, expect, it } from "vitest";

import type { LibraryFolder, PlacedLibraryItem } from "@/lib/api";

import {
  buildLibraryTree,
  countLibraryArtifacts,
  flattenLibraryRows,
  formatLibraryByteSize,
  libraryFileDisplayName,
  libraryFileIcon,
  libraryFileSubtitle,
  libraryFolderPath,
  libraryProvenanceLine,
} from "./library-tree";

function item(
  id: string,
  overrides: Partial<{
    name: string;
    artifact_type: string;
    content_type: string;
    byte_size: number | null;
    original_filename: string | null;
    source: "upload" | "run";
    saved_at: string;
    folder_id: string | null;
  }> = {},
): PlacedLibraryItem {
  return {
    artifact: {
      artifact_id: id,
      artifact_type: overrides.artifact_type ?? "file.png",
      schema_version: 1,
      sha256: `hash-${id}`,
      content_url: `/v1/artifacts/${id}/content`,
      content_type:
        overrides.content_type === undefined
          ? "image/png"
          : overrides.content_type,
      byte_size: overrides.byte_size === undefined ? 2048 : overrides.byte_size,
    },
    name: overrides.name ?? id,
    provenance: {
      source: overrides.source ?? "upload",
      original_filename:
        overrides.original_filename === undefined
          ? `${id}.png`
          : overrides.original_filename,
      saved_at: overrides.saved_at ?? "2026-01-01T00:00:00Z",
    },
    folder_id: overrides.folder_id ?? null,
  };
}

function folder(
  id: string,
  name: string,
  parentId: string | null,
): LibraryFolder {
  return {
    folder_id: id,
    workspace_id: "ws",
    parent_id: parentId,
    name,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("buildLibraryTree", () => {
  it("nests user folders to any depth", () => {
    const tree = buildLibraryTree({
      folders: [
        folder("field", "Fieldwork", null),
        folder("sep", "September", "field"),
        folder("raw", "Raw photos", "sep"),
      ],
      items: [],
    });

    const field = tree[0];
    expect(field?.kind).toBe("folder");
    expect(field?.kind === "folder" && field.nodes[0]?.key).toBe("folder:sep");

    const september = field?.kind === "folder" ? field.nodes[0] : null;
    expect(september?.kind === "folder" && september.nodes[0]?.key).toBe(
      "folder:raw",
    );
  });

  it("keeps artifacts that are not filed anywhere at the root", () => {
    const tree = buildLibraryTree({
      folders: [folder("field", "Fieldwork", null)],
      items: [item("loose"), item("filed", { folder_id: "field" })],
    });

    expect(tree.map((node) => node.key)).toEqual([
      "folder:field",
      "file:loose",
    ]);
  });

  it("lists folders before artifacts inside a folder", () => {
    const tree = buildLibraryTree({
      folders: [
        folder("field", "Fieldwork", null),
        folder("zeta", "Zeta", "field"),
      ],
      items: [item("aaa", { folder_id: "field" })],
    });

    const fieldwork = tree[0];
    expect(
      fieldwork?.kind === "folder" && fieldwork.nodes.map((n) => n.key),
    ).toEqual(["folder:zeta", "file:aaa"]);
  });

  it("counts every artifact under a folder, however deeply filed", () => {
    const tree = buildLibraryTree({
      folders: [
        folder("field", "Fieldwork", null),
        folder("sep", "September", "field"),
      ],
      items: [
        item("a", { folder_id: "field" }),
        item("b", { folder_id: "sep" }),
        item("c", { folder_id: "sep" }),
      ],
    });

    const fieldwork = tree[0];
    expect(fieldwork?.kind === "folder" && fieldwork.total).toBe(3);
  });

  it("drops folders with nothing matching under a filter", () => {
    const tree = buildLibraryTree({
      folders: [
        folder("field", "Fieldwork", null),
        folder("rep", "Reports", null),
      ],
      items: [item("plot.png", { folder_id: "rep" })],
      query: "plot",
    });

    expect(tree.map((node) => node.key)).toEqual(["folder:rep"]);
  });

  it("keeps the path to a matching artifact", () => {
    const tree = buildLibraryTree({
      folders: [
        folder("field", "Fieldwork", null),
        folder("sep", "September", "field"),
      ],
      items: [
        item("core-samples.csv", {
          folder_id: "sep",
          content_type: "text/csv",
        }),
      ],
      query: "core",
    });

    const fieldwork = tree[0];
    const september = fieldwork?.kind === "folder" ? fieldwork.nodes[0] : null;
    const sample = september?.kind === "folder" ? september.nodes[0] : null;
    expect(fieldwork?.key).toBe("folder:field");
    expect(september?.key).toBe("folder:sep");
    expect(sample?.key).toBe("file:core-samples.csv");
  });

  it("reveals a folder that matches by name", () => {
    const tree = buildLibraryTree({
      folders: [folder("field", "Fieldwork", null)],
      items: [item("photo.png", { folder_id: "field" })],
      query: "fieldwork",
    });

    const fieldwork = tree[0];
    expect(
      fieldwork?.kind === "folder" && fieldwork.nodes.map((n) => n.key),
    ).toEqual(["file:photo.png"]);
  });

  it("sorts by name or by most recently saved", () => {
    const items = [
      item("beta", { saved_at: "2026-02-01T00:00:00Z" }),
      item("alpha", { saved_at: "2026-01-01T00:00:00Z" }),
    ];

    expect(
      buildLibraryTree({ folders: [], items }).map((node) => node.key),
    ).toEqual(["file:alpha", "file:beta"]);
    expect(
      buildLibraryTree({ folders: [], items, sort: "recent" }).map(
        (node) => node.key,
      ),
    ).toEqual(["file:beta", "file:alpha"]);
  });
});

describe("flattenLibraryRows", () => {
  const folders = [
    folder("field", "Fieldwork", null),
    folder("sep", "September", "field"),
  ];
  const items = [item("a", { folder_id: "sep" }), item("loose")];

  it("walks the tree in the order the panel paints it", () => {
    const rows = flattenLibraryRows(buildLibraryTree({ folders, items }));
    expect(rows.map((row) => row.key)).toEqual([
      "folder:field",
      "folder:sep",
      "file:a",
      "file:loose",
    ]);
  });

  it("stops descending into collapsed folders", () => {
    const rows = flattenLibraryRows(buildLibraryTree({ folders, items }), {
      collapsed: new Set(["folder:field"]),
    });
    expect(rows.map((row) => row.key)).toEqual(["folder:field", "file:loose"]);
  });
});

describe("countLibraryArtifacts", () => {
  it("counts filed and root artifacts once each", () => {
    const tree = buildLibraryTree({
      folders: [folder("field", "Fieldwork", null)],
      items: [item("a", { folder_id: "field" }), item("loose")],
    });
    expect(countLibraryArtifacts(tree)).toBe(2);
  });
});

describe("libraryFileIcon", () => {
  it("follows the bytes, not the folder", () => {
    expect(libraryFileIcon(item("a"))).toBe("image");
    expect(
      libraryFileIcon(
        item("b", { artifact_type: "table.csv@1", content_type: "text/csv" }),
      ),
    ).toBe("table");
    expect(
      libraryFileIcon(
        item("c", {
          artifact_type: "scalar.text@1",
          content_type: "text/plain",
        }),
      ),
    ).toBe("text");
    expect(
      libraryFileIcon(
        item("d", {
          artifact_type: "model.weights@1",
          content_type: "application/octet-stream",
        }),
      ),
    ).toBe("model");
    expect(
      libraryFileIcon(
        item("e", {
          artifact_type: "file.blob@1",
          content_type: "application/octet-stream",
        }),
      ),
    ).toBe("other");
  });
});

describe("libraryFolderPath", () => {
  const folders = [
    folder("field", "Fieldwork", null),
    folder("sep", "September", "field"),
  ];

  it("names the route to a folder from the root", () => {
    expect(libraryFolderPath(folders, "sep")).toEqual([
      "Fieldwork",
      "September",
    ]);
    expect(libraryFolderPath(folders, null)).toEqual([]);
  });
});

describe("the rows keep the Library's file naming", () => {
  it("prefers the filename an upload arrived with", () => {
    expect(
      libraryFileDisplayName(
        item("photo", { original_filename: "IMG_0042.png" }),
      ),
    ).toBe("IMG_0042.png");
    expect(
      libraryFileDisplayName(
        item("run", {
          name: "Scan result",
          source: "run",
          original_filename: null,
        }),
      ),
    ).toBe("Scan result");
  });

  it("puts the size before where it came from", () => {
    expect(libraryFileSubtitle(item("photo", { byte_size: 2048 }))).toBe(
      "2.0 KB · uploaded",
    );
    expect(
      libraryFileSubtitle(
        item("run", {
          source: "run",
          byte_size: null,
          original_filename: null,
        }),
      ),
    ).toBe("from a run");
  });

  it("reads a run artifact's birth record from its provenance", () => {
    const runItem: PlacedLibraryItem = {
      ...item("run", { source: "run", original_filename: null }),
      provenance: {
        source: "run",
        graph_id: "g",
        graph_title: "Site survey",
        graph_revision: 4,
        node_id: "n",
        node_title: "GeoTIFF scan",
        execution_id: "e",
        saved_at: "2026-01-01T00:00:00Z",
      },
    };
    expect(libraryProvenanceLine(runItem)).toBe(
      "Site survey · GeoTIFF scan · revision 4 · from a run",
    );
  });

  it("formats byte sizes the way the folder list reads", () => {
    expect(formatLibraryByteSize(512)).toBe("512 B");
    expect(formatLibraryByteSize(2048)).toBe("2.0 KB");
    expect(formatLibraryByteSize(5_400_000)).toBe("5.1 MB");
    expect(formatLibraryByteSize(null)).toBeNull();
  });
});
