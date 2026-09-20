import { describe, expect, it } from "vitest";

import type { LibraryItem } from "@/lib/api";

import {
  LIBRARY_FOLDERS,
  buildLibraryFolders,
  formatLibraryByteSize,
  isItemImage,
  libraryFileCount,
  libraryFileDisplayName,
  libraryFileSubtitle,
  libraryFolderFor,
  libraryProvenanceLine,
  visibleLibraryFolders,
} from "./library-tree";

function item(
  artifactId: string,
  artifactType: string,
  overrides: Partial<LibraryItem> = {},
  artifactOverrides: Partial<LibraryItem["artifact"]> = {},
): LibraryItem {
  return {
    artifact: {
      artifact_id: artifactId,
      artifact_type: artifactType,
      schema_version: 1,
      content_type: "application/octet-stream",
      byte_size: null,
      sha256: null,
      content_url: `./artifacts/${artifactId}/content`,
      download_formats: [],
      metadata: {},
      ...artifactOverrides,
    },
    name: `${artifactId}-name`,
    provenance: {
      source: "run",
      saved_at: "2026-09-11T12:00:00Z",
      graph_title: "Sales",
      node_title: "Resize",
      graph_revision: 4,
      execution_id: "execution-1",
    },
    run: null,
    ...overrides,
  };
}

function folderIds(
  folders: ReturnType<typeof buildLibraryFolders>,
): string[] {
  return folders.map((folder) => folder.id);
}

describe("libraryFolderFor", () => {
  it("files containers and interpreted payloads by what they look like", () => {
    expect(libraryFolderFor(item("a", "file.jpeg"))).toBe("images");
    expect(libraryFolderFor(item("a", "image.raster"))).toBe("images");
    expect(libraryFolderFor(item("a", "file.csv"))).toBe("tables");
    expect(libraryFolderFor(item("a", "table.data"))).toBe("tables");
    expect(libraryFolderFor(item("a", "file.txt"))).toBe("text");
    expect(libraryFolderFor(item("a", "scalar.text"))).toBe("text");
    expect(libraryFolderFor(item("a", "model.weights"))).toBe("models");
  });

  it("files an unknown type, and a blob, in other", () => {
    expect(libraryFolderFor(item("a", "file.blob"))).toBe("other");
    expect(libraryFolderFor(item("a", "mystery.payload"))).toBe("other");
  });

  it("ignores the version suffix on a type id", () => {
    expect(libraryFolderFor(item("a", "file.png@1"))).toBe("images");
  });
});

describe("buildLibraryFolders", () => {
  it("keeps every standing folder when the Library is empty", () => {
    const folders = buildLibraryFolders([]);

    expect(folderIds(folders)).toEqual(LIBRARY_FOLDERS.map((f) => f.id));
    expect(folders.every((folder) => folder.files.length === 0)).toBe(true);
  });

  it("files artifacts under their folder and counts them", () => {
    const folders = buildLibraryFolders([
      item("shot", "file.jpeg"),
      item("scan", "image.raster"),
      item("rows", "file.csv"),
      item("mystery", "file.blob"),
    ]);

    expect(folderIds(folders)).toEqual([
      "images",
      "tables",
      "text",
      "models",
      "other",
    ]);
    expect(folders[0]?.files.map((file) => file.item.artifact.artifact_id)).toEqual(
      ["scan", "shot"],
    );
    expect(folders[1]?.total).toBe(1);
    expect(folders[4]?.total).toBe(1);
  });

  it("orders files by name and keeps the newest first on request", () => {
    const items = [
      item("z", "file.txt", {
        name: "zulu",
        provenance: {
          source: "upload",
          saved_at: "2026-09-12T12:00:00Z",
          original_filename: "zulu.txt",
        },
        run: null,
      }),
      item("a", "file.txt", {
        name: "alpha",
        provenance: {
          source: "upload",
          saved_at: "2026-09-10T12:00:00Z",
          original_filename: "alpha.txt",
        },
        run: null,
      }),
    ];

    expect(
      buildLibraryFolders(items)[2]?.files.map((file) => file.item.name),
    ).toEqual(["alpha", "zulu"]);
    expect(
      buildLibraryFolders(items, { sort: "recent" })[2]?.files.map(
        (file) => file.item.name,
      ),
    ).toEqual(["zulu", "alpha"]);
  });

  it("filters by name, original filename, type and folder", () => {
    const items = [
      item("shot", "file.jpeg", {
        name: "PNG image",
        provenance: {
          source: "upload",
          saved_at: "2026-09-11T12:00:00Z",
          original_filename: "harbour-front.jpg",
        },
        run: null,
      }),
      item("rows", "file.csv"),
    ];

    const byFile = buildLibraryFolders(items, { query: "harbour" });
    expect(libraryFileCount(byFile)).toBe(2);
    expect(byFile[0]?.files.map((file) => file.item.name)).toEqual([
      "PNG image",
    ]);

    const byType = buildLibraryFolders(items, { query: "csv" });
    expect(byType[1]?.files.map((file) => file.item.artifact.artifact_id)).toEqual(
      ["rows"],
    );

    const byFolder = buildLibraryFolders(items, { query: "images" });
    expect(byFolder[0]?.files.length).toBe(1);
    expect(byFolder[1]?.files.length).toBe(0);
  });

  it("hides folders with no match while a filter is active", () => {
    const folders = buildLibraryFolders([item("rows", "file.csv")]);

    expect(visibleLibraryFolders(folders, "").length).toBe(5);
    expect(visibleLibraryFolders(folders, "rows").map((f) => f.id)).toEqual([
      "tables",
    ]);
  });
});

describe("library file labels", () => {
  it("names an uploaded file by the filename it arrived with", () => {
    const uploaded = item("shot", "file.jpeg", {
      name: "PNG image",
      provenance: {
        source: "upload",
        saved_at: "2026-09-11T12:00:00Z",
        original_filename: "harbour.jpg",
      },
      run: null,
    });

    expect(libraryFileDisplayName(uploaded)).toBe("harbour.jpg");
    expect(libraryFileDisplayName(item("rows", "table.data"))).toBe(
      "rows-name",
    );
  });

  it("describes size and origin under the name", () => {
    const uploaded = item("shot", "file.jpeg", {
      provenance: {
        source: "upload",
        saved_at: "2026-09-11T12:00:00Z",
        original_filename: "harbour.jpg",
      },
      run: null,
    }, { byte_size: 2_684_354_560 });

    expect(libraryFileSubtitle(uploaded)).toBe("2.5 GB · uploaded");
    expect(libraryFileSubtitle(item("rows", "table.data"))).toBe("from a run");
  });

  it("formats byte sizes the way a file browser does", () => {
    expect(formatLibraryByteSize(null)).toBeNull();
    expect(formatLibraryByteSize(0)).toBe("0 B");
    expect(formatLibraryByteSize(999)).toBe("999 B");
    expect(formatLibraryByteSize(1024)).toBe("1.0 KB");
    expect(formatLibraryByteSize(15_360)).toBe("15 KB");
    expect(formatLibraryByteSize(12_884_901_888)).toBe("12 GB");
  });

  it("keeps the provenance line for both sources", () => {
    expect(libraryProvenanceLine(item("rows", "table.data"))).toBe(
      "Sales · Resize · revision 4 · from a run",
    );
    const uploaded = item("shot", "file.jpeg", {
      provenance: {
        source: "upload",
        saved_at: "2026-09-11T12:00:00Z",
        original_filename: "harbour.jpg",
      },
      run: null,
    });

    expect(libraryProvenanceLine(uploaded)).toBe("uploaded · harbour.jpg");
  });

  it("spots an image by its content type", () => {
    const jpeg = item("shot", "file.jpeg", {}, { content_type: "image/jpeg" });

    expect(isItemImage(jpeg)).toBe(true);
    expect(isItemImage(item("rows", "text/csv"))).toBe(false);
  });
});
