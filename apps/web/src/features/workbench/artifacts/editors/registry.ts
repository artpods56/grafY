import type { ArtifactTypeSpec } from "@/lib/api";

import { artifactTypeKey } from "../artifact-type-key";
import { JsonArtifactEditor } from "./JsonArtifactEditor";
import { TableArtifactEditor } from "./TableArtifactEditor";
import { DEFAULT_TABLE_PAYLOAD } from "./table-editor-reducer";
import { TextArtifactEditor } from "./TextArtifactEditor";
import type { ArtifactEditorRegistration } from "./types";

const JSON_SCHEMA_STARTER = '{"type":"object","properties":{}}';

export const JSON_EDITOR: ArtifactEditorRegistration = {
  typeKey: "json.raw@1",
  label: "Raw JSON",
  createDefaultPayload: () => ({}),
  Component: JsonArtifactEditor,
};

export const TEXT_EDITOR: ArtifactEditorRegistration = {
  typeKey: "scalar.text@1",
  label: "Text",
  createDefaultPayload: () => ({ value: "" }),
  Component: TextArtifactEditor,
};

export const TABLE_EDITOR: ArtifactEditorRegistration = {
  typeKey: "table.data@1",
  label: "Table",
  createDefaultPayload: () => structuredClone(DEFAULT_TABLE_PAYLOAD),
  Component: TableArtifactEditor,
};

/**
 * Specialized editors keyed by `id@version`.
 */
export const SPECIALIZED_EDITORS: readonly ArtifactEditorRegistration[] = [
  TEXT_EDITOR,
  TABLE_EDITOR,
];

const editorsByKey = new Map(
  SPECIALIZED_EDITORS.map((editor) => [editor.typeKey, editor]),
);

const DEFAULT_PAYLOADS: Record<string, () => Record<string, unknown>> = {
  "scalar.text@1": TEXT_EDITOR.createDefaultPayload,
  "scalar.integer@1": () => ({ value: 0 }),
  "table.data@1": TABLE_EDITOR.createDefaultPayload,
  "json.schema@1": () => ({ value: JSON_SCHEMA_STARTER }),
  "geo.feature_collection@1": () => ({
    type: "FeatureCollection",
    crs: "EPSG:4326",
    features: [],
    source_name: "untitled",
    bounds: null,
  }),
};

export function getArtifactEditor(
  artifactType: string,
  schemaVersion: number,
  spec?: Pick<ArtifactTypeSpec, "authorable">,
): ArtifactEditorRegistration | null {
  const typeKey = artifactTypeKey({
    id: artifactType,
    schema_version: schemaVersion,
  });
  const specialized = editorsByKey.get(typeKey);
  if (specialized) return specialized;
  if (spec && spec.authorable !== true) return null;
  return JSON_EDITOR;
}

export function getDefaultPayloadForType(
  artifactType: string,
  schemaVersion: number,
  spec?: Pick<ArtifactTypeSpec, "authorable" | "key">,
): Record<string, unknown> {
  const typeKey = artifactTypeKey({
    id: artifactType,
    schema_version: schemaVersion,
  });
  const specialized = editorsByKey.get(typeKey);
  if (specialized) return specialized.createDefaultPayload();
  const starter = DEFAULT_PAYLOADS[typeKey];
  if (starter) return starter();
  if (spec && spec.authorable !== true) return {};
  return {};
}

export function authorableArtifactTypes(
  artifactTypes: readonly Pick<
    ArtifactTypeSpec,
    "key" | "title" | "authorable"
  >[],
): readonly Pick<ArtifactTypeSpec, "key" | "title" | "authorable">[] {
  return artifactTypes.filter((spec) => spec.authorable === true);
}
