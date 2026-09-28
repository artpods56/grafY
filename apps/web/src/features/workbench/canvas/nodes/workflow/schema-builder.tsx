"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Handle, Position } from "@xyflow/react";
import { ArrowDown, ArrowUp, GripVertical, Plus, Trash2 } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";

import { handleStyle } from "../../handle-style";
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
  schemaMetadataField: { display: "grid", gap: "3px" },
  schemaMetadataLabel: {
    color: tokens.colorMuted,
    fontSize: "10px",
    fontWeight: 600,
  },
  schemaToggle: {
    height: "28px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    paddingInline: "8px",
    borderWidth: 0,
    borderRadius: "7px",
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorHoverStrong,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 600,
    whiteSpace: "nowrap",
  },
  schemaToggleActive: {
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorTextEmphasis,
    boxShadow: `inset 0 0 0 1px ${tokens.colorAccentBorder}`,
  },
  schemaEmpty: {
    margin: 0,
    padding: "12px 10px",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
    textAlign: "center",
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
  schemaFieldGrip: {
    width: "18px",
    height: "26px",
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorSubtle,
    cursor: "grab",
    touchAction: "none",
  },
  schemaSelect: {
    width: "100%",
    minWidth: 0,
    height: "28px",
    paddingInline: "7px",
    borderWidth: 0,
    borderRadius: "7px",
    outline: {
      default: "none",
      ":focus": `2px solid ${tokens.colorAccentBorder}`,
    },
    backgroundColor: tokens.colorSurface,
    color: tokens.colorTextEmphasis,
    fontSize: "10px",
    fontWeight: 500,
  },
  schemaFieldDetail: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto auto",
    alignItems: "center",
    gap: "4px",
    marginLeft: "40px",
  },
  schemaRequired: {
    height: "24px",
    paddingInline: "7px",
    borderWidth: 0,
    borderRadius: "6px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorSubtle,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 600,
  },
  schemaRequiredActive: {
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorWarning,
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
          <label {...stylex.props(s.schemaMetadataField)}>
            <span {...stylex.props(s.schemaMetadataLabel)}>
              Schema title · optional
            </span>
            <input
              type="text"
              value={
                typeof data.config.title === "string" ? data.config.title : ""
              }
              placeholder="Response"
              {...nodeInteractionProps(
                stylex.props(sharedStyles.schemaCompactInput),
              )}
              onChange={(event) =>
                data.onConfigChange?.(id, "title", event.currentTarget.value)
              }
            />
          </label>
          <button
            type="button"
            aria-pressed={data.config.additional_properties === true}
            title="Allow properties not declared below"
            {...nodeInteractionProps(
              stylex.props(
                s.schemaToggle,
                data.config.additional_properties === true
                  ? s.schemaToggleActive
                  : null,
              ),
            )}
            onClick={() =>
              data.onConfigChange?.(
                id,
                "additional_properties",
                data.config.additional_properties !== true,
              )
            }
          >
            Extra fields
          </button>
        </div>
        <label {...stylex.props(s.schemaMetadataField)}>
          <span {...stylex.props(s.schemaMetadataLabel)}>
            Description · optional
          </span>
          <input
            type="text"
            value={
              typeof data.config.description === "string"
                ? data.config.description
                : ""
            }
            placeholder="What this response contains"
            {...nodeInteractionProps(
              stylex.props(sharedStyles.schemaCompactInput),
            )}
            onChange={(event) =>
              data.onConfigChange?.(
                id,
                "description",
                event.currentTarget.value,
              )
            }
          />
        </label>
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
                    <Handle
                      className="nodrag nowheel"
                      type="target"
                      position={Position.Left}
                      id={encodeHandleId(
                        portMetaForPort(
                          inputPort,
                          inputPort.shape,
                          field.id,
                          data.artifactTypeBindings,
                        ),
                      )}
                      aria-label={`Nested schema for ${field.name || `field ${index + 1}`}`}
                      title="Connect one JSON Schema output here."
                      style={handleStyle("19px", handleColor, true)}
                    />
                  ) : null}

                  <div {...stylex.props(s.schemaFieldTop)}>
                    <button
                      type="button"
                      aria-label={`Drag to reorder field ${index + 1}`}
                      title="Drag to reorder; arrow buttons also move this field"
                      {...nodeInteractionProps(stylex.props(s.schemaFieldGrip))}
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
                    </button>
                    <span {...stylex.props(sharedStyles.schemaFieldIndex)}>
                      {index + 1}
                    </span>
                    <input
                      type="text"
                      value={field.name}
                      placeholder="field_name"
                      aria-label={`Field ${index + 1} name`}
                      {...nodeInteractionProps(
                        stylex.props(sharedStyles.schemaCompactInput),
                      )}
                      onChange={(event) =>
                        replaceField(field.id, {
                          ...field,
                          name: event.currentTarget.value,
                        })
                      }
                    />
                    <select
                      value={field.kind}
                      aria-label={`Field ${index + 1} type`}
                      {...nodeInteractionProps(stylex.props(s.schemaSelect))}
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
                    </select>
                  </div>

                  <div {...stylex.props(s.schemaFieldDetail)}>
                    <input
                      type="text"
                      value={field.description}
                      placeholder="Description (optional)"
                      aria-label={`Field ${index + 1} description`}
                      {...nodeInteractionProps(
                        stylex.props(sharedStyles.schemaCompactInput),
                      )}
                      onChange={(event) =>
                        replaceField(field.id, {
                          ...field,
                          description: event.currentTarget.value,
                        })
                      }
                    />
                    <button
                      type="button"
                      aria-pressed={field.required}
                      aria-label={`${field.required ? "Make" : "Mark"} field ${index + 1} ${field.required ? "optional" : "required"}`}
                      {...nodeInteractionProps(
                        stylex.props(
                          s.schemaRequired,
                          field.required ? s.schemaRequiredActive : null,
                        ),
                      )}
                      onClick={() =>
                        replaceField(field.id, {
                          ...field,
                          required: !field.required,
                        })
                      }
                    >
                      Required
                    </button>
                    <span {...stylex.props(sharedStyles.schemaFieldActions)}>
                      <button
                        type="button"
                        disabled={index === 0}
                        aria-label={`Move field ${index + 1} up`}
                        title="Move field up"
                        {...nodeInteractionProps(
                          stylex.props(
                            sharedStyles.schemaFieldAction,
                            index === 0
                              ? sharedStyles.schemaFieldActionDisabled
                              : null,
                          ),
                        )}
                        onClick={() =>
                          commitFields(
                            moveSchemaBuilderField(fields, field.id, index - 1),
                          )
                        }
                      >
                        <ArrowUp size={10} />
                      </button>
                      <button
                        type="button"
                        disabled={index === fields.length - 1}
                        aria-label={`Move field ${index + 1} down`}
                        title="Move field down"
                        {...nodeInteractionProps(
                          stylex.props(
                            sharedStyles.schemaFieldAction,
                            index === fields.length - 1
                              ? sharedStyles.schemaFieldActionDisabled
                              : null,
                          ),
                        )}
                        onClick={() =>
                          commitFields(
                            moveSchemaBuilderField(fields, field.id, index + 1),
                          )
                        }
                      >
                        <ArrowDown size={10} />
                      </button>
                      <button
                        type="button"
                        aria-label={`Remove field ${index + 1}`}
                        title="Remove field and its connection"
                        {...nodeInteractionProps(
                          stylex.props(
                            sharedStyles.schemaFieldAction,
                            sharedStyles.schemaFieldRemove,
                          ),
                        )}
                        onClick={() =>
                          commitFields(
                            fields.filter(
                              (candidate) => candidate.id !== field.id,
                            ),
                          )
                        }
                      >
                        <Trash2 size={10} />
                      </button>
                    </span>
                  </div>

                  {field.kind === "sequence" ? (
                    <div {...stylex.props(s.schemaItemRow)}>
                      <span {...stylex.props(s.schemaItemLabel)}>Items</span>
                      <select
                        value={field.item_kind}
                        aria-label={`Field ${index + 1} item type`}
                        {...nodeInteractionProps(stylex.props(s.schemaSelect))}
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
                      </select>
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
          <p {...stylex.props(s.schemaEmpty)}>
            Add a field to define this object schema.
          </p>
        )}

        <button
          type="button"
          {...nodeInteractionProps(stylex.props(sharedStyles.schemaAddField))}
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
        </button>
      </section>
    </div>
  );
}
