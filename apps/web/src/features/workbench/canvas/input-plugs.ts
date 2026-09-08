import { createUuid } from "@/features/workbench/model/uuid";
import type { NodeSpec, RunNodeResult } from "@/lib/api";
import {
  SCHEMA_BUILDER_INPUT_PORT,
  schemaFieldConsumesInput,
  type SchemaBuilderField,
} from "./schema-builder";

export interface WorkflowInputPlug {
  id: string;
  portName: string;
}

export interface WorkflowInputPlugBinding {
  sourceLabel: string;
  sourceShape: "one" | "many";
  conversionLabel?: string;
  contributionLabel?: string;
}

interface CollectSegment {
  inputIndex: number;
  startIndex: number;
  itemCount: number;
  sourceKind: "single" | "sequence";
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function createWorkflowInputPlug(portName: string): WorkflowInputPlug {
  return { id: createUuid(), portName };
}

export function initialInputPlugs(spec: NodeSpec): WorkflowInputPlug[] {
  return spec.inputs
    .filter((port) => port.instance_plugs === true && port.required)
    .map((port) => createWorkflowInputPlug(port.name));
}

export function inputPlugsForPort(
  inputPlugs: readonly WorkflowInputPlug[],
  portName: string,
): WorkflowInputPlug[] {
  return inputPlugs.filter((plug) => plug.portName === portName);
}

export function appendInputPlug(
  inputPlugs: readonly WorkflowInputPlug[],
  portName: string,
): WorkflowInputPlug[] {
  const nextPlug = createWorkflowInputPlug(portName);
  const lastPortIndex = inputPlugs.findLastIndex(
    (plug) => plug.portName === portName,
  );
  if (lastPortIndex === -1) return [...inputPlugs, nextPlug];
  return [
    ...inputPlugs.slice(0, lastPortIndex + 1),
    nextPlug,
    ...inputPlugs.slice(lastPortIndex + 1),
  ];
}

export function removeInputPlug(
  inputPlugs: readonly WorkflowInputPlug[],
  plugId: string,
): WorkflowInputPlug[] {
  return inputPlugs.filter((plug) => plug.id !== plugId);
}

export function reorderInputPlug(
  inputPlugs: readonly WorkflowInputPlug[],
  portName: string,
  plugId: string,
  toIndex: number,
): WorkflowInputPlug[] {
  const portPlugs = inputPlugsForPort(inputPlugs, portName);
  const fromIndex = portPlugs.findIndex((plug) => plug.id === plugId);
  if (fromIndex === -1 || portPlugs.length < 2) return [...inputPlugs];

  const boundedIndex = Math.max(0, Math.min(toIndex, portPlugs.length - 1));
  if (fromIndex === boundedIndex) return [...inputPlugs];
  const reorderedPortPlugs = [...portPlugs];
  const [movedPlug] = reorderedPortPlugs.splice(fromIndex, 1);
  reorderedPortPlugs.splice(boundedIndex, 0, movedPlug);

  let nextPortIndex = 0;
  return inputPlugs.map((plug) =>
    plug.portName === portName
      ? reorderedPortPlugs[nextPortIndex++]
      : plug,
  );
}

/**
 * Aligns nested-schema plugs with their owning field ids and field order.
 * Plugs for unrelated ports retain their relative order.
 */
export function reconcileSchemaFieldInputPlugs(
  inputPlugs: readonly WorkflowInputPlug[],
  fields: readonly SchemaBuilderField[],
  portName: string = SCHEMA_BUILDER_INPUT_PORT,
): WorkflowInputPlug[] {
  const desiredPlugs = fields
    .filter(schemaFieldConsumesInput)
    .map((field) => ({ id: field.id, portName }));
  const firstPortIndex = inputPlugs.findIndex(
    (plug) => plug.portName === portName,
  );
  const withoutPort = inputPlugs.filter((plug) => plug.portName !== portName);
  const insertionIndex =
    firstPortIndex === -1
      ? withoutPort.length
      : inputPlugs
          .slice(0, firstPortIndex)
          .filter((plug) => plug.portName !== portName).length;

  return [
    ...withoutPort.slice(0, insertionIndex),
    ...desiredPlugs,
    ...withoutPort.slice(insertionIndex),
  ];
}

function collectSegments(run: RunNodeResult | null): CollectSegment[] {
  if (!run) return [];
  for (const output of run.outputs) {
    if (output.kind !== "sequence") continue;
    const value = objectRecord(output.value);
    const metadata = objectRecord(value?.metadata);
    const rawSegments = metadata?.collect_segments;
    if (!Array.isArray(rawSegments)) continue;

    const segments: CollectSegment[] = [];
    for (const rawSegment of rawSegments) {
      const segment = objectRecord(rawSegment);
      if (
        !segment ||
        !Number.isInteger(segment.input_index) ||
        !Number.isInteger(segment.start_index) ||
        !Number.isInteger(segment.item_count) ||
        (segment.source_kind !== "single" &&
          segment.source_kind !== "sequence")
      ) {
        continue;
      }
      segments.push({
        inputIndex: segment.input_index as number,
        startIndex: segment.start_index as number,
        itemCount: segment.item_count as number,
        sourceKind: segment.source_kind,
      });
    }
    return segments;
  }
  return [];
}

export function collectContributionLabel(
  run: RunNodeResult | null,
  inputIndex: number,
): string | undefined {
  const segment = collectSegments(run).find(
    (candidate) => candidate.inputIndex === inputIndex,
  );
  if (!segment) return undefined;
  if (segment.itemCount === 0) return "output empty";

  const first = segment.startIndex + 1;
  if (segment.itemCount === 1) return `output ${first}`;
  return `output ${first}–${segment.startIndex + segment.itemCount}`;
}
