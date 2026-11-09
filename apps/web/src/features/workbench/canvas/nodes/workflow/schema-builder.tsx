"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ArrowDown, ArrowUp, GripVertical, Plus, Trash2 } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { Field, TextInput } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { Notice } from "@/components/ui/notice";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { CanvasPortBall } from "../CanvasNodeChrome";
import { encodeHandleId } from "../../handles";
import { reconcileSchemaFieldInputPlugs } from "../../input-plugs";
import { artifactTypeColor } from "../../nodes.css";
import {
  SCHEMA_BUILDER_INPUT_PORT,
  SCHEMA_FIELD_KINDS,
  SCHEMA_SEQUENCE_ITEM_KINDS,
  createSchemaBuilderField,
  moveSchemaBuilderField,
  schemaBuilderFields,
  schemaFieldConsumesInput,
  withSchemaFieldKind,
  type SchemaBuilderField,
  type SchemaFieldKind,
  type SchemaSequenceItemKind,
} from "../../schema-builder";
import {
  portMetaForPort,
  resolvedPortArtifactType,
  type WorkflowNodeData,
} from "../../types";

import { InstanceInputConnectionToggle, nodeInteractionProps } from "./ports";
import { sharedStyles } from "./styles";

const s = stylex.create({
  schemaMetadata: {
    display: "grid",
    gap: "6px",
    paddingInline: "4px",
  },
  schemaMetadataRow: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    alignItems: "end",
    gap: "6px",
  },
  /** A metadata row keeps its label 3px off the control. */
  metaField: { gap: "3px" },
  /**
   * The required flag is warning-coloured rather than the kit's neutral pressed
   * fill, and that colour carries meaning: which fields a caller must send. The
   * state itself comes from <Button pressed>, so only the hue is owned here.
   */
  requiredActive: {
    color: {
      default: tokens.colorWarning,
      ":hover:not(:disabled)": tokens.colorWarning,
    },
  },
  schemaFieldRowDragging: {
    backgroundColor: tokens.colorAccentSoft,
    boxShadow: `inset 0 0 0 1px ${tokens.colorAccentBorder}`,
  },
  schemaFieldTop: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "18px 18px minmax(0, 1fr) 92px",
    alignItems: "center",
    gap: "4px",
  },
  /** The handle keeps the 18px column the row budgets it, and its grab cursor. */
  grip: {
    width: "18px",
    height: "26px",
    borderRadius: "5px",
    cursor: "grab",
    touchAction: "none",
  },
  schemaFieldDetail: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto auto",
    alignItems: "center",
    gap: "4px",
    marginLeft: "40px",
  },
  /** Row actions keep the 18px the detail row budgets them. */
  rowAction: {
    width: "18px",
    height: "22px",
    borderRadius: "5px",
  },
  schemaItemRow: {
    minWidth: 0,
    minHeight: "26px",
    display: "grid",
    gridTemplateColumns: "40px 92px minmax(0, 1fr)",
    alignItems: "center",
    gap: "4px",
    marginLeft: "40px",
  },
  schemaItemLabel: {
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 600,
  },
  schemaConnection: {
    overflow: "hidden",
    color: tokens.colorMuted,
    fontSize: "10px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  schemaConnectionBound: { color: tokens.colorTextEmphasis, fontWeight: 500 },
  schemaConnectionRow: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "4px",
  },
  schemaConnectionGrow: {
    minWidth: 0,
    flex: "1 1 auto",
  },
});

const SCHEMA_FIELD_KIND_LABELS: Record<SchemaFieldKind, string> = {
  string: "Text",
  integer: "Integer",
  number: "Number",
  boolean: "Boolean",
  sequence: "Sequence",
  schema: "Schema",
};

const SCHEMA_ITEM_KIND_LABELS: Record<SchemaSequenceItemKind, string> = {
  string: "Text",
  integer: "Integer",
  number: "Number",
  boolean: "Boolean",
  schema: "Schema",
};

export function SchemaBuilderBody({
  id,
  data,
}: {
  id: string;
  data: WorkflowNodeData;
}) {
  const fields = schemaBuilderFields(data.config.fields);
  const inputPort = data.spec.inputs.find(
    (port) => port.name === SCHEMA_BUILDER_INPUT_PORT,
  );
  const artifactType = inputPort
    ? resolvedPortArtifactType(inputPort, data.artifactTypeBindings)
    : null;
  const handleColor = artifactType
    ? artifactTypeColor(artifactType.id, tokens.colorAccent)
    : tokens.colorAccent;
  const [draggedFieldId, setDraggedFieldId] = React.useState<string | null>(
    null,
  );
  const draggedFieldIdRef = React.useRef<string | null>(null);
  const lastPointerTargetRef = React.useRef<string | null>(null);

  const commitFields = (nextFields: readonly SchemaBuilderField[]) => {
    const nextInputPlugs = reconcileSchemaFieldInputPlugs(
      data.inputPlugs,
      nextFields,
      SCHEMA_BUILDER_INPUT_PORT,
    );
    if (data.onSchemaBuilderFieldsChange) {
      data.onSchemaBuilderFieldsChange(id, nextFields, nextInputPlugs);
    } else {
      data.onConfigChange?.(id, "fields", nextFields);
    }
  };

  const replaceField = (fieldId: string, nextField: SchemaBuilderField) => {
    commitFields(
      fields.map((field) => (field.id === fieldId ? nextField : field)),
    );
  };

  const finishPointerDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    draggedFieldIdRef.current = null;
    lastPointerTargetRef.current = null;
    setDraggedFieldId(null);
  };

  return (
    <div {...stylex.props(sharedStyles.schemaBody)}>
      <div {...stylex.props(s.schemaMetadata)}>
        <div {...stylex.props(s.schemaMetadataRow)}>
          <Field label="Schema title · optional" xstyle={s.metaField}>
            <TextInput
              type="text"
              value={
                typeof data.config.title === "string" ? data.config.title : ""
              }
              placeholder="Response"
              className="nodrag nowheel"
              xstyle={sharedStyles.denseControl}
              onChange={(event) =>
                data.onConfigChange?.(id, "title", event.currentTarget.value)
              }
            />
          </Field>
          <Button
            variant="soft"
            size="sm"
            pressed={data.config.additional_properties === true}
            title="Allow properties not declared below"
            className="nodrag nowheel"
            onClick={() =>
              data.onConfigChange?.(
                id,
                "additional_properties",
                data.config.additional_properties !== true,
              )
            }
          >
            Extra fields
          </Button>
        </div>
        <Field label="Description · optional" xstyle={s.metaField}>
          <TextInput
            type="text"
            value={
              typeof data.config.description === "string"
                ? data.config.description
                : ""
            }
            placeholder="What this response contains"
            className="nodrag nowheel"
            xstyle={sharedStyles.denseControl}
            onChange={(event) =>
              data.onConfigChange?.(
                id,
                "description",
                event.currentTarget.value,
              )
            }
          />
        </Field>
      </div>

      <section
        {...stylex.props(sharedStyles.schemaFieldsSection)}
        aria-label="Schema fields"
      >
        <div {...stylex.props(sharedStyles.schemaFieldsHeader)}>
          <span {...stylex.props(sharedStyles.schemaFieldsTitle)}>Fields</span>
          <span {...stylex.props(sharedStyles.schemaFieldsCount)}>
            {fields.length} {fields.length === 1 ? "field" : "fields"} · ordered
          </span>
        </div>

        {fields.length ? (
          <div
            {...nodeInteractionProps(
              stylex.props(sharedStyles.schemaFieldList),
            )}
          >
            {fields.map((field, index) => {
              const consumesInput = schemaFieldConsumesInput(field);
              const binding = data.inputPlugBindings[field.id];
              const connectionLabel = binding?.sourceLabel ?? "Connect schema";
              return (
                <div
                  key={field.id}
                  data-schema-field-id={field.id}
                  {...stylex.props(
                    sharedStyles.schemaFieldRow,
                    draggedFieldId === field.id
                      ? s.schemaFieldRowDragging
                      : null,
                  )}
                >
                  {consumesInput && inputPort ? (
                    <CanvasPortBall
                      nodeId={id}
                      handleId={encodeHandleId(
                        portMetaForPort(
                          inputPort,
                          inputPort.shape,
                          field.id,
                          data.artifactTypeBindings,
                        ),
                      )}
                      side="input"
                      color={handleColor}
                      sequence
                      centerY={19}
                      ariaLabel={`Nested schema for ${field.name || `field ${index + 1}`}`}
                      title="Connect one JSON Schema output here."
                    />
                  ) : null}

                  <div {...stylex.props(s.schemaFieldTop)}>
                    <IconButton
                      label={`Drag to reorder field ${index + 1}`}
                      title="Drag to reorder; arrow buttons also move this field"
                      size="xs"
                      className="nodrag nowheel"
                      xstyle={s.grip}
                      onPointerDown={(event) => {
                        if (event.button !== 0) return;
                        event.stopPropagation();
                        event.currentTarget.setPointerCapture(event.pointerId);
                        draggedFieldIdRef.current = field.id;
                        lastPointerTargetRef.current = field.id;
                        setDraggedFieldId(field.id);
                      }}
                      onPointerMove={(event) => {
                        const activeFieldId = draggedFieldIdRef.current;
                        if (!activeFieldId) return;
                        event.preventDefault();
                        event.stopPropagation();
                        const target = document
                          .elementFromPoint(event.clientX, event.clientY)
                          ?.closest<HTMLElement>("[data-schema-field-id]");
                        const targetFieldId = target?.dataset.schemaFieldId;
                        if (targetFieldId === activeFieldId) {
                          lastPointerTargetRef.current = null;
                          return;
                        }
                        if (
                          !targetFieldId ||
                          targetFieldId === lastPointerTargetRef.current
                        ) {
                          return;
                        }
                        const targetIndex = fields.findIndex(
                          (candidate) => candidate.id === targetFieldId,
                        );
                        if (targetIndex === -1) return;
                        lastPointerTargetRef.current = targetFieldId;
                        commitFields(
                          moveSchemaBuilderField(
                            fields,
                            activeFieldId,
                            targetIndex,
                          ),
                        );
                      }}
                      onPointerUp={finishPointerDrag}
                      onPointerCancel={finishPointerDrag}
                    >
                      <GripVertical size={12} />
                    </IconButton>
                    <span {...stylex.props(sharedStyles.schemaFieldIndex)}>
                      {index + 1}
                    </span>
                    <TextInput
                      type="text"
                      value={field.name}
                      placeholder="field_name"
                      aria-label={`Field ${index + 1} name`}
                      className="nodrag nowheel"
                      xstyle={sharedStyles.denseControl}
                      onChange={(event) =>
                        replaceField(field.id, {
                          ...field,
                          name: event.currentTarget.value,
                        })
                      }
                    />
                    <Select
                      size="sm"
                      value={field.kind}
                      aria-label={`Field ${index + 1} type`}
                      className="nodrag nowheel"
                      onChange={(event) =>
                        replaceField(
                          field.id,
                          withSchemaFieldKind(
                            field,
                            event.currentTarget.value as SchemaFieldKind,
                          ),
                        )
                      }
                    >
                      {SCHEMA_FIELD_KINDS.map((kind) => (
                        <option key={kind} value={kind}>
                          {SCHEMA_FIELD_KIND_LABELS[kind]}
                        </option>
                      ))}
                    </Select>
                  </div>

                  <div {...stylex.props(s.schemaFieldDetail)}>
                    <TextInput
                      type="text"
                      value={field.description}
                      placeholder="Description (optional)"
                      aria-label={`Field ${index + 1} description`}
                      className="nodrag nowheel"
                      xstyle={sharedStyles.denseControl}
                      onChange={(event) =>
                        replaceField(field.id, {
                          ...field,
                          description: event.currentTarget.value,
                        })
                      }
                    />
                    <Button
                      variant="ghost"
                      size="xs"
                      pressed={field.required}
                      xstyle={field.required ? s.requiredActive : null}
                      aria-label={`${field.required ? "Make" : "Mark"} field ${index + 1} ${field.required ? "optional" : "required"}`}
                      className="nodrag nowheel"
                      onClick={() =>
                        replaceField(field.id, {
                          ...field,
                          required: !field.required,
                        })
                      }
                    >
                      Required
                    </Button>
                    <span {...stylex.props(sharedStyles.schemaFieldActions)}>
                      <IconButton
                        label={`Move field ${index + 1} up`}
                        title="Move field up"
                        size="xs"
                        className="nodrag nowheel"
                        xstyle={s.rowAction}
                        disabled={index === 0}
                        onClick={() =>
                          commitFields(
                            moveSchemaBuilderField(fields, field.id, index - 1),
                          )
                        }
                      >
                        <ArrowUp size={10} />
                      </IconButton>
                      <IconButton
                        label={`Move field ${index + 1} down`}
                        title="Move field down"
                        size="xs"
                        className="nodrag nowheel"
                        xstyle={s.rowAction}
                        disabled={index === fields.length - 1}
                        onClick={() =>
                          commitFields(
                            moveSchemaBuilderField(fields, field.id, index + 1),
                          )
                        }
                      >
                        <ArrowDown size={10} />
                      </IconButton>
                      <IconButton
                        label={`Remove field ${index + 1}`}
                        title="Remove field and its connection"
                        variant="danger"
                        size="xs"
                        className="nodrag nowheel"
                        xstyle={s.rowAction}
                        onClick={() =>
                          commitFields(
                            fields.filter(
                              (candidate) => candidate.id !== field.id,
                            ),
                          )
                        }
                      >
                        <Trash2 size={10} />
                      </IconButton>
                    </span>
                  </div>

                  {field.kind === "sequence" ? (
                    <div {...stylex.props(s.schemaItemRow)}>
                      <span {...stylex.props(s.schemaItemLabel)}>Items</span>
                      <Select
                        size="sm"
                        value={field.item_kind}
                        aria-label={`Field ${index + 1} item type`}
                        className="nodrag nowheel"
                        onChange={(event) =>
                          replaceField(field.id, {
                            ...field,
                            item_kind: event.currentTarget
                              .value as SchemaSequenceItemKind,
                          })
                        }
                      >
                        {SCHEMA_SEQUENCE_ITEM_KINDS.map((kind) => (
                          <option key={kind} value={kind}>
                            {SCHEMA_ITEM_KIND_LABELS[kind]}
                          </option>
                        ))}
                      </Select>
                      {field.item_kind === "schema" ? (
                        <span {...stylex.props(s.schemaConnectionRow)}>
                          <span
                            title={connectionLabel}
                            {...stylex.props(
                              s.schemaConnection,
                              s.schemaConnectionGrow,
                              binding ? s.schemaConnectionBound : null,
                            )}
                          >
                            {connectionLabel}
                          </span>
                          {inputPort ? (
                            <InstanceInputConnectionToggle
                              nodeId={id}
                              port={inputPort}
                              plugId={field.id}
                              label={`${field.name || `field ${index + 1}`} schema`}
                            />
                          ) : null}
                        </span>
                      ) : null}
                    </div>
                  ) : field.kind === "schema" ? (
                    <div {...stylex.props(s.schemaItemRow)}>
                      <span {...stylex.props(s.schemaItemLabel)}>Value</span>
                      <span
                        {...stylex.props(s.schemaConnectionRow)}
                        style={{ gridColumn: "2 / -1" }}
                      >
                        <span
                          title={connectionLabel}
                          {...stylex.props(
                            s.schemaConnection,
                            s.schemaConnectionGrow,
                            binding ? s.schemaConnectionBound : null,
                          )}
                        >
                          {connectionLabel}
                        </span>
                        {inputPort ? (
                          <InstanceInputConnectionToggle
                            nodeId={id}
                            port={inputPort}
                            plugId={field.id}
                            label={`${field.name || `field ${index + 1}`} schema`}
                          />
                        ) : null}
                      </span>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : (
          <Notice tone="neutral">
            Add a field to define this object schema.
          </Notice>
        )}

        <Button
          variant="dashed"
          size="sm"
          className="nodrag nowheel"
          onClick={() => {
            const names = new Set(fields.map((field) => field.name));
            let fieldNumber = fields.length + 1;
            while (names.has(`field_${fieldNumber}`)) fieldNumber += 1;
            commitFields([
              ...fields,
              createSchemaBuilderField(fieldNumber - 1),
            ]);
          }}
        >
          <Plus size={11} />
          Add field
        </Button>
      </section>
    </div>
  );
}
