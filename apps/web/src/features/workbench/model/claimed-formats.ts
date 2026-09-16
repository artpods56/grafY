import type { ArtifactTypeKey } from "@/lib/api";

import { BLOB_ARTIFACT_TYPE } from "./blob-notice";

const FILE_INTERPRET_OPERATOR_ID = "file.interpret";
const FORMAT_TYPE_VARIABLE = "format";

/**
 * A claimed `file.*` format: a container type the deployment extension table
 * knows. The blob fallback is not a format, and an interpreted payload type is
 * not a file format either.
 */
export function isClaimedFileFormatId(id: string): boolean {
  return id.startsWith("file.") && id !== BLOB_ARTIFACT_TYPE;
}

/**
 * The types a node's artifact type variable may bind to. `file.interpret@1`
 * names its format explicitly, so its `format` variable offers the claimed
 * `file.*` formats only; every other variable keeps the full catalog.
 */
export function artifactTypeVariableOptions(
  operatorId: string,
  variable: string,
  options: readonly ArtifactTypeKey[],
): readonly ArtifactTypeKey[] {
  if (
    operatorId !== FILE_INTERPRET_OPERATOR_ID ||
    variable !== FORMAT_TYPE_VARIABLE
  ) {
    return options;
  }
  return options.filter((option) => isClaimedFileFormatId(option.id));
}
