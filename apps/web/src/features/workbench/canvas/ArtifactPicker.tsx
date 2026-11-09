"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ChevronDown } from "lucide-react";
import useSWR from "swr";

import {
  createTableTextArtifacts,
  getArtifactTablePage,
  getArtifactTableSchema,
  type ArtifactRef,
  type SavedGraphOrigin,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Menu,
  MenuContent,
  MenuGroup,
  MenuItem,
  MenuLabel,
  MenuSubmenu,
  MenuSubmenuTrigger,
  MenuTrigger,
} from "@/components/ui/menu";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { writeArtifactDrop } from "../model/artifact-drop";
import { isTableArtifact } from "./artifact-card";
import {
  PICKER_ROW_LIMIT,
  pickerColumns,
  pickerPreview,
} from "./artifact-picker-rows";
import {
  formatArtifactTypeLabel,
  formatArtifactTypeSequence,
  type ArtifactTypeCatalog,
} from "./artifact-type-label";

type PickedValue = SavedGraphOrigin["value"];

/** One named output a person may take whole, or look inside. */
export interface PickableArtifact {
  readonly port: string;
  readonly artifact: PickedValue;
}

/** Whether there is anything inside this artifact to pick. */
export function hasPickableParts(artifact: PickedValue): boolean {
  return "item_refs" in artifact || isTableArtifact(artifact);
}

const s = stylex.create({
  // The rows are many and their words long; the list scrolls and each row stays one line.
  parts: {
    maxWidth: "360px",
    maxHeight: "320px",
    overflowY: "auto",
  },
  row: {
    cursor: "grab",
  },
});

function typeLabel(
  artifact: PickedValue,
  artifactTypes: ArtifactTypeCatalog,
): string {
  const type = {
    id: artifact.artifact_type,
    schema_version: artifact.schema_version,
  };
  const label = formatArtifactTypeLabel(type, artifactTypes);
  return "item_refs" in artifact ? formatArtifactTypeSequence(label) : label;
}

/**
 * Everything a row needs to be dragged out. The menu stays open through the drag,
 * because taking away the element being dragged would end it, and closes after.
 */
function useDragRow(close: () => void) {
  return React.useCallback(
    (value: PickedValue) => ({
      draggable: true,
      title: "Drag onto the canvas, an input or the Library",
      closeOnClick: false,
      onDragStart: (event: React.DragEvent) => {
        event.stopPropagation();
        writeArtifactDrop(event.dataTransfer, value);
      },
      onDragEnd: close,
    }),
    [close],
  );
}

function SequenceParts({
  refs,
  artifactTypes,
  dragRow,
}: {
  refs: readonly ArtifactRef[];
  artifactTypes: ArtifactTypeCatalog;
  dragRow: ReturnType<typeof useDragRow>;
}) {
  return (
    <>
      {refs.slice(0, PICKER_ROW_LIMIT).map((ref, index) => (
        <MenuItem
          key={ref.artifact_id}
          hint={typeLabel(ref, artifactTypes)}
          xstyle={s.row}
          {...dragRow(ref)}
        >
          Item {index + 1}
        </MenuItem>
      ))}
      {refs.length > PICKER_ROW_LIMIT ? (
        <MenuLabel>
          First {PICKER_ROW_LIMIT} of {refs.length}
        </MenuLabel>
      ) : null}
    </>
  );
}

function TableParts({
  artifactId,
  dragRow,
}: {
  artifactId: string;
  dragRow: ReturnType<typeof useDragRow>;
}) {
  const { workspace } = useWorkspaceContext();
  const { data, error } = useSWR(
    ["artifact-picker-rows", workspace.id, artifactId] as const,
    async ([, workspaceId, id]) => {
      const schema = await getArtifactTableSchema(workspaceId, id);
      const columns = pickerColumns(schema.columns);
      if (!columns) return null;
      const [page, made] = await Promise.all([
        getArtifactTablePage(
          workspaceId,
          id,
          0,
          PICKER_ROW_LIMIT,
          [columns.content.id, ...(columns.label ? [columns.label.id] : [])],
          120,
        ),
        createTableTextArtifacts(
          workspaceId,
          id,
          columns.content.id,
          PICKER_ROW_LIMIT,
        ),
      ]);
      return { columns, page, made };
    },
    // What it makes never changes; there is no reason to ask twice.
    { revalidateOnFocus: false, revalidateIfStale: false },
  );
  if (error) return <MenuLabel>Could not read these rows.</MenuLabel>;
  if (data === undefined) return <MenuLabel>Reading rows…</MenuLabel>;
  if (data === null)
    return <MenuLabel>This table has no text to take.</MenuLabel>;
  const { columns, page, made } = data;
  return (
    <>
      {made.rows.map(({ row_index: rowIndex, artifact }, index) => {
        const row = page.rows[index];
        const label = columns.label && row?.[columns.label.id]?.display;
        const preview = pickerPreview(row?.[columns.content.id]?.display);
        const words = `${label ? `${String(label)}: ` : ""}${preview || "empty"}`;
        return artifact ? (
          <MenuItem
            key={rowIndex}
            hint={`Row ${rowIndex + 1}`}
            xstyle={s.row}
            {...dragRow(artifact)}
          >
            {words}
          </MenuItem>
        ) : (
          <MenuItem key={rowIndex} hint={`Row ${rowIndex + 1}`} disabled>
            {words}
          </MenuItem>
        );
      })}
      {made.total_rows > made.rows.length ? (
        <MenuLabel>
          First {made.rows.length} of {made.total_rows}
        </MenuLabel>
      ) : null}
    </>
  );
}

/**
 * A menu of artifacts, each draggable out of it whole, with what is inside one a step
 * further: the items of a sequence, or the rows of a table as text. It knows nothing
 * of where its artifacts came from, so anything holding outputs can offer them.
 */
export function ArtifactPicker({
  artifacts,
  artifactTypes,
  label,
}: {
  artifacts: readonly PickableArtifact[];
  artifactTypes: ArtifactTypeCatalog;
  label: string;
}): React.ReactElement {
  const [open, setOpen] = React.useState(false);
  const dragRow = useDragRow(() => setOpen(false));
  return (
    <Menu modal={false} open={open} onOpenChange={setOpen}>
      <MenuTrigger
        render={<Button variant="soft" size="xs" className="nodrag" />}
      >
        {label}
        <ChevronDown size={12} aria-hidden="true" />
      </MenuTrigger>
      <MenuContent>
        {artifacts.map(({ port, artifact }) => {
          const type = typeLabel(artifact, artifactTypes);
          if (!hasPickableParts(artifact)) {
            return (
              <MenuItem
                key={port}
                hint={type}
                xstyle={s.row}
                {...dragRow(artifact)}
              >
                {port}
              </MenuItem>
            );
          }
          return (
            <MenuSubmenu key={port}>
              <MenuSubmenuTrigger
                draggable
                title="Drag it whole, or open it to take a part"
                xstyle={s.row}
                onDragStart={(event) => {
                  event.stopPropagation();
                  writeArtifactDrop(event.dataTransfer, artifact);
                }}
                onDragEnd={() => setOpen(false)}
              >
                {port} · {type}
              </MenuSubmenuTrigger>
              <MenuContent side="right" sideOffset={4} xstyle={s.parts}>
                <MenuGroup>
                  {"item_refs" in artifact ? (
                    <SequenceParts
                      refs={artifact.item_refs}
                      artifactTypes={artifactTypes}
                      dragRow={dragRow}
                    />
                  ) : (
                    <TableParts
                      artifactId={artifact.artifact_id}
                      dragRow={dragRow}
                    />
                  )}
                </MenuGroup>
              </MenuContent>
            </MenuSubmenu>
          );
        })}
      </MenuContent>
    </Menu>
  );
}
