import { describe, expect, it } from "vitest";

import type { PlacedLibraryItem } from "@/lib/api";
import {
  ARTIFACT_DROP_DATA_TYPE,
  ARTIFACT_GROUPS_DATA_TYPE,
  readArtifactDrop,
  readArtifactDropGroups,
  writeArtifactDrop,
} from "../../model/artifact-drop";
import {
  LIBRARY_FOLDER_DATA_TYPE,
  LIBRARY_MOVE_DATA_TYPE,
  artifactDropGroups,
  dropEffectFor,
  libraryDragKind,
  readLibraryDrop,
  writeLibraryArtifactDrag,
  writeLibraryFolderDrag,
} from "./library-drag";

/**
 * A drag's data, as the browser holds it: readable by type, and `types` reports
 * what has been written so far, which is all a `dragover` can see.
 */
function transfer(extraTypes: readonly string[] = []): DataTransfer {
  const values = new Map<string, string>();
  return {
    data: values,
    get types() {
      return [...extraTypes, ...values.keys()];
    },
    files: [] as unknown as FileList,
    getData: (type: string) => values.get(type) ?? "",
    setData: (type: string, value: string) => {
      values.set(type, value);
    },
    effectAllowed: "uninitialized",
    dropEffect: "none",
  } as unknown as DataTransfer;
}

function written(dataTransfer: DataTransfer): Map<string, string> {
  return (dataTransfer as unknown as { data: Map<string, string> }).data;
}

function item(
  id: string,
  overrides: Partial<{
    artifact_type: string;
    schema_version: number;
    sha256: string | null;
    folder_id: string | null;
  }> = {},
): PlacedLibraryItem {
  return {
    artifact: {
      artifact_id: id,
      artifact_type: overrides.artifact_type ?? "file.csv",
      schema_version: overrides.schema_version ?? 1,
      content_type: "text/csv",
      byte_size: 12,
      sha256: overrides.sha256 === undefined ? `hash-${id}` : overrides.sha256,
      content_url: `/v1/artifacts/${id}/content`,
      download_formats: [],
      metadata: {},
    },
    name: `${id}.csv`,
    provenance: {
      source: "upload",
      saved_at: "2026-09-11T12:00:00Z",
      original_filename: `${id}.csv`,
    },
    run: null,
    folder_id: overrides.folder_id ?? null,
  };
}

function sequence(value: unknown) {
  return value as {
    item_refs: { artifact_id: string }[];
    ordered: boolean;
    index_key: string;
    sequence_id: string;
  };
}

describe("artifactDropGroups", () => {
  it("carries nothing when the drag picked up no rows", () => {
    expect(artifactDropGroups([])).toEqual([]);
  });

  it("hands a lone artifact over as the single reference it is", () => {
    const [group] = artifactDropGroups([item("a")]);

    expect(group).toMatchObject({
      artifact_id: "a",
      artifact_type: "file.csv",
      schema_version: 1,
      content_hash: "hash-a",
    });
    expect(group).not.toHaveProperty("item_refs");
  });

  it("puts artifacts of one kind on one ordered card", () => {
    const groups = artifactDropGroups([item("a"), item("b"), item("c")]);

    expect(groups).toHaveLength(1);
    const only = sequence(groups[0]);
    expect(only.item_refs.map((ref) => ref.artifact_id)).toEqual([
      "a",
      "b",
      "c",
    ]);
    expect(only.ordered).toBe(true);
    expect(only.index_key).toBe("order_index");
    expect(only.sequence_id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("gives each kind its own card, in the order the rows first appear", () => {
    const groups = artifactDropGroups([
      item("plot", { artifact_type: "file.png" }),
      item("sales"),
      item("map", { artifact_type: "file.png" }),
      item("notes", { artifact_type: "text.plain" }),
    ]);

    expect(
      groups.map((group) => [
        group.artifact_type,
        "item_refs" in group
          ? group.item_refs.map((ref) => ref.artifact_id)
          : [group.artifact_id],
      ]),
    ).toEqual([
      ["file.png", ["plot", "map"]],
      ["file.csv", ["sales"]],
      ["text.plain", ["notes"]],
    ]);
  });

  it("will not put two schema versions of a type on one card", () => {
    const groups = artifactDropGroups([
      item("old", { schema_version: 1 }),
      item("new", { schema_version: 2 }),
    ]);

    expect(groups.map((group) => group.schema_version)).toEqual([1, 2]);
  });

  it("passes an artifact with no stored hash on without one", () => {
    const [group] = artifactDropGroups([item("blob", { sha256: null })]);

    expect(group).toMatchObject({ content_hash: null });
  });
});

describe("writeLibraryArtifactDrag", () => {
  it("writes exactly what a drag of one artifact always wrote", () => {
    const dataTransfer = transfer();

    writeLibraryArtifactDrag(dataTransfer, [item("a")]);

    expect(readArtifactDrop(dataTransfer)).toEqual({
      value: {
        artifact_id: "a",
        artifact_type: "file.csv",
        schema_version: 1,
        content_hash: "hash-a",
      },
      shape: "one",
    });
    // One card needs no group list, so a single drag stays as small as it was.
    expect(written(dataTransfer).has(ARTIFACT_GROUPS_DATA_TYPE)).toBe(false);
    expect(written(dataTransfer).get(LIBRARY_MOVE_DATA_TYPE)).toBe('["a"]');
    expect(dataTransfer.effectAllowed).toBe("copyMove");
  });

  it("writes every card the selection asks for, and the rows a folder move needs", () => {
    const dataTransfer = transfer();

    writeLibraryArtifactDrag(dataTransfer, [
      item("sales"),
      item("returns"),
      item("plot", { artifact_type: "file.png" }),
    ]);

    const groups = readArtifactDropGroups(dataTransfer);
    expect(groups.map((group) => group.shape)).toEqual(["many", "one"]);
    expect(
      groups.map((group) =>
        "item_refs" in group.value
          ? group.value.item_refs.map((ref) => ref.artifact_id)
          : [group.value.artifact_id],
      ),
    ).toEqual([["sales", "returns"], ["plot"]]);
    expect(written(dataTransfer).get(LIBRARY_MOVE_DATA_TYPE)).toBe(
      '["sales","returns","plot"]',
    );
    // A canvas that knows nothing about grouped drops still gets a card to land.
    expect(readArtifactDrop(dataTransfer)?.shape).toBe("many");
  });

  it("writes nothing when there was nothing to drag", () => {
    const dataTransfer = transfer();

    writeLibraryArtifactDrag(dataTransfer, []);

    expect(written(dataTransfer).size).toBe(0);
  });
});

describe("readLibraryDrop", () => {
  it("reads a Library artifact drag as every row it picked up", () => {
    const dataTransfer = transfer();
    writeLibraryArtifactDrag(dataTransfer, [item("a"), item("b")]);

    expect(libraryDragKind(dataTransfer)).toBe("artifact");
    expect(readLibraryDrop(dataTransfer)).toEqual({
      kind: "artifact",
      artifactIds: ["a", "b"],
    });
  });

  it("files an artifact dragged from a canvas, which carries no move list", () => {
    const dataTransfer = transfer();
    writeArtifactDrop(dataTransfer, {
      artifact_id: "canvas-artifact",
      artifact_type: "file.csv",
      schema_version: 1,
      content_hash: null,
    });

    expect(readLibraryDrop(dataTransfer)).toEqual({
      kind: "artifact",
      artifactIds: ["canvas-artifact"],
    });
  });

  it("will not file a sequence dragged off the canvas as one row", () => {
    const dataTransfer = transfer();
    writeArtifactDrop(dataTransfer, {
      artifact_type: "file.csv",
      schema_version: 1,
      item_refs: [
        {
          artifact_id: "a",
          artifact_type: "file.csv",
          schema_version: 1,
          content_hash: null,
        },
      ],
      ordered: true,
      index_key: "order_index",
      sequence_id: "22222222-2222-4222-8222-222222222222",
    });

    expect(readLibraryDrop(dataTransfer)).toBeNull();
  });

  it("reads a broken move list as nothing rather than filing garbage", () => {
    const dataTransfer = transfer();
    written(dataTransfer).set(LIBRARY_MOVE_DATA_TYPE, "{ not json");
    writeArtifactDrop(dataTransfer, {
      artifact_id: "a",
      artifact_type: "file.csv",
      schema_version: 1,
      content_hash: null,
    });

    expect(readLibraryDrop(dataTransfer)).toEqual({
      kind: "artifact",
      artifactIds: ["a"],
    });
  });

  it("reads a folder drag and a desktop drop by what they carry", () => {
    const folderDrag = transfer();
    writeLibraryFolderDrag(folderDrag, "fieldwork");
    expect(libraryDragKind(folderDrag)).toBe("folder");
    expect(readLibraryDrop(folderDrag)).toEqual({
      kind: "folder",
      folderId: "fieldwork",
    });
    // A folder travels on its own type and carries no artifact payload, so a
    // canvas cannot read it as a card.
    expect(folderDrag.getData(LIBRARY_FOLDER_DATA_TYPE)).toBe("fieldwork");
    expect(folderDrag.getData(ARTIFACT_DROP_DATA_TYPE)).toBe("");

    const desktop = transfer(["Files"]);
    Object.defineProperty(desktop, "files", {
      value: [new File(["1"], "a.csv")],
    });
    expect(libraryDragKind(desktop)).toBe("upload");
    expect(readLibraryDrop(desktop)?.kind).toBe("upload");

    const unrelated = transfer();
    unrelated.setData("text/plain", "a sentence");
    expect(libraryDragKind(unrelated)).toBeNull();
    expect(readLibraryDrop(unrelated)).toBeNull();
  });

  it("copies what arrives and moves what was already here", () => {
    expect(dropEffectFor("upload")).toBe("copy");
    expect(dropEffectFor("artifact")).toBe("move");
    expect(dropEffectFor("folder")).toBe("move");
  });
});
