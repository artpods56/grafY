"use client";

import * as stylex from "@stylexjs/stylex";
import { Handle, Position } from "@xyflow/react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import { createUuid } from "@/features/workbench/model/uuid";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { handleStyle } from "../../handle-style";
import { encodeHandleId } from "../../handles";
import { artifactTypeColor } from "../../nodes.css";
import {
  ARTIFACT_QUERY_RELATIONS_PORT,
  artifactQueryRelations,
  createArtifactQueryRelation,
  moveArtifactQueryRelation,
  reconcileArtifactQueryRelationInputPlugs,
  type ArtifactQueryRelation,
} from "../../query-artifact-tables";
import {
  portMetaForPort,
  resolvedPortArtifactType,
  type WorkflowNodeData,
} from "../../types";

import { InstanceInputConnectionToggle, nodeInteractionProps } from "./ports";
import { sharedStyles } from "./styles";

const s = stylex.create({
  queryRelationTop: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "18px minmax(0, 1fr)",
    alignItems: "center",
    gap: "4px",
  },
  queryRelationDetail: {
    minWidth: 0,
    minHeight: "24px",
    display: "flex",
    alignItems: "center",
    gap: "4px",
    marginLeft: "22px",
  },
  queryRelationSource: {
    minWidth: 0,
    flex: "1 1 auto",
    overflow: "hidden",
    color: tokens.colorMuted,
    fontSize: "10px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  queryRelationSourceBound: {
    color: tokens.colorTextEmphasis,
    fontWeight: 500,
  },
});

const ARTIFACT_QUERY_ALIAS_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

export function ArtifactQueryTablesBody({
  id,
  data,
}: {
  id: string;
  data: WorkflowNodeData;
}) {
  const relations = artifactQueryRelations(data.config.relations);
  const inputPort = data.spec.inputs.find(
    (port) => port.name === ARTIFACT_QUERY_RELATIONS_PORT,
  );
  const artifactType = inputPort
    ? resolvedPortArtifactType(inputPort, data.artifactTypeBindings)
    : null;
  const handleColor = artifactType
    ? artifactTypeColor(artifactType.id, tokens.colorAccent)
    : tokens.colorAccent;

  const commitRelations = (nextRelations: readonly ArtifactQueryRelation[]) => {
    const nextInputPlugs = reconcileArtifactQueryRelationInputPlugs(
      data.inputPlugs,
      nextRelations,
    );
    if (data.onArtifactQueryRelationsChange) {
      data.onArtifactQueryRelationsChange(id, nextRelations, nextInputPlugs);
    } else {
      data.onConfigChange?.(id, "relations", nextRelations);
    }
  };

  const replaceRelation = (
    relationId: string,
    nextRelation: ArtifactQueryRelation,
  ) => {
    commitRelations(
      relations.map((relation) =>
        relation.id === relationId ? nextRelation : relation,
      ),
    );
  };

  return (
    <div {...stylex.props(sharedStyles.schemaBody)}>
      <section
        {...stylex.props(sharedStyles.schemaFieldsSection)}
        aria-label="Artifact table relations"
      >
        <div {...stylex.props(sharedStyles.schemaFieldsHeader)}>
          <span {...stylex.props(sharedStyles.schemaFieldsTitle)}>
            Relations
          </span>
          <span {...stylex.props(sharedStyles.schemaFieldsCount)}>
            {relations.length} {relations.length === 1 ? "table" : "tables"}
            {" · ordered"}
          </span>
        </div>

        <div
          {...nodeInteractionProps(stylex.props(sharedStyles.schemaFieldList))}
        >
          {relations.map((relation, index) => {
            const binding = data.inputPlugBindings[relation.id];
            const connectionLabel = binding?.sourceLabel ?? "Connect table";
            const aliasIsUnique =
              relations.filter(
                (candidate) =>
                  candidate.alias.toLowerCase() ===
                  relation.alias.toLowerCase(),
              ).length === 1;
            const aliasIsValid =
              ARTIFACT_QUERY_ALIAS_PATTERN.test(relation.alias) &&
              aliasIsUnique;
            return (
              <div
                key={relation.id}
                {...stylex.props(sharedStyles.schemaFieldRow)}
              >
                {inputPort ? (
                  <Handle
                    className="nodrag nowheel"
                    type="target"
                    position={Position.Left}
                    id={encodeHandleId(
                      portMetaForPort(
                        inputPort,
                        inputPort.shape,
                        relation.id,
                        data.artifactTypeBindings,
                      ),
                    )}
                    aria-label={`Table relation ${relation.alias || index + 1}`}
                    title="Connect one table artifact here."
                    style={handleStyle("19px", handleColor, true)}
                  />
                ) : null}

                <div {...stylex.props(s.queryRelationTop)}>
                  <span {...stylex.props(sharedStyles.schemaFieldIndex)}>
                    {index + 1}
                  </span>
                  <input
                    type="text"
                    value={relation.alias}
                    pattern="[A-Za-z_][A-Za-z0-9_]*"
                    maxLength={128}
                    aria-label={`Relation ${index + 1} SQL alias`}
                    aria-invalid={!aliasIsValid}
                    title={
                      aliasIsValid
                        ? "SQL table name"
                        : "Use a unique SQL identifier: letters, digits, and underscores"
                    }
                    placeholder={`relation_${index + 1}`}
                    {...nodeInteractionProps(
                      stylex.props(sharedStyles.schemaCompactInput),
                    )}
                    onChange={(event) =>
                      replaceRelation(relation.id, {
                        ...relation,
                        alias: event.currentTarget.value,
                      })
                    }
                  />
                </div>

                <div {...stylex.props(s.queryRelationDetail)}>
                  <span
                    title={connectionLabel}
                    {...stylex.props(
                      s.queryRelationSource,
                      binding ? s.queryRelationSourceBound : null,
                    )}
                  >
                    {connectionLabel}
                  </span>
                  {inputPort ? (
                    <InstanceInputConnectionToggle
                      nodeId={id}
                      port={inputPort}
                      plugId={relation.id}
                      label={`${relation.alias || `relation ${index + 1}`} table`}
                    />
                  ) : null}
                  <span {...stylex.props(sharedStyles.schemaFieldActions)}>
                    <button
                      type="button"
                      disabled={index === 0}
                      aria-label={`Move relation ${index + 1} up`}
                      title="Move relation up"
                      {...nodeInteractionProps(
                        stylex.props(
                          sharedStyles.schemaFieldAction,
                          index === 0
                            ? sharedStyles.schemaFieldActionDisabled
                            : null,
                        ),
                      )}
                      onClick={() =>
                        commitRelations(
                          moveArtifactQueryRelation(
                            relations,
                            relation.id,
                            index - 1,
                          ),
                        )
                      }
                    >
                      <ArrowUp size={10} />
                    </button>
                    <button
                      type="button"
                      disabled={index === relations.length - 1}
                      aria-label={`Move relation ${index + 1} down`}
                      title="Move relation down"
                      {...nodeInteractionProps(
                        stylex.props(
                          sharedStyles.schemaFieldAction,
                          index === relations.length - 1
                            ? sharedStyles.schemaFieldActionDisabled
                            : null,
                        ),
                      )}
                      onClick={() =>
                        commitRelations(
                          moveArtifactQueryRelation(
                            relations,
                            relation.id,
                            index + 1,
                          ),
                        )
                      }
                    >
                      <ArrowDown size={10} />
                    </button>
                    <button
                      type="button"
                      disabled={relations.length === 1}
                      aria-label={`Remove relation ${index + 1}`}
                      title={
                        relations.length === 1
                          ? "At least one relation is required"
                          : "Remove relation and its connection"
                      }
                      {...nodeInteractionProps(
                        stylex.props(
                          sharedStyles.schemaFieldAction,
                          sharedStyles.schemaFieldRemove,
                          relations.length === 1
                            ? sharedStyles.schemaFieldActionDisabled
                            : null,
                        ),
                      )}
                      onClick={() =>
                        commitRelations(
                          relations.filter(
                            (candidate) => candidate.id !== relation.id,
                          ),
                        )
                      }
                    >
                      <Trash2 size={10} />
                    </button>
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        <button
          type="button"
          disabled={relations.length >= 32}
          {...nodeInteractionProps(stylex.props(sharedStyles.schemaAddField))}
          onClick={() =>
            commitRelations([
              ...relations,
              createArtifactQueryRelation(
                relations.length,
                createUuid(),
                relations,
              ),
            ])
          }
        >
          <Plus size={11} />
          Add relation
        </button>
      </section>
    </div>
  );
}
