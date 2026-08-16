"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Popover } from "@base-ui/react/popover";
import {
  Handle,
  Position,
  useEdges,
  useNodeConnections,
  useUpdateNodeInternals,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  ExternalLink,
  GripVertical,
  LoaderCircle,
  Plus,
  Power,
  RotateCcw,
  Sparkles,
  TriangleAlert,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import type { Port } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  CanvasNodeHeader,
  nodeChrome,
} from "./CanvasNodeChrome";
import {
  schemaFields,
  type NumberTupleItem,
  type NumberTupleSchemaField,
  type SchemaField,
  type StringListSchemaField,
} from "../config-schema";
import { useHandleIsDocked } from "../edges/useDockedConnection";
import { dockedHandleStyle, handleStyle } from "../handle-style";
import { decodeHandleId, encodeHandleId } from "../handles";
import {
  inputPlugsForPort,
  reconcileSchemaFieldInputPlugs,
} from "../input-plugs";
import { artifactTypeColor } from "../nodes.css";
import {
  nodeSecretDependencyRevision,
  nodeSecretInputs,
  type WorkflowNodeSecretInput,
  type WorkflowNodeSecretState,
} from "../node-secrets";
import {
  SCHEMA_BUILDER_INPUT_PORT,
  SCHEMA_BUILDER_OPERATOR_ID,
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
} from "../schema-builder";
import {
  resolvedBodyHeight,
  resolvedNodeWidth,
  type WorkflowNodeLayout,
} from "../node-layout";
import {
  ARTIFACT_QUERY_OPERATOR_ID,
  ARTIFACT_QUERY_RELATIONS_PORT,
  artifactQueryRelations,
  createArtifactQueryRelation,
  moveArtifactQueryRelation,
  reconcileArtifactQueryRelationInputPlugs,
  type ArtifactQueryRelation,
} from "../query-artifact-tables";
import {
  TABLE_FILE_IMPORT_OPERATOR_ID,
  GEOJSON_UPLOAD_OPERATOR_ID,
  GEOTIFF_UPLOAD_OPERATOR_ID,
  GIS_VECTOR_LAYER_OPERATOR_ID,
  WORKFLOW_NODE_TYPE,
  acceptedPortShapes,
  compatibilityHandleId,
  declaredArtifactTypeVariables,
  effectivePortShape,
  imageUploadSizeLabel,
  imageUploads,
  isFileUploadOperator,
  portHasInstancePlugs,
  portMetaForPort,
  resolvedPortArtifactType,
  type WorkflowEdge,
  type WorkflowInputPlug,
  type WorkflowNodeData,
} from "../types";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import {
  GRID_CELL_SIZE_DEFAULT,
  PORT_RAIL_ROW_HEIGHT_CELLS,
  lengthFromSpan,
  spanFromLength,
} from "../grid-layout";
import {
  CanvasNodeShell,
  useCanvasNodeShell,
} from "./CanvasNodeShell";
import {
  configBoardColumns,
  fieldFootprint,
  packFieldFootprints,
  secretFootprint,
  type FieldFootprint,
} from "./field-footprints";
import { LayoutResizeHandle } from "./LayoutResizeHandle";
import { NodeExecutionAppendix } from "./NodeExecutionAppendix";
import { TextareaBodyResizeHandle } from "./TextareaBodyResizeHandle";
import { PortTypePopover } from "./type-inspector";
import { VectorLayerStyleBody } from "./VectorLayerStyleBody";

type WorkflowNode = Node<WorkflowNodeData, typeof WORKFLOW_NODE_TYPE>;

const ACCEPTED_IMAGE_TYPES =
  ".png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp,image/png,image/jpeg,image/webp,image/tiff,image/bmp";

const s = stylex.create({
  compatibilityIcon: {
    color: tokens.colorWarning,
    flexShrink: 0,
  },
  compatibilityBadge: {
    height: "18px",
    display: "inline-flex",
    alignItems: "center",
    flexShrink: 0,
    paddingInline: "6px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    fontSize: "9px",
    fontWeight: 600,
    letterSpacing: "0.05em",
    lineHeight: 1,
    textTransform: "uppercase",
  },
  compatibilityBody: {
    display: "grid",
    gap: "9px",
    padding: "4px 12px 13px",
  },
  compatibilityIssue: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.5,
  },
  compatibilityConfig: {
    overflow: "hidden",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "6px",
    backgroundColor: tokens.colorSurface,
  },
  compatibilityConfigSummary: {
    padding: "7px 9px",
    color: tokens.colorSubtle,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 600,
  },
  compatibilityConfigValue: {
    maxHeight: "150px",
    overflow: "auto",
    margin: 0,
    padding: "8px 9px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
    color: tokens.colorMuted,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    lineHeight: 1.45,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
  compatibilityPort: {
    backgroundColor: {
      default: tokens.colorSurfaceSunken,
      ":hover": tokens.colorSurfaceSunken,
    },
    color: tokens.colorTextDisabled,
  },
  textareaHost: {
    position: "relative",
    width: "100%",
    minHeight: 0,
  },
  textareaHostFill: {
    flex: "1 1 0%",
    display: "flex",
    flexDirection: "column",
    minHeight: 0,
  },
  textareaFill: {
    flex: "1 1 0%",
    width: "100%",
    // Literal keeps StyleX happy (imported layout constants can't be used here).
    minHeight: "96px",
    height: "auto",
    resize: "none",
  },
  textareaDefault: {
    height: "96px",
  },
  header: {
    display: "grid",
    gap: "2px",
    padding: "12px 16px 12px 12px",
  },
  titleRow: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "4px",
  },
  /** Unsupported cards keep a direct remove: removal is the only repair. */
  removeButton: {
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover": tokens.colorDangerHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger },
  },
  /** Compact execution status stays visible without adding shell chrome. */
  executionDot: {
    width: "8px",
    height: "8px",
    flexShrink: 0,
    borderRadius: "9999px",
    backgroundColor: tokens.colorMuted,
  },
  executionDotSuccess: { backgroundColor: tokens.colorSuccess },
  executionDotDanger: { backgroundColor: tokens.colorDanger },
  executionSpinner: { flexShrink: 0, color: tokens.colorInfo },
  executionSpinnerWarning: { color: tokens.colorWarning },
  operatorRow: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "6px",
    marginLeft: "56px",
  },
  operatorCopy: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  openModuleSource: {
    flexShrink: 0,
    minHeight: "18px",
    display: "inline-flex",
    alignItems: "center",
    gap: "3px",
    paddingInline: "5px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "4px",
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover": tokens.colorHover,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 600,
  },
  upgradeModuleCall: {
    flexShrink: 0,
    minHeight: "22px",
    display: "inline-flex",
    alignItems: "center",
    gap: "3px",
    paddingInline: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "4px",
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover": tokens.colorHover,
    },
    color: tokens.colorText,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 600,
  },
  generationBadge: {
    flexShrink: 0,
    minHeight: "22px",
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    paddingInline: "7px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "9999px",
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
    fontSize: "10px",
    fontWeight: 650,
  },
  generationAction: {
    flexShrink: 0,
    minHeight: "22px",
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    paddingInline: "7px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "9999px",
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover": tokens.colorHover,
      ":disabled": tokens.colorSurfaceSunken,
    },
    color: tokens.colorTextEmphasis,
    cursor: { default: "pointer", ":disabled": "wait" },
    fontFamily: "inherit",
    fontSize: "10px",
    fontWeight: 700,
  },
  tabs: {
    display: "grid",
    gap: "5px",
    paddingBlock: "2px",
  },
  tabsOutput: {
    display: "grid",
    gap: "5px",
    paddingTop: "2px",
    paddingBottom: "14px",
  },
  plugPorts: {
    display: "grid",
    gap: "5px",
    paddingBlock: "2px",
  },
  genericTypes: {
    display: "grid",
    gap: "5px",
    padding: "0 10px 8px",
  },
  genericTypeRow: {
    minHeight: "30px",
    display: "flex",
    alignItems: "center",
    gap: "7px",
    padding: "5px 7px",
    borderRadius: "7px",
    backgroundColor: tokens.colorSurfaceMuted,
  },
  genericTypeDot: {
    width: "6px",
    height: "6px",
    flexShrink: 0,
    borderRadius: "9999px",
    backgroundColor: tokens.colorAccent,
  },
  genericTypeCopy: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  genericTypeBound: {
    color: tokens.colorTextEmphasis,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontWeight: 500,
  },
  resetType: {
    minHeight: "22px",
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    paddingInline: "6px",
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorMuted, ":hover": tokens.colorText },
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 500,
  },
  resetTypeDisabled: {
    color: tokens.colorSubtle,
    cursor: "not-allowed",
    opacity: 0.55,
  },
  plugGroup: {
    display: "grid",
    gap: "5px",
    paddingBottom: "4px",
  },
  plugPortHeader: {
    minHeight: "24px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    paddingInline: "12px 10px",
  },
  plugPortTitle: {
    display: "flex",
    minWidth: 0,
    alignItems: "center",
    gap: "7px",
    padding: 0,
    overflow: "hidden",
    borderWidth: 0,
    backgroundColor: "transparent",
    color: tokens.colorTextEmphasis,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  plugPortRule: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
  plugList: {
    display: "grid",
    gap: "4px",
    paddingInline: "8px",
  },
  plugRow: {
    position: "relative",
    minWidth: 0,
    minHeight: "38px",
    display: "grid",
    gridTemplateColumns: "20px 20px minmax(0, 1fr) auto",
    alignItems: "center",
    gap: "4px",
    padding: "3px 4px 3px 28px",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceMuted,
  },
  plugRowDragging: {
    backgroundColor: tokens.colorAccentSoft,
    boxShadow: `inset 0 0 0 1px ${tokens.colorAccentBorder}`,
  },
  plugGrip: {
    width: "20px",
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
  plugIndex: {
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    textAlign: "center",
  },
  plugCopy: {
    minWidth: 0,
    display: "grid",
    gap: "1px",
  },
  plugSource: {
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  plugSourceEmpty: { color: tokens.colorMuted, fontWeight: 550 },
  plugMeta: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: "10px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  plugActions: { display: "flex", alignItems: "center", gap: "1px" },
  plugAction: {
    width: "18px",
    height: "20px",
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorText },
    cursor: "pointer",
  },
  plugActionDisabled: {
    color: tokens.colorTextDisabled,
    cursor: "default",
    opacity: 0.45,
  },
  plugRemove: {
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger },
  },
  addPlug: {
    minHeight: "26px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "5px",
    marginInline: "8px",
    paddingInline: "8px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorHoverStrong,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  tabWithToggle: {
    paddingInlineEnd: "5px",
  },
  tabTrigger: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "7px",
    height: "100%",
    padding: 0,
    borderWidth: 0,
    backgroundColor: "transparent",
    color: "inherit",
    cursor: "pointer",
    font: "inherit",
  },
  tabDisabled: {
    color: tokens.colorTextDisabled,
    backgroundColor: {
      default: tokens.colorSurfaceSunken,
      ":hover": tokens.colorSurfaceSunken,
    },
  },
  connectionToggle: {
    width: "18px",
    height: "18px",
    flexShrink: 0,
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "9999px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHoverStrong,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
  },
  connectionToggleEnabled: {
    color: tokens.colorAccent,
    backgroundColor: {
      default: tokens.colorAccentSoft,
      ":hover": tokens.colorAccentSoft,
    },
  },
  connectionToggleDisabled: {
    color: tokens.colorTextDisabled,
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover": tokens.colorHover,
    },
  },
  plugConnectionToggle: {
    width: "18px",
    height: "20px",
    borderRadius: "5px",
  },
  dot: {
    width: "6px",
    height: "6px",
    flexShrink: 0,
    borderRadius: "9999px",
  },
  body: {
    display: "grid",
    gap: "9px",
    padding: "0 16px 6px",
    minHeight: 0,
  },
  /**
   * Config bricks sit on the lattice: columns come from the node width, rows
   * are whole cells that may stretch when a brick's content outgrows them.
   * Row gap stays 0 so the packed cell count still predicts the body height;
   * the slack inside each brick is the visual gutter.
   */
  configBoard: {
    display: "grid",
    columnGap: "10px",
    rowGap: 0,
    minWidth: 0,
    alignItems: "stretch",
  },
  /** The reserved gutter below every brick is what separates adjacent shelves. */
  configBrick: {
    minWidth: 0,
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    paddingBottom: "8px",
  },
  fieldSized: {
    flex: "1 1 0%",
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
  },
  upload: {
    width: "100%",
    minHeight: "34px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "7px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorHover,
    },
    color: tokens.colorTextEmphasis,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  hiddenInput: {
    position: "absolute",
    width: "1px",
    height: "1px",
    overflow: "hidden",
    clip: "rect(0 0 0 0)",
    whiteSpace: "nowrap",
  },
  fileList: {
    maxHeight: "132px",
    display: "grid",
    gap: "5px",
    overflowY: "auto",
  },
  fileRow: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "18px minmax(0,1fr) auto 22px",
    alignItems: "center",
    gap: "6px",
    minHeight: "28px",
    paddingInline: "10px 4px",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceMuted,
  },
  fileIndex: {
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
  },
  fileName: {
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 550,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  fileSize: { color: tokens.colorSubtle, fontSize: tokens.fontSizeXs },
  fileRemove: {
    width: "22px",
    height: "22px",
    display: "grid",
    placeItems: "center",
    borderWidth: 0,
    borderRadius: "6px",
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorDangerHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger },
    cursor: "pointer",
  },
  moreFiles: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  field: { display: "grid", alignContent: "start", gap: "4px" },
  tupleField: {
    minWidth: 0,
    margin: 0,
    padding: 0,
    borderWidth: 0,
  },
  tupleGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: "6px",
  },
  tupleItem: { minWidth: 0, display: "grid", gap: "3px" },
  tupleItemLabel: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  tupleError: {
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  stringList: {
    display: "grid",
    gap: "5px",
  },
  stringListRow: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 31px",
    alignItems: "center",
    gap: "5px",
  },
  stringListRemove: {
    width: "31px",
    height: "31px",
    display: "grid",
    placeItems: "center",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorDangerHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger },
    cursor: "pointer",
    opacity: { ":disabled": 0.4 },
  },
  stringListAdd: {
    minHeight: "29px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "5px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorHover,
    },
    color: tokens.colorTextEmphasis,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
    opacity: { ":disabled": 0.4 },
  },
  fieldLabel: {
    minWidth: 0,
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    gap: "3px",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    textTransform: "capitalize",
  },
  fieldLabelText: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  srOnly: {
    position: "absolute",
    width: "1px",
    height: "1px",
    margin: "-1px",
    padding: 0,
    overflow: "hidden",
    clipPath: "inset(50%)",
    whiteSpace: "nowrap",
    borderWidth: 0,
  },
  input: {
    width: "100%",
    height: "31px",
    paddingInline: "10px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    outline: {
      default: "none",
      ":focus": `2px solid ${tokens.colorAccentBorder}`,
    },
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
  },
  textarea: {
    paddingBlock: "8px",
    lineHeight: 1.45,
    resize: "none",
  },
  codeTextarea: {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: tokens.fontSizeXs,
    tabSize: 2,
  },
  /**
   * Same silhouette as text inputs: full-width 31px bar, check on the
   * trailing edge. Checked state lives on the well, not the bar.
   */
  checkBox: {
    position: "relative",
    width: "100%",
    height: "31px",
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    paddingInline: "10px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceMuted,
    cursor: "pointer",
    outline: {
      default: "none",
      ":focus-within": `2px solid ${tokens.colorAccentBorder}`,
    },
  },
  checkWell: {
    width: "18px",
    height: "18px",
    flexShrink: 0,
    display: "grid",
    placeItems: "center",
    borderRadius: tokens.radiusSm,
    color: tokens.colorOnAccent,
    boxShadow: `inset 0 0 0 1px ${tokens.colorBorder}`,
  },
  checkWellChecked: {
    backgroundColor: tokens.colorAccent,
    boxShadow: "none",
  },
  checkInput: {
    position: "absolute",
    inset: 0,
    margin: 0,
    opacity: 0,
    cursor: "pointer",
  },
  checkMark: {
    opacity: 0,
    transform: "scale(0.85)",
  },
  checkMarkChecked: {
    opacity: 1,
    transform: "scale(1)",
  },
  /** Structural schema metadata, so it stays out of the port/type colour range. */
  required: { color: tokens.colorSubtle, fontSize: tokens.fontSizeSm },
  secretField: { display: "grid", alignContent: "start", gap: "5px" },
  secretHeader: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
  },
  secretStatus: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 600,
  },
  secretStatusConfigured: { color: tokens.colorSuccess },
  secretStatusStale: { color: tokens.colorWarning },
  secretStatusError: { color: tokens.colorDanger },
  secretControl: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: "5px",
  },
  secretInput: { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
  secretButton: {
    minWidth: "54px",
    height: "31px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "5px",
    paddingInline: "9px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: tokens.colorAccentSoft,
      ":hover": tokens.colorHoverStrong,
    },
    color: tokens.colorTextEmphasis,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 600,
  },
  secretButtonDisabled: {
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorTextDisabled,
    cursor: "not-allowed",
  },
  secretFooter: {
    minHeight: "18px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
  },
  secretHint: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.35,
  },
  secretRemove: {
    flexShrink: 0,
    padding: 0,
    borderWidth: 0,
    backgroundColor: "transparent",
    color: {
      default: tokens.colorSubtle,
      ":hover": tokens.colorDanger,
    },
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 500,
  },
  secretRemoveDisabled: {
    color: tokens.colorTextDisabled,
    cursor: "not-allowed",
  },
  schemaBody: {
    display: "grid",
    gap: "10px",
    padding: "0 8px 12px",
  },
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
  schemaCompactInput: {
    width: "100%",
    minWidth: 0,
    height: "28px",
    paddingInline: "8px",
    borderWidth: 0,
    borderRadius: "7px",
    outline: {
      default: "none",
      ":focus": `2px solid ${tokens.colorAccentBorder}`,
    },
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
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
  schemaFieldsSection: { display: "grid", gap: "5px" },
  schemaFieldsHeader: {
    minHeight: "24px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    paddingInline: "5px",
  },
  schemaFieldsTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
  },
  schemaFieldsCount: { color: tokens.colorSubtle, fontSize: "10px" },
  schemaFieldList: {
    display: "grid",
    gap: "5px",
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
  schemaFieldRow: {
    position: "relative",
    minWidth: 0,
    display: "grid",
    gap: "5px",
    padding: "6px 6px 6px 28px",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceMuted,
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
  schemaFieldIndex: {
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    textAlign: "center",
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
  schemaFieldActions: { display: "flex", alignItems: "center", gap: "1px" },
  schemaFieldAction: {
    width: "18px",
    height: "22px",
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorText },
    cursor: "pointer",
  },
  schemaFieldActionDisabled: {
    color: tokens.colorTextDisabled,
    cursor: "default",
    opacity: 0.45,
  },
  schemaFieldRemove: {
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger },
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
  schemaAddField: {
    minHeight: "28px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "5px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorHoverStrong,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
  },
  emptyBody: {
    padding: "0 16px 14px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  spacer: { minHeight: "4px" },
  spinner: {
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});

function nodeInteractionProps(props: ReturnType<typeof stylex.props>) {
  return {
    ...props,
    className: `nodrag nowheel${props.className ? ` ${props.className}` : ""}`,
  };
}

function useOptionalInputConnection(
  nodeId: string,
  port: Port,
  plugId?: string,
) {
  const edges = useEdges<WorkflowEdge>();
  return React.useMemo(() => {
    if (port.direction !== "input") return null;
    const edge = edges.find((candidate) => {
      if (candidate.target !== nodeId) return false;
      const handle = decodeHandleId(candidate.targetHandle);
      if (!handle || handle.portName !== port.name) return false;
      if (plugId !== undefined) return handle.plugId === plugId;
      return handle.plugId === undefined;
    });
    const onUpdate = edge?.data?.onUpdate;
    if (!edge || !onUpdate) return null;
    const enabled = edge.data?.enabled !== false;
    // Only optional ports can be disabled; still allow re-enabling a
    // connection that was left disabled against a required input.
    if (port.required && enabled) return null;
    return {
      enabled,
      toggle: () => onUpdate(edge.id, { enabled: !enabled }),
    };
  }, [edges, nodeId, plugId, port.direction, port.name, port.required]);
}

function OptionalConnectionToggle({
  connection,
  label,
  compact = false,
}: {
  connection: { enabled: boolean; toggle: () => void };
  label: string;
  compact?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={connection.enabled}
      aria-label={`${label} connection enabled`}
      title={
        connection.enabled ? "Disable connection" : "Enable connection"
      }
      {...nodeInteractionProps(
        stylex.props(
          s.connectionToggle,
          connection.enabled
            ? s.connectionToggleEnabled
            : s.connectionToggleDisabled,
          compact ? s.plugConnectionToggle : null,
        ),
      )}
      onClick={(event) => {
        event.stopPropagation();
        connection.toggle();
      }}
    >
      <Power size={compact ? 10 : 11} aria-hidden="true" />
    </button>
  );
}

/**
 * Shared port rail: one lattice-tall row per index, input on the left and
 * output on the right so neighboring nodes can Lego-join on the same Y.
 */
function PortRail({
  id,
  data,
  inputPorts,
  outputPorts,
}: {
  id: string;
  data: WorkflowNodeData;
  inputPorts: readonly Port[];
  outputPorts: readonly Port[];
}) {
  const grid = useOptionalCanvasGridSettings();
  const cellSize = grid?.settings.cellSize ?? GRID_CELL_SIZE_DEFAULT;
  const rowHeight = lengthFromSpan(PORT_RAIL_ROW_HEIGHT_CELLS, cellSize);
  const rowCount = Math.max(inputPorts.length, outputPorts.length);
  if (rowCount === 0) return null;

  return (
    <div data-testid="port-rail" {...stylex.props(nodeChrome.portRail)}>
      {Array.from({ length: rowCount }, (_, index) => {
        const input = inputPorts[index];
        const output = outputPorts[index];
        return (
          <div
            key={`port-rail-row-${index}`}
            data-testid="port-rail-row"
            style={{ height: rowHeight }}
            {...stylex.props(nodeChrome.portRailRow)}
          >
            <div {...stylex.props(nodeChrome.portRailSlot)}>
              {input ? (
                <PortTab
                  id={id}
                  data={data}
                  port={input}
                  shape={effectivePortShape(data, input)}
                />
              ) : null}
            </div>
            <div {...stylex.props(nodeChrome.portRailSlot, nodeChrome.portRailSlotOut)}>
              {output ? (
                <PortTab
                  id={id}
                  data={data}
                  port={output}
                  shape={effectivePortShape(data, output)}
                />
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PortTab({
  id,
  data,
  port,
  shape,
}: {
  id: string;
  data: WorkflowNodeData;
  port: Port;
  shape: Port["shape"];
}) {
  const input = port.direction === "input";
  const connection = useOptionalInputConnection(id, port);
  const visibleName = port.title ?? port.name;
  const artifactType = resolvedPortArtifactType(
    port,
    data.artifactTypeBindings,
  );
  const color = artifactType
    ? artifactTypeColor(artifactType.id, tokens.colorAccent)
    : tokens.colorAccent;
  const artifactContract = artifactType
    ? `${artifactType.id}@${artifactType.schema_version}`
    : "Any artifact";
  const effectiveContract =
    shape === "many" ? `list[${artifactContract}]` : artifactContract;
  const accessibleLabel = input
    ? `Input port ${visibleName}, accepts ${effectiveContract}${port.required ? ", required" : ""}`
    : `Output port ${visibleName}, provides ${effectiveContract}`;
  const connectionDisabled = Boolean(connection && !connection.enabled);
  const handleId = encodeHandleId(
    portMetaForPort(
      port,
      input ? port.shape : shape,
      undefined,
      data.artifactTypeBindings,
    ),
  );
  const docked = useHandleIsDocked(id, handleId);

  return (
    <div
      data-docked-port={docked ? "true" : undefined}
      {...stylex.props(nodeChrome.tabRow, input ? null : nodeChrome.tabRowOut)}
    >
      <div
        {...stylex.props(
          nodeChrome.tab,
          input ? nodeChrome.tabIn : nodeChrome.tabOut,
          connection ? s.tabWithToggle : null,
          connectionDisabled ? s.tabDisabled : null,
          docked ? nodeChrome.tabDocked : null,
        )}
      >
        <PortTypePopover
          port={port}
          shape={shape}
          artifactTypeBindings={data.artifactTypeBindings}
        >
          <Popover.Trigger
            type="button"
            aria-label={`Inspect ${visibleName} type`}
            title={port.description ?? `Inspect ${visibleName} type`}
            {...nodeInteractionProps(stylex.props(s.tabTrigger))}
          >
            <span {...stylex.props(nodeChrome.tabLabel)}>{visibleName}</span>
            {input && port.required ? (
              <span {...stylex.props(s.required, nodeChrome.tabShape)}>*</span>
            ) : null}
            {shape === "many" ? (
              <span {...stylex.props(nodeChrome.tabShape)}>· many</span>
            ) : null}
          </Popover.Trigger>
        </PortTypePopover>
        {connection ? (
          <OptionalConnectionToggle
            connection={connection}
            label={visibleName}
          />
        ) : null}
      </div>
      <Handle
        type={input ? "target" : "source"}
        position={input ? Position.Left : Position.Right}
        id={handleId}
        aria-hidden={docked}
        aria-label={accessibleLabel}
        title={
          input
            ? `${accessibleLabel}. Connect a compatible output here.${port.description ? ` ${port.description}` : ""}`
            : `${accessibleLabel}. Drag to a compatible input. If fields are available, you can choose what arrives after connecting.${port.description ? ` ${port.description}` : ""}`
        }
        style={
          docked
            ? dockedHandleStyle("50%")
            : handleStyle("50%", color, shape === "many")
        }
      />
    </div>
  );
}

function InstancePlugRow({
  id,
  data,
  port,
  plug,
  index,
  plugCount,
  visibleName,
  acceptedShapeLabel,
  color,
  draggedPlugId,
  draggedPlugIdRef,
  lastPointerTargetRef,
  setDraggedPlugId,
  finishPointerDrag,
}: {
  id: string;
  data: WorkflowNodeData;
  port: Port;
  plug: WorkflowInputPlug;
  index: number;
  plugCount: number;
  visibleName: string;
  acceptedShapeLabel: string;
  color: string;
  draggedPlugId: string | null;
  draggedPlugIdRef: React.MutableRefObject<string | null>;
  lastPointerTargetRef: React.MutableRefObject<string | null>;
  setDraggedPlugId: React.Dispatch<React.SetStateAction<string | null>>;
  finishPointerDrag: (event: React.PointerEvent<HTMLButtonElement>) => void;
}) {
  const connection = useOptionalInputConnection(id, port, plug.id);
  const binding = data.inputPlugBindings[plug.id];
  const connectionMeta = binding
    ? [
        binding.sourceShape === "many" ? "sequence" : "single",
        binding.conversionLabel ? `feed ${binding.conversionLabel}` : null,
        binding.contributionLabel,
      ]
        .filter((label): label is string => Boolean(label))
        .join(" · ")
    : `Accepts ${acceptedShapeLabel}`;
  const accessibleLabel = `${visibleName} input ${index + 1}, accepts ${acceptedShapeLabel}`;
  const connectionDisabled = Boolean(connection && !connection.enabled);

  return (
    <div
      data-input-plug-id={plug.id}
      data-input-plug-port={port.name}
      {...stylex.props(
        s.plugRow,
        draggedPlugId === plug.id ? s.plugRowDragging : null,
      )}
    >
      <Handle
        className="nodrag nowheel"
        type="target"
        position={Position.Left}
        id={encodeHandleId(
          portMetaForPort(
            port,
            port.shape,
            plug.id,
            data.artifactTypeBindings,
          ),
        )}
        aria-label={accessibleLabel}
        title={`${accessibleLabel}. Connect one compatible output here.`}
        style={handleStyle("50%", color, true)}
      />
      <button
        type="button"
        aria-label={`Drag to reorder ${visibleName} input ${index + 1}`}
        title="Drag to reorder; arrow buttons also move this input"
        {...nodeInteractionProps(stylex.props(s.plugGrip))}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.stopPropagation();
          event.currentTarget.setPointerCapture(event.pointerId);
          draggedPlugIdRef.current = plug.id;
          lastPointerTargetRef.current = plug.id;
          setDraggedPlugId(plug.id);
        }}
        onPointerMove={(event) => {
          const activePlugId = draggedPlugIdRef.current;
          if (!activePlugId) return;
          event.preventDefault();
          event.stopPropagation();
          const target = document
            .elementFromPoint(event.clientX, event.clientY)
            ?.closest<HTMLElement>("[data-input-plug-id]");
          const targetPlugId = target?.dataset.inputPlugId;
          if (targetPlugId === activePlugId) {
            lastPointerTargetRef.current = null;
            return;
          }
          if (
            !targetPlugId ||
            target?.dataset.inputPlugPort !== port.name ||
            targetPlugId === lastPointerTargetRef.current
          ) {
            return;
          }
          const targetIndex = inputPlugsForPort(
            data.inputPlugs,
            port.name,
          ).findIndex((candidate) => candidate.id === targetPlugId);
          if (targetIndex === -1) return;
          lastPointerTargetRef.current = targetPlugId;
          data.onReorderInputPlug?.(id, port.name, activePlugId, targetIndex);
        }}
        onPointerUp={finishPointerDrag}
        onPointerCancel={finishPointerDrag}
      >
        <GripVertical size={12} />
      </button>
      <span {...stylex.props(s.plugIndex)}>{index + 1}</span>
      <span {...stylex.props(s.plugCopy)}>
        <span
          {...stylex.props(
            s.plugSource,
            binding ? null : s.plugSourceEmpty,
            connectionDisabled ? s.tabDisabled : null,
          )}
          title={binding?.sourceLabel}
        >
          {binding?.sourceLabel ?? "Connect input"}
        </span>
        <span {...stylex.props(s.plugMeta)} title={connectionMeta}>
          {connectionMeta}
        </span>
      </span>
      <span {...stylex.props(s.plugActions)}>
        {connection ? (
          <OptionalConnectionToggle
            connection={connection}
            label={`${visibleName} input ${index + 1}`}
            compact
          />
        ) : null}
        <button
          type="button"
          disabled={index === 0}
          aria-label={`Move ${visibleName} input ${index + 1} up`}
          title="Move input up"
          {...nodeInteractionProps(
            stylex.props(
              s.plugAction,
              index === 0 ? s.plugActionDisabled : null,
            ),
          )}
          onClick={() =>
            data.onReorderInputPlug?.(id, port.name, plug.id, index - 1)
          }
        >
          <ArrowUp size={10} />
        </button>
        <button
          type="button"
          disabled={index === plugCount - 1}
          aria-label={`Move ${visibleName} input ${index + 1} down`}
          title="Move input down"
          {...nodeInteractionProps(
            stylex.props(
              s.plugAction,
              index === plugCount - 1 ? s.plugActionDisabled : null,
            ),
          )}
          onClick={() =>
            data.onReorderInputPlug?.(id, port.name, plug.id, index + 1)
          }
        >
          <ArrowDown size={10} />
        </button>
        <button
          type="button"
          aria-label={`Remove ${visibleName} input ${index + 1}`}
          title="Remove input and its connection"
          {...nodeInteractionProps(stylex.props(s.plugAction, s.plugRemove))}
          onClick={() => data.onRemoveInputPlug?.(id, plug.id)}
        >
          <Trash2 size={10} />
        </button>
      </span>
    </div>
  );
}

function InstancePlugPort({
  id,
  data,
  port,
}: {
  id: string;
  data: WorkflowNodeData;
  port: Port;
}) {
  const plugs = inputPlugsForPort(data.inputPlugs, port.name);
  const [draggedPlugId, setDraggedPlugId] = React.useState<string | null>(null);
  const draggedPlugIdRef = React.useRef<string | null>(null);
  const lastPointerTargetRef = React.useRef<string | null>(null);
  const visibleName = port.title ?? port.name;
  const artifactType = resolvedPortArtifactType(
    port,
    data.artifactTypeBindings,
  );
  const color = artifactType
    ? artifactTypeColor(artifactType.id, tokens.colorAccent)
    : tokens.colorAccent;
  const acceptedShapeLabel = acceptedPortShapes(port)
    .map((shape) => (shape === "many" ? "sequence" : "single"))
    .join(" or ");

  const finishPointerDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    draggedPlugIdRef.current = null;
    lastPointerTargetRef.current = null;
    setDraggedPlugId(null);
  };

  return (
    <section {...stylex.props(s.plugGroup)} aria-label={`${visibleName} inputs`}>
      <div {...stylex.props(s.plugPortHeader)}>
        <PortTypePopover
          port={port}
          shape={port.shape}
          artifactTypeBindings={data.artifactTypeBindings}
        >
          <button
            type="button"
            aria-label={`Inspect ${visibleName} type`}
            title={port.description ?? `Inspect ${visibleName} type`}
            {...nodeInteractionProps(stylex.props(s.plugPortTitle))}
          >
            <span {...stylex.props(s.dot)} style={{ backgroundColor: color }} />
            <span {...stylex.props(nodeChrome.tabLabel)}>{visibleName}</span>
            {port.required ? <span {...stylex.props(s.required)}>*</span> : null}
          </button>
        </PortTypePopover>
        <span {...stylex.props(s.plugPortRule)}>
          {acceptedShapeLabel} · plug order
        </span>
      </div>

      <div {...stylex.props(s.plugList)}>
        {plugs.map((plug, index) => (
          <InstancePlugRow
            key={plug.id}
            id={id}
            data={data}
            port={port}
            plug={plug}
            index={index}
            plugCount={plugs.length}
            visibleName={visibleName}
            acceptedShapeLabel={acceptedShapeLabel}
            color={color}
            draggedPlugId={draggedPlugId}
            draggedPlugIdRef={draggedPlugIdRef}
            lastPointerTargetRef={lastPointerTargetRef}
            setDraggedPlugId={setDraggedPlugId}
            finishPointerDrag={finishPointerDrag}
          />
        ))}
      </div>
      <button
        type="button"
        {...nodeInteractionProps(stylex.props(s.addPlug))}
        onClick={() => data.onAddInputPlug?.(id, port.name)}
      >
        <Plus size={11} />
        Add input
      </button>
    </section>
  );
}

function GenericArtifactTypeState({
  id,
  data,
  resettable,
}: {
  id: string;
  data: WorkflowNodeData;
  resettable: boolean;
}) {
  const variables = declaredArtifactTypeVariables(data.spec);
  if (!variables.length) return null;

  return (
    <div {...stylex.props(s.genericTypes)} aria-label="Generic artifact types">
      {variables.map((variable) => {
        const artifactType = data.artifactTypeBindings[variable];
        const label = artifactType
          ? `${artifactType.id}@${artifactType.schema_version}`
          : "Any artifact · binds on connect";
        return (
          <div key={variable} {...stylex.props(s.genericTypeRow)}>
            <span
              aria-hidden="true"
              {...stylex.props(s.genericTypeDot)}
              style={
                artifactType
                  ? {
                      backgroundColor:
                        artifactTypeColor(
                          artifactType.id,
                          tokens.colorAccent,
                        ),
                    }
                  : undefined
              }
            />
            <span
              title={`${variable}: ${label}`}
              {...stylex.props(
                s.genericTypeCopy,
                artifactType ? s.genericTypeBound : null,
              )}
            >
              {label}
            </span>
            {artifactType ? (
              <button
                type="button"
                disabled={!resettable || !data.onResetArtifactTypeBinding}
                aria-label={`Reset artifact type ${variable}`}
                title={
                  resettable
                    ? "Reset type"
                    : "Disconnect this node before resetting its type"
                }
                {...nodeInteractionProps(
                  stylex.props(
                    s.resetType,
                    resettable ? null : s.resetTypeDisabled,
                  ),
                )}
                onClick={() => data.onResetArtifactTypeBinding?.(id, variable)}
              >
                <RotateCcw size={10} />
                Reset type
              </button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Descriptions ride the label tooltip instead of taking a line in the brick:
 * they are schema documentation you read once, not state you monitor.
 */
function FieldLabelText({
  title,
  description,
}: {
  title: string;
  description?: string | null;
}) {
  return (
    <span
      title={description ? `${title} — ${description}` : title}
      {...stylex.props(s.fieldLabelText)}
    >
      {title}
    </span>
  );
}

function numberTupleValue(value: unknown, length: number): number[] | null {
  if (
    !Array.isArray(value) ||
    value.length !== length ||
    !value.every(
      (item): item is number =>
        typeof item === "number" && Number.isFinite(item),
    )
  ) {
    return null;
  }
  return value;
}

function numberTupleValueSignature(value: unknown, length: number): string {
  const tuple = numberTupleValue(value, length);
  if (tuple) return `tuple:${JSON.stringify(tuple)}`;
  return value === null ? `null:${length}` : `unset:${length}`;
}

function parseNumberTupleDraft(
  values: readonly string[],
  items: readonly NumberTupleItem[],
): number[] | null {
  if (values.length !== items.length) return null;
  const parsedValues: number[] = [];
  for (const [index, item] of items.entries()) {
    const raw = values[index] ?? "";
    if (raw === "") return null;
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return null;
    if (item.type === "integer" && !Number.isInteger(parsed)) return null;
    if (item.minimum !== undefined && parsed < item.minimum) return null;
    if (item.maximum !== undefined && parsed > item.maximum) return null;
    parsedValues.push(parsed);
  }
  return parsedValues;
}

function NumberTupleConfigField({
  field,
  value,
  onChange,
}: {
  field: NumberTupleSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const itemCount = field.items.length;
  const valueSignature = numberTupleValueSignature(value, itemCount);
  const [draftValues, setDraftValues] = React.useState<string[]>(() => {
    const tuple = numberTupleValue(value, itemCount);
    return tuple?.map(String) ?? Array.from({ length: itemCount }, () => "");
  });
  const [touched, setTouched] = React.useState(false);
  const previousValueSignature = React.useRef(valueSignature);
  const pendingValueSignature = React.useRef<string | null>(null);

  React.useEffect(() => {
    if (previousValueSignature.current === valueSignature) return;
    previousValueSignature.current = valueSignature;
    if (pendingValueSignature.current === valueSignature) {
      pendingValueSignature.current = null;
      return;
    }

    pendingValueSignature.current = null;
    const tuple = numberTupleValue(value, itemCount);
    setDraftValues(
      tuple?.map(String) ?? Array.from({ length: itemCount }, () => ""),
    );
    setTouched(false);
  }, [itemCount, value, valueSignature]);

  const draftIsEmpty = draftValues.every((raw) => raw === "");
  const draftIsValid = parseNumberTupleDraft(draftValues, field.items) !== null;
  const showError =
    touched &&
    !draftIsValid &&
    (!draftIsEmpty || (field.required && !field.nullable));

  return (
    <fieldset {...stylex.props(s.field, s.tupleField)}>
      <legend {...stylex.props(s.fieldLabel)}>
        <FieldLabelText
          title={field.title}
          description={
            field.nullable
              ? `${field.description ?? ""} Leave every value blank to use no bounds.`.trim()
              : field.description
          }
        />
        {field.required ? <span {...stylex.props(s.required)}>*</span> : null}
      </legend>
      <div {...stylex.props(s.tupleGrid)}>
        {field.items.map((item, index) => (
          <label key={`${item.title}:${index}`} {...stylex.props(s.tupleItem)}>
            <span title={item.title} {...stylex.props(s.tupleItemLabel)}>
              {item.title}
            </span>
            <input
              type="number"
              aria-label={`${field.title}: ${item.title}`}
              aria-invalid={showError}
              value={draftValues[index] ?? ""}
              min={item.minimum}
              max={item.maximum}
              step={item.type === "integer" ? 1 : "any"}
              {...nodeInteractionProps(stylex.props(s.input))}
              onChange={(event) => {
                const nextDraftValues = [...draftValues];
                nextDraftValues[index] = event.currentTarget.value;
                setDraftValues(nextDraftValues);
                setTouched(true);

                const parsedValues = parseNumberTupleDraft(
                  nextDraftValues,
                  field.items,
                );
                const nextValue =
                  parsedValues ?? (field.nullable ? null : undefined);
                pendingValueSignature.current = numberTupleValueSignature(
                  nextValue,
                  itemCount,
                );
                onChange(nextValue);
              }}
            />
          </label>
        ))}
      </div>
      {showError ? (
        <span role="alert" {...stylex.props(s.tupleError)}>
          Enter all {itemCount} values as numbers within the shown ranges.
        </span>
      ) : null}
    </fieldset>
  );
}

function StringListConfigField({
  field,
  value,
  onChange,
}: {
  field: StringListSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const values = Array.isArray(value) && value.every(
    (item): item is string => typeof item === "string",
  )
    ? value
    : [];
  const minimumItems = field.minItems ?? 0;
  const canAdd =
    field.maxItems === undefined || values.length < field.maxItems;
  const canRemove = values.length > minimumItems;

  return (
    <fieldset {...stylex.props(s.field, s.tupleField)}>
      <legend {...stylex.props(s.fieldLabel)}>
        <FieldLabelText title={field.title} description={field.description} />
        {field.required ? <span {...stylex.props(s.required)}>*</span> : null}
      </legend>
      <div {...stylex.props(s.stringList)}>
        {values.map((item, index) => (
          <div key={index} {...stylex.props(s.stringListRow)}>
            <input
              type="text"
              aria-label={`${field.title} item ${index + 1}`}
              value={item}
              minLength={field.itemMinLength}
              maxLength={field.itemMaxLength}
              pattern={field.itemPattern}
              {...nodeInteractionProps(stylex.props(s.input))}
              onChange={(event) => {
                const nextValues = [...values];
                nextValues[index] = event.currentTarget.value;
                onChange(nextValues);
              }}
            />
            <button
              type="button"
              aria-label={`Remove ${field.title} item ${index + 1}`}
              title="Remove item"
              disabled={!canRemove}
              {...nodeInteractionProps(stylex.props(s.stringListRemove))}
              onClick={() => {
                onChange(values.filter((_, itemIndex) => itemIndex !== index));
              }}
            >
              <Trash2 size={13} />
            </button>
          </div>
        ))}
        <button
          type="button"
          aria-label={`Add ${field.title} item`}
          disabled={!canAdd}
          {...nodeInteractionProps(stylex.props(s.stringListAdd))}
          onClick={() => onChange([...values, ""])}
        >
          <Plus size={13} />
          Add item
        </button>
      </div>
    </fieldset>
  );
}

function ConfigField({
  field,
  value,
  onChange,
  fillHeight = false,
  labelHidden = false,
  layout = null,
  onLayoutDraft,
  onLayoutCommit,
}: {
  field: SchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
  fillHeight?: boolean;
  /** Kept for assistive tech when the node title already names the field. */
  labelHidden?: boolean;
  layout?: WorkflowNodeLayout | null;
  onLayoutDraft?: (layout: WorkflowNodeLayout | null) => void;
  onLayoutCommit?: (layout: WorkflowNodeLayout | null) => void;
}) {
  const fieldProps = stylex.props(s.field, fillHeight ? s.fieldSized : null);
  const labelProps = stylex.props(s.fieldLabel, labelHidden ? s.srOnly : null);
  const canResizeBody =
    field.type === "string" &&
    field.format === "textarea" &&
    onLayoutDraft &&
    onLayoutCommit;
  if (field.type === "number-tuple") {
    return (
      <NumberTupleConfigField
        field={field}
        value={value}
        onChange={onChange}
      />
    );
  }
  if (field.type === "string-list") {
    return (
      <StringListConfigField
        field={field}
        value={value}
        onChange={onChange}
      />
    );
  }
  if (field.type === "boolean") {
    const checked = value === true;
    return (
      <label {...fieldProps}>
        <span {...labelProps}>
          <FieldLabelText title={field.title} description={field.description} />
          {field.required ? <span {...stylex.props(s.required)}>*</span> : null}
        </span>
        <span {...stylex.props(s.checkBox)}>
          <input
            type="checkbox"
            checked={checked}
            aria-label={field.title}
            {...nodeInteractionProps(stylex.props(s.checkInput))}
            onChange={(event) => onChange(event.currentTarget.checked)}
          />
          <span
            {...stylex.props(s.checkWell, checked ? s.checkWellChecked : null)}
          >
            <Check
              size={13}
              strokeWidth={2.5}
              aria-hidden
              {...stylex.props(
                s.checkMark,
                checked ? s.checkMarkChecked : null,
              )}
            />
          </span>
        </span>
      </label>
    );
  }

  return (
    <label {...fieldProps}>
      <span {...labelProps}>
        <FieldLabelText title={field.title} description={field.description} />
        {field.required ? <span {...stylex.props(s.required)}>*</span> : null}
      </span>
      {field.enumValues ? (
        <select
          value={
            typeof value === "string" || typeof value === "number" ? value : ""
          }
          {...nodeInteractionProps(stylex.props(s.input))}
          onChange={(event) => {
            const selected = event.currentTarget.value;
            onChange(
              field.type === "number" || field.type === "integer"
                ? Number(selected)
                : selected,
            );
          }}
        >
          {typeof value !== "string" && typeof value !== "number" ? (
            <option value="" disabled>
              Choose an option
            </option>
          ) : null}
          {field.enumValues.map((option) => (
            <option key={String(option)} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : field.type === "string" && field.format === "textarea" ? (
        <div
          {...stylex.props(
            s.textareaHost,
            fillHeight ? s.textareaHostFill : null,
          )}
        >
          <textarea
            value={typeof value === "string" ? value : ""}
            minLength={field.minLength}
            maxLength={field.maxLength}
            {...nodeInteractionProps(
              stylex.props(
                s.input,
                s.textarea,
                field.codeLanguage ? s.codeTextarea : null,
                fillHeight ? s.textareaFill : s.textareaDefault,
              ),
            )}
            onChange={(event) => onChange(event.currentTarget.value)}
          />
          {canResizeBody ? (
            <TextareaBodyResizeHandle
              layout={layout}
              ariaLabel={`Resize ${field.title} field`}
              onDraft={onLayoutDraft}
              onCommit={onLayoutCommit}
            />
          ) : null}
        </div>
      ) : (
        <input
          type={
            field.type === "number" || field.type === "integer"
              ? "number"
              : "text"
          }
          value={
            typeof value === "string" || typeof value === "number" ? value : ""
          }
          min={field.minimum}
          max={field.maximum}
          minLength={field.minLength}
          maxLength={field.maxLength}
          pattern={field.pattern}
          step={field.type === "integer" ? 1 : undefined}
          {...nodeInteractionProps(stylex.props(s.input))}
          onChange={(event) => {
            const raw = event.currentTarget.value;
            onChange(
              field.type === "number" || field.type === "integer"
                ? raw === ""
                  ? undefined
                  : Number(raw)
                : raw,
            );
          }}
        />
      )}
    </label>
  );
}

const SECRET_STATUS_LABEL: Record<WorkflowNodeSecretState, string> = {
  unknown: "Status unavailable",
  loading: "Checking…",
  unconfigured: "Not configured",
  configured: "Configured",
  stale: "Stale",
  applying: "Applying…",
  removing: "Removing…",
  error: "Action failed",
};

function SecretInputField({
  id,
  data,
  input,
}: {
  id: string;
  data: WorkflowNodeData;
  input: WorkflowNodeSecretInput;
}) {
  const [value, setValue] = React.useState("");
  const storedStatus = data.secretStatuses[input.name] ?? { state: "unknown" };
  const ready = data.secretInputReadiness[input.name] ?? false;
  const status = !ready && storedStatus.state === "configured"
    ? { state: "stale" as const }
    : storedStatus;
  const busy = status.state === "applying" || status.state === "removing";
  const canApply =
    ready && !busy && value.length > 0 &&
    Boolean(data.onApplyNodeSecret);
  const canRemove =
    ready && !busy && status.state === "configured" &&
    Boolean(data.onRemoveNodeSecret);
  const hint = !ready
    ? status.state === "stale"
      ? "Save the changed secret settings, then apply a new secret."
      : "Save this node before configuring this secret."
    : status.state === "stale"
      ? "Apply a key for the current endpoint."
      : status.state === "error"
        ? status.message ?? "The secret action could not be completed."
        : input.description ?? "Write-only · the stored value cannot be read back.";

  return (
    <form
      {...nodeInteractionProps(stylex.props(s.secretField))}
      onSubmit={(event) => {
        event.preventDefault();
        if (!canApply) return;
        void data.onApplyNodeSecret?.(id, input.name, value).then((applied) => {
          if (applied) setValue("");
        });
      }}
    >
      <div {...stylex.props(s.secretHeader)}>
        <span {...stylex.props(s.fieldLabel)}>
          <FieldLabelText title={input.title} />
        </span>
        <span
          role="status"
          {...stylex.props(
            s.secretStatus,
            status.state === "configured" ? s.secretStatusConfigured : null,
            status.state === "stale" ? s.secretStatusStale : null,
            status.state === "error" ? s.secretStatusError : null,
          )}
        >
          {SECRET_STATUS_LABEL[status.state]}
        </span>
      </div>
      <div {...stylex.props(s.secretControl)}>
        <input
          type="password"
          name={`${id}-${input.name}`}
          value={value}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          data-1p-ignore
          data-lpignore="true"
          data-bwignore
          aria-label={input.title}
          placeholder={status.state === "configured" ? "Replace secret" : "Enter secret"}
          disabled={!ready || busy}
          {...nodeInteractionProps(stylex.props(s.input, s.secretInput))}
          onChange={(event) => setValue(event.currentTarget.value)}
        />
        <button
          type="submit"
          disabled={!canApply}
          {...nodeInteractionProps(
            stylex.props(
              s.secretButton,
              canApply ? null : s.secretButtonDisabled,
            ),
          )}
        >
          {status.state === "applying" ? (
            <LoaderCircle size={11} {...stylex.props(s.spinner)} />
          ) : null}
          Apply
        </button>
      </div>
      <div {...stylex.props(s.secretFooter)}>
        <p {...stylex.props(s.secretHint)}>{hint}</p>
        <button
          type="button"
          disabled={!canRemove}
          {...nodeInteractionProps(
            stylex.props(
              s.secretRemove,
              canRemove ? null : s.secretRemoveDisabled,
            ),
          )}
          onClick={() => {
            if (!canRemove) return;
            void data.onRemoveNodeSecret?.(id, input.name).then((removed) => {
              if (removed) setValue("");
            });
          }}
        >
          Remove
        </button>
      </div>
    </form>
  );
}

function FileUploadBody({ id, data }: { id: string; data: WorkflowNodeData }) {
  const uploads = imageUploads(data);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const isGeoJson = data.spec.operator_id === GEOJSON_UPLOAD_OPERATOR_ID;
  const isGeoTiff = data.spec.operator_id === GEOTIFF_UPLOAD_OPERATOR_ID;
  const isTableFile = data.spec.operator_id === TABLE_FILE_IMPORT_OPERATOR_ID;
  const isSingleFile = isGeoJson || isGeoTiff || isTableFile;
  const acceptedTypes = isGeoJson
    ? ".geojson,.json,application/geo+json,application/json"
    : isGeoTiff
      ? ".tif,.tiff,image/tiff,application/geotiff"
      : isTableFile
        ? ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        : ACCEPTED_IMAGE_TYPES;

  return (
    <div {...stylex.props(s.body)}>
      <input
        ref={inputRef}
        type="file"
        multiple={!isSingleFile}
        accept={acceptedTypes}
        {...nodeInteractionProps(stylex.props(s.hiddenInput))}
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files ?? []);
          event.currentTarget.value = "";
          if (files.length) data.onImagesSelected?.(id, files);
        }}
      />
      {uploads.length ? (
        <div {...nodeInteractionProps(stylex.props(s.fileList))}>
          {uploads.map((upload, index) => (
            <div
              key={`${upload.upload_key}-${index}`}
              {...stylex.props(s.fileRow)}
            >
              <span {...stylex.props(s.fileIndex)}>
                {String(index + 1).padStart(2, "0")}
              </span>
              <span {...stylex.props(s.fileName)}>{upload.filename}</span>
              <span {...stylex.props(s.fileSize)}>
                {imageUploadSizeLabel(upload.byte_size)}
              </span>
              <button
                type="button"
                aria-label={`Remove ${upload.filename}`}
                title={`Remove ${upload.filename}`}
                {...nodeInteractionProps(stylex.props(s.fileRemove))}
                onClick={() => data.onRemoveImageUpload?.(id, index)}
              >
                <Trash2 size={10} />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p {...stylex.props(s.moreFiles)}>
          {isGeoJson
            ? "GeoJSON FeatureCollection · WGS84 longitude/latitude"
            : isGeoTiff
              ? "Georeferenced GeoTIFF or Cloud Optimized GeoTIFF"
              : isTableFile
                ? "UTF-8 CSV or Excel workbook"
                : "PNG, JPEG, WebP, TIFF or BMP · ordered as selected"}
        </p>
      )}
      <button
        type="button"
        {...nodeInteractionProps(stylex.props(s.upload))}
        onClick={() => inputRef.current?.click()}
      >
        {data.execution.status === "uploading" ? (
          <LoaderCircle size={12} {...stylex.props(s.spinner)} />
        ) : (
          <Upload size={12} />
        )}
        {data.execution.status === "uploading"
          ? "Uploading…"
          : uploads.length
            ? isSingleFile ? "Replace file" : "Replace images"
            : isGeoJson
              ? "Choose GeoJSON"
              : isGeoTiff
                ? "Choose GeoTIFF"
                : isTableFile
                  ? "Choose CSV or XLSX"
                  : "Choose images"}
      </button>
    </div>
  );
}

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

const ARTIFACT_QUERY_ALIAS_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

function InstanceInputConnectionToggle({
  nodeId,
  port,
  plugId,
  label,
}: {
  nodeId: string;
  port: Port;
  plugId: string;
  label: string;
}) {
  const connection = useOptionalInputConnection(nodeId, port, plugId);
  if (!connection) return null;
  return (
    <OptionalConnectionToggle
      connection={connection}
      label={label}
      compact
    />
  );
}

function SchemaBuilderBody({
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
    <div {...stylex.props(s.schemaBody)}>
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
              {...nodeInteractionProps(stylex.props(s.schemaCompactInput))}
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
            {...nodeInteractionProps(stylex.props(s.schemaCompactInput))}
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

      <section {...stylex.props(s.schemaFieldsSection)} aria-label="Schema fields">
        <div {...stylex.props(s.schemaFieldsHeader)}>
          <span {...stylex.props(s.schemaFieldsTitle)}>Fields</span>
          <span {...stylex.props(s.schemaFieldsCount)}>
            {fields.length} {fields.length === 1 ? "field" : "fields"} · ordered
          </span>
        </div>

        {fields.length ? (
          <div
            {...nodeInteractionProps(stylex.props(s.schemaFieldList))}
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
                    s.schemaFieldRow,
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
                      {...nodeInteractionProps(
                        stylex.props(s.schemaFieldGrip),
                      )}
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
                    <span {...stylex.props(s.schemaFieldIndex)}>
                      {index + 1}
                    </span>
                    <input
                      type="text"
                      value={field.name}
                      placeholder="field_name"
                      aria-label={`Field ${index + 1} name`}
                      {...nodeInteractionProps(
                        stylex.props(s.schemaCompactInput),
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
                        stylex.props(s.schemaCompactInput),
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
                    <span {...stylex.props(s.schemaFieldActions)}>
                      <button
                        type="button"
                        disabled={index === 0}
                        aria-label={`Move field ${index + 1} up`}
                        title="Move field up"
                        {...nodeInteractionProps(
                          stylex.props(
                            s.schemaFieldAction,
                            index === 0
                              ? s.schemaFieldActionDisabled
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
                            s.schemaFieldAction,
                            index === fields.length - 1
                              ? s.schemaFieldActionDisabled
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
                            s.schemaFieldAction,
                            s.schemaFieldRemove,
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
          {...nodeInteractionProps(stylex.props(s.schemaAddField))}
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

function ArtifactQueryTablesBody({
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

  const commitRelations = (
    nextRelations: readonly ArtifactQueryRelation[],
  ) => {
    const nextInputPlugs = reconcileArtifactQueryRelationInputPlugs(
      data.inputPlugs,
      nextRelations,
    );
    if (data.onArtifactQueryRelationsChange) {
      data.onArtifactQueryRelationsChange(
        id,
        nextRelations,
        nextInputPlugs,
      );
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
    <div {...stylex.props(s.schemaBody)}>
      <section
        {...stylex.props(s.schemaFieldsSection)}
        aria-label="Artifact table relations"
      >
        <div {...stylex.props(s.schemaFieldsHeader)}>
          <span {...stylex.props(s.schemaFieldsTitle)}>Relations</span>
          <span {...stylex.props(s.schemaFieldsCount)}>
            {relations.length} {relations.length === 1 ? "table" : "tables"}
            {" · ordered"}
          </span>
        </div>

        <div {...nodeInteractionProps(stylex.props(s.schemaFieldList))}>
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
              <div key={relation.id} {...stylex.props(s.schemaFieldRow)}>
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
                  <span {...stylex.props(s.schemaFieldIndex)}>{index + 1}</span>
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
                      stylex.props(s.schemaCompactInput),
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
                  <span {...stylex.props(s.schemaFieldActions)}>
                    <button
                      type="button"
                      disabled={index === 0}
                      aria-label={`Move relation ${index + 1} up`}
                      title="Move relation up"
                      {...nodeInteractionProps(
                        stylex.props(
                          s.schemaFieldAction,
                          index === 0 ? s.schemaFieldActionDisabled : null,
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
                          s.schemaFieldAction,
                          index === relations.length - 1
                            ? s.schemaFieldActionDisabled
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
                          s.schemaFieldAction,
                          s.schemaFieldRemove,
                          relations.length === 1
                            ? s.schemaFieldActionDisabled
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
          {...nodeInteractionProps(stylex.props(s.schemaAddField))}
          onClick={() =>
            commitRelations([
              ...relations,
              createArtifactQueryRelation(
                relations.length,
                crypto.randomUUID(),
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

export type ConfigBrick =
  | { kind: "field"; field: SchemaField; footprint: FieldFootprint }
  | {
      kind: "secret";
      input: WorkflowNodeSecretInput;
      footprint: FieldFootprint;
    };

/**
 * A lone field whose title the node title already contains ("Text" on a "Text
 * input" node) names the same thing twice. The label stays in the accessibility
 * tree; only its row is reclaimed. Booleans keep theirs — a bare checkbox
 * reads as nothing at all.
 */
export function configFieldLabelIsRedundant(
  nodeTitle: string,
  bricks: readonly ConfigBrick[],
): boolean {
  const only = bricks.length === 1 ? bricks[0] : undefined;
  if (only?.kind !== "field" || only.field.type === "boolean") return false;
  const squash = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");
  const title = squash(only.field.title);
  return title.length > 0 && squash(nodeTitle).includes(title);
}

function configBricks(data: WorkflowNodeData): ConfigBrick[] {
  return [
    ...schemaFields(data.spec.config_schema).map(
      (field): ConfigBrick => ({
        kind: "field",
        field,
        footprint: fieldFootprint(field),
      }),
    ),
    ...nodeSecretInputs(data.spec).map(
      (input): ConfigBrick => ({
        kind: "secret",
        input,
        footprint: secretFootprint(),
      }),
    ),
  ];
}

/**
 * Config inputs are packed onto the body lattice in schema order. Widening the
 * node stretches the existing bricks first (more room for labels/descriptions);
 * packing only adds columns once another half-brick can stay comfortably wide.
 * A saved body height is only a request — the board grows whenever the ordered
 * bricks need more rows.
 */
function GenericBody({
  id,
  data,
  bodyHeight,
  layout,
  onLayoutDraft,
  onLayoutCommit,
}: {
  id: string;
  data: WorkflowNodeData;
  bodyHeight: number | null;
  layout: WorkflowNodeLayout | null;
  onLayoutDraft: (layout: WorkflowNodeLayout | null) => void;
  onLayoutCommit: (layout: WorkflowNodeLayout | null) => void;
}) {
  const grid = useOptionalCanvasGridSettings();
  const bricks = configBricks(data);
  if (!bricks.length) return null;

  const cellSize = grid?.settings.cellSize ?? GRID_CELL_SIZE_DEFAULT;
  const labelHidden = configFieldLabelIsRedundant(data.spec.title, bricks);
  const board = packFieldFootprints(
    bricks.map((brick) => brick.footprint),
    {
      columns: configBoardColumns(resolvedNodeWidth(layout), cellSize),
      minRows: bodyHeight === null ? 0 : spanFromLength(bodyHeight, cellSize),
    },
  );

  return (
    <div {...stylex.props(s.body)}>
      <div
        data-testid="config-board"
        {...stylex.props(s.configBoard)}
        style={{
          gridTemplateColumns: `repeat(${board.columns}, minmax(0, 1fr))`,
          gridTemplateRows: `repeat(${board.rows}, minmax(${cellSize}px, auto))`,
        }}
      >
        {board.placements.map((placement) => {
          const brick = bricks[placement.index];
          if (!brick) return null;
          const fillsCell = brick.footprint.growY === true;
          return (
            <div
              key={
                brick.kind === "field"
                  ? `field:${brick.field.name}`
                  : `secret:${brick.input.name}`
              }
              data-testid="config-brick"
              {...stylex.props(s.configBrick)}
              style={{
                gridColumn: `${placement.col + 1} / span ${placement.w}`,
                gridRow: `${placement.row + 1} / span ${placement.h}`,
              }}
            >
              {brick.kind === "field" ? (
                <ConfigField
                  field={brick.field}
                  value={data.config[brick.field.name]}
                  fillHeight={fillsCell}
                  labelHidden={labelHidden}
                  layout={layout}
                  onLayoutDraft={onLayoutDraft}
                  onLayoutCommit={onLayoutCommit}
                  onChange={(value) =>
                    data.onConfigChange?.(id, brick.field.name, value)
                  }
                />
              ) : (
                <SecretInputField
                  key={`${data.secretInputScope}:${brick.input.name}:${nodeSecretDependencyRevision(brick.input, data.config)}`}
                  id={id}
                  data={data}
                  input={brick.input}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * One cell of chrome: the title always reads, everything else (about popover
 * with provenance, removal) appears once the node is selected. Execution keeps
 * only a status tell here — the status icon and appendix carry the detail.
 */
function NodeHeader({
  id,
  data,
  selected,
}: {
  id: string;
  data: WorkflowNodeData;
  selected: boolean;
}) {
  const executionLabel = data.execution.status === "idle"
    ? null
    : data.execution.status;
  const executionIsBusy =
    data.execution.status === "uploading" ||
    data.execution.status === "running" ||
    data.execution.status === "cancelling";
  const generation =
    data.generation?.state === "published" ? null : data.generation;
  const generationIsBusy = generation
    ? ["queued", "claimed", "preparing", "coding", "testing", "cancelling", "interrupting"].includes(
        generation.state,
      )
    : false;
  const canReviewGeneration = Boolean(
    generation?.state === "awaiting_approval" &&
      generation.buildId &&
      data.onReviewGeneratedNode,
  );
  const canIterateGeneration = Boolean(
    data.spec.agent_authoring?.runnable &&
      data.generation?.state === "published" &&
      data.generation?.threadId &&
      data.onIterateGeneratedNode,
  );

  return (
    <CanvasNodeHeader
      title={data.spec.title}
      selected={selected}
      aboutLabel={`About ${data.spec.title}`}
      aboutTitle={data.spec.title}
      aboutDescription={
        data.spec.description ||
        "No description is available for this node."
      }
      aboutFooter={
        <>
          <span {...stylex.props(s.operatorCopy)}>
            {typeof data.spec.module_graph_revision === "number"
              ? `Module · r${data.spec.module_graph_revision}`
              : `${data.spec.operator_id}@${data.spec.operator_version}`}
          </span>
          {data.spec.module_graph_id && data.onOpenModuleSource ? (
            <button
              type="button"
              aria-label={`Open source graph for ${data.spec.title}`}
              title="Open source graph"
              {...nodeInteractionProps(stylex.props(s.openModuleSource))}
              onClick={() => {
                if (!data.spec.module_graph_id) return;
                data.onOpenModuleSource?.(data.spec.module_graph_id);
              }}
            >
              <ExternalLink size={9} />
              Source
            </button>
          ) : null}
        </>
      }
      onRemove={() => data.onRemoveNode?.(id)}
      status={
        generation ? (
          generationIsBusy ? (
            <LoaderCircle
              size={11}
              role="status"
              aria-label={`Draft ${generation.state}`}
              {...stylex.props(s.spinner, s.executionSpinner)}
            />
          ) : (
            <Sparkles
              size={11}
              role="status"
              aria-label={`Draft ${generation.state}`}
              {...stylex.props(
                generation.state === "failed" ? s.compatibilityIcon : null,
              )}
            />
          )
        ) : executionLabel ? (
          executionIsBusy ? (
            <LoaderCircle
              size={11}
              role="status"
              aria-label={`Execution ${executionLabel}`}
              {...stylex.props(
                s.spinner,
                s.executionSpinner,
                data.execution.status === "cancelling"
                  ? s.executionSpinnerWarning
                  : null,
              )}
            />
          ) : (
            <span
              role="status"
              aria-label={`Execution ${executionLabel}`}
              title={`Execution ${executionLabel}`}
              {...stylex.props(
                s.executionDot,
                data.execution.status === "succeeded"
                  ? s.executionDotSuccess
                  : null,
                data.execution.status === "failed" ? s.executionDotDanger : null,
              )}
            />
          )
        ) : null
      }
    >
      {generation ? (
        <span
          title={generation.error ?? `Generated node draft: ${generation.state}`}
          {...stylex.props(s.generationBadge)}
        >
          <Sparkles size={10} />
          Revision {generation.targetOperatorVersion} · {generation.state.replaceAll("_", " ")}
        </span>
      ) : null}
      {canReviewGeneration && generation ? (
        <button
          type="button"
          aria-label={`Review generated build for ${data.spec.title}`}
          title="Inspect tested source and requested capabilities"
          {...nodeInteractionProps(stylex.props(s.generationAction))}
          onClick={() => data.onReviewGeneratedNode?.(id, generation)}
        >
          <Sparkles size={10} />
          Review build
        </button>
      ) : null}
      {canIterateGeneration && data.generation ? (
        <button
          type="button"
          aria-label={`Iterate on ${data.spec.title}`}
          title={`Keep version ${data.spec.operator_version} runnable while building the next revision`}
          {...nodeInteractionProps(stylex.props(s.generationAction))}
          onClick={() => data.onIterateGeneratedNode?.(id, data.generation!)}
        >
          <Sparkles size={10} />
          Iterate
        </button>
      ) : null}
      {typeof data.moduleUpgradeRelease === "number" &&
      data.onUpgradeModuleCall ? (
        <button
          type="button"
          aria-label={`Upgrade module call to release ${data.moduleUpgradeRelease}`}
          title={`Upgrade to release ${data.moduleUpgradeRelease}`}
          {...nodeInteractionProps(stylex.props(s.upgradeModuleCall))}
          onClick={() => data.onUpgradeModuleCall?.(id)}
        >
          <ArrowUp size={11} />
          Upgrade to release {data.moduleUpgradeRelease}
        </button>
      ) : null}
    </CanvasNodeHeader>
  );
}

type IncompatibleWorkflowNodeCompatibility = Exclude<
  WorkflowNodeData["compatibility"],
  { status: "supported" }
>;

function CompatibilityPort({
  direction,
  endpoint,
}: {
  direction: "input" | "output";
  endpoint: IncompatibleWorkflowNodeCompatibility["inputs"][number];
}) {
  const input = direction === "input";
  const label = endpoint.plugId
    ? `${endpoint.portName} · ${endpoint.plugId}`
    : endpoint.portName;
  return (
    <div {...stylex.props(nodeChrome.tabRow, input ? null : nodeChrome.tabRowOut)}>
      <div
        {...stylex.props(
          nodeChrome.tab,
          input ? nodeChrome.tabIn : nodeChrome.tabOut,
          s.compatibilityPort,
        )}
        title={`Historical ${direction} ${label}`}
      >
        <span {...stylex.props(nodeChrome.tabLabel)}>{label}</span>
      </div>
      <Handle
        type={input ? "target" : "source"}
        position={input ? Position.Left : Position.Right}
        id={compatibilityHandleId(direction, endpoint)}
        isConnectable={false}
        aria-label={`Unavailable ${direction} port ${label}`}
        title={`This historical ${direction} cannot accept new connections.`}
        style={{
          ...handleStyle("50%", tokens.colorMuted),
          cursor: "not-allowed",
          opacity: 0.72,
        }}
      />
    </div>
  );
}

function CompatibilityPortRail({
  inputs,
  outputs,
}: {
  inputs: IncompatibleWorkflowNodeCompatibility["inputs"];
  outputs: IncompatibleWorkflowNodeCompatibility["outputs"];
}) {
  const grid = useOptionalCanvasGridSettings();
  const cellSize = grid?.settings.cellSize ?? GRID_CELL_SIZE_DEFAULT;
  const rowHeight = lengthFromSpan(PORT_RAIL_ROW_HEIGHT_CELLS, cellSize);
  const rowCount = Math.max(inputs.length, outputs.length);
  if (rowCount === 0) return null;

  return (
    <div data-testid="port-rail" {...stylex.props(nodeChrome.portRail)}>
      {Array.from({ length: rowCount }, (_, index) => {
        const input = inputs[index];
        const output = outputs[index];
        return (
          <div
            key={`compat-rail-row-${index}`}
            data-testid="port-rail-row"
            style={{ height: rowHeight }}
            {...stylex.props(nodeChrome.portRailRow)}
          >
            <div {...stylex.props(nodeChrome.portRailSlot)}>
              {input ? (
                <CompatibilityPort direction="input" endpoint={input} />
              ) : null}
            </div>
            <div {...stylex.props(nodeChrome.portRailSlot, nodeChrome.portRailSlotOut)}>
              {output ? (
                <CompatibilityPort direction="output" endpoint={output} />
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function IncompatibleWorkflowNodeCard({
  id,
  data,
  selected,
  dragging,
  compatibility,
}: {
  id: string;
  data: WorkflowNodeData;
  selected: boolean;
  dragging: boolean;
  compatibility: IncompatibleWorkflowNodeCompatibility;
}) {
  const updateNodeInternals = useUpdateNodeInternals();
  const grid = useOptionalCanvasGridSettings();
  const allowCornerResize =
    grid?.settings.allowWorkflowCornerResize ?? false;
  const [draftLayout, setDraftLayout] = React.useState<WorkflowNodeLayout | null>(
    null,
  );
  const layout = draftLayout ?? data.layout;
  const nodeWidth = resolvedNodeWidth(layout);
  const shell = useCanvasNodeShell({
    id,
    selected,
    dragging,
    naturalWidth: nodeWidth,
    updateNodeInternals,
  });
  const { gridWidth, paintWidth, fillMinHeight } = shell;
  const endpointRevision = JSON.stringify({
    inputs: compatibility.inputs,
    outputs: compatibility.outputs,
  });
  const hasProgress = Boolean(data.progress?.entries.length);
  const hasExecutionError = Boolean(data.execution.error);
  const hasMaterialization = (data.run?.outputs ?? []).some(
    (output) => output.artifacts.length > 0,
  );
  const hasSavedHistory = Boolean(data.historyContext?.graphId);

  React.useLayoutEffect(() => {
    updateNodeInternals(id);
  }, [
    endpointRevision,
    fillMinHeight,
    gridWidth,
    hasExecutionError,
    hasMaterialization,
    hasProgress,
    hasSavedHistory,
    id,
    updateNodeInternals,
  ]);

  const commitLayout = React.useCallback(
    (next: WorkflowNodeLayout | null) => {
      setDraftLayout(null);
      data.onLayoutChange?.(id, next);
      window.requestAnimationFrame(() => updateNodeInternals(id));
    },
    [data, id, updateNodeInternals],
  );

  return (
    <CanvasNodeShell
      state={shell}
      selected={selected}
      remoteSelectionColor={data.remoteSelectionColor}
      variant="incompatible"
      ariaLabel={`${data.spec.title} ${compatibility.status} node`}
      resizeHandle={
        allowCornerResize ? (
          <LayoutResizeHandle
            layout={layout}
            axes={["width"]}
            ariaLabel={`Resize ${data.spec.title}`}
            onDraft={setDraftLayout}
            onCommit={commitLayout}
          />
        ) : undefined
      }
      appendix={
        <NodeExecutionAppendix
          nodeId={id}
          nodeTitle={data.spec.title}
          expanded={selected}
          width={paintWidth}
          execution={data.execution}
          progress={data.progress}
          run={data.run}
          historyContext={data.historyContext}
          onOpenHistory={data.onOpenExecutionHistory}
        />
      }
    >
      <header {...stylex.props(s.header)}>
        <span {...stylex.props(s.titleRow)}>
          <TriangleAlert
            size={14}
            aria-hidden="true"
            {...stylex.props(s.compatibilityIcon)}
          />
          <button
            type="button"
            aria-label={`Remove ${data.spec.title}`}
            title={`Remove ${data.spec.title}`}
            {...nodeInteractionProps(
              stylex.props(nodeChrome.headerButton, s.removeButton),
            )}
            onClick={() => data.onRemoveNode?.(id)}
          >
            <X size={13} />
          </button>
          <span {...stylex.props(nodeChrome.title)} title={data.spec.title}>
            {data.spec.title}
          </span>
          <span {...stylex.props(s.compatibilityBadge)}>
            {compatibility.status}
          </span>
        </span>
        <span {...stylex.props(s.operatorRow)}>
          <span {...stylex.props(s.operatorCopy)}>
            {data.spec.operator_id}@{data.spec.operator_version}
          </span>
        </span>
      </header>
      <CompatibilityPortRail
        inputs={compatibility.inputs}
        outputs={compatibility.outputs}
      />
      <div {...stylex.props(s.compatibilityBody)}>
        {compatibility.issues.map((issue) => (
          <p key={issue} role="status" {...stylex.props(s.compatibilityIssue)}>
            {issue}
          </p>
        ))}
        <details
          {...nodeInteractionProps(stylex.props(s.compatibilityConfig))}
        >
          <summary {...stylex.props(s.compatibilityConfigSummary)}>
            Saved configuration
          </summary>
          <pre {...stylex.props(s.compatibilityConfigValue)}>
            {JSON.stringify(data.config, null, 2)}
          </pre>
        </details>
      </div>
    </CanvasNodeShell>
  );
}

function SupportedWorkflowNodeCard({
  id,
  data,
  selected,
  dragging,
}: NodeProps<WorkflowNode>) {
  const fields = schemaFields(data.spec.config_schema);
  const secretInputs = nodeSecretInputs(data.spec);
  const isFileUpload = isFileUploadOperator(data.spec.operator_id);
  const isSchemaBuilder =
    data.spec.operator_id === SCHEMA_BUILDER_OPERATOR_ID;
  const isArtifactQuery =
    data.spec.operator_id === ARTIFACT_QUERY_OPERATOR_ID;
  const isVectorLayer =
    data.spec.operator_id === GIS_VECTOR_LAYER_OPERATOR_ID;
  const visibleInputPorts = data.spec.inputs.filter((port) => {
    if (isSchemaBuilder && port.name === SCHEMA_BUILDER_INPUT_PORT) {
      return false;
    }
    if (isArtifactQuery && port.name === ARTIFACT_QUERY_RELATIONS_PORT) {
      return false;
    }
    return true;
  });
  const hasConfig = fields.length > 0 || secretInputs.length > 0;
  const hasExecutionError = Boolean(data.execution.error);
  const hasProgress = Boolean(data.progress?.entries.length);
  const hasMaterialization = (data.run?.outputs ?? []).some(
    (output) => output.artifacts.length > 0,
  );
  const hasSavedHistory = Boolean(data.historyContext?.graphId);
  const inputPlugRevision = data.inputPlugs
    .map((plug) => `${plug.portName}:${plug.id}`)
    .join("|");
  const schemaBuilderRevision = isSchemaBuilder
    ? JSON.stringify(data.config.fields ?? [])
    : "";
  const artifactTypeBindingRevision = Object.entries(data.artifactTypeBindings)
    .map(
      ([variable, artifactType]) =>
        `${variable}:${artifactType.id}@${artifactType.schema_version}`,
    )
    .sort()
    .join("|");
  const incidentConnections = useNodeConnections({ id });
  const updateNodeInternals = useUpdateNodeInternals();
  const grid = useOptionalCanvasGridSettings();
  const allowCornerResize =
    grid?.settings.allowWorkflowCornerResize ?? false;
  const measuredArtifactTypeBindings = data.artifactTypeBindings;
  const onHandlesMeasured = data.onHandlesMeasured;
  const [draftLayout, setDraftLayout] = React.useState<WorkflowNodeLayout | null>(
    null,
  );
  const layout = draftLayout ?? data.layout;
  const nodeWidth = resolvedNodeWidth(layout);
  const shell = useCanvasNodeShell({
    id,
    selected,
    dragging,
    naturalWidth: nodeWidth,
    updateNodeInternals,
  });
  const { gridWidth, paintWidth, fillMinHeight } = shell;
  const bodyHeight = resolvedBodyHeight(layout);
  const layoutRevision = [
    layout?.width ?? "",
    layout?.bodyHeight ?? "",
  ].join(":");
  const commitLayout = (next: WorkflowNodeLayout | null) => {
    setDraftLayout(null);
    data.onLayoutChange?.(id, next);
    window.requestAnimationFrame(() => updateNodeInternals(id));
  };

  React.useLayoutEffect(() => {
    // React Flow measures handles in the animation frame queued here. Queue the
    // readiness callback afterward so a concrete generic handle is registered
    // before Workbench publishes an edge that targets it.
    updateNodeInternals(id);
    const frame = window.requestAnimationFrame(() =>
      onHandlesMeasured?.(id, measuredArtifactTypeBindings),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [
    measuredArtifactTypeBindings,
    data.mappedInputPort,
    artifactTypeBindingRevision,
    inputPlugRevision,
    schemaBuilderRevision,
    layoutRevision,
    data.spec.inputs.length,
    data.spec.outputs.length,
    fields.length,
    fillMinHeight,
    gridWidth,
    secretInputs.length,
    hasExecutionError,
    hasMaterialization,
    hasProgress,
    hasSavedHistory,
    onHandlesMeasured,
    id,
    updateNodeInternals,
  ]);

  return (
    <CanvasNodeShell
      state={shell}
      selected={selected}
      remoteSelectionColor={data.remoteSelectionColor}
      resizeHandle={
        allowCornerResize ? (
          <LayoutResizeHandle
            layout={layout}
            axes={["width", "bodyHeight"]}
            ariaLabel={`Resize ${data.spec.title}`}
            onDraft={setDraftLayout}
            onCommit={commitLayout}
          />
        ) : undefined
      }
      appendix={
        <NodeExecutionAppendix
          nodeId={id}
          nodeTitle={data.spec.title}
          expanded={selected}
          width={paintWidth}
          execution={data.execution}
          progress={data.progress}
          run={data.run}
          historyContext={data.historyContext}
          onOpenHistory={data.onOpenExecutionHistory}
        />
      }
    >
      <NodeHeader id={id} data={data} selected={selected ?? false} />
      <GenericArtifactTypeState
        id={id}
        data={data}
        resettable={incidentConnections.length === 0}
      />
      <PortRail
        id={id}
        data={data}
        inputPorts={visibleInputPorts.filter(
          (port) => !portHasInstancePlugs(port),
        )}
        outputPorts={data.spec.outputs}
      />
      {visibleInputPorts.some((port) => portHasInstancePlugs(port)) ? (
        <div {...stylex.props(s.plugPorts)}>
          {visibleInputPorts
            .filter((port) => portHasInstancePlugs(port))
            .map((port) => (
              <InstancePlugPort
                key={`in-${port.name}`}
                id={id}
                data={data}
                port={port}
              />
            ))}
        </div>
      ) : null}
      {isSchemaBuilder ? (
        <SchemaBuilderBody id={id} data={data} />
      ) : isArtifactQuery ? (
        <ArtifactQueryTablesBody id={id} data={data} />
      ) : isFileUpload ? (
        <>
          {hasConfig ? (
            <GenericBody
              id={id}
              data={data}
              bodyHeight={bodyHeight}
              layout={layout}
              onLayoutDraft={setDraftLayout}
              onLayoutCommit={commitLayout}
            />
          ) : null}
          <FileUploadBody id={id} data={data} />
        </>
      ) : isVectorLayer ? (
        <>
          <GenericBody
            id={id}
            data={data}
            bodyHeight={bodyHeight}
            layout={layout}
            onLayoutDraft={setDraftLayout}
            onLayoutCommit={commitLayout}
          />
          <VectorLayerStyleBody id={id} data={data} />
        </>
      ) : hasConfig ? (
        <GenericBody
          id={id}
          data={data}
          bodyHeight={bodyHeight}
          layout={layout}
          onLayoutDraft={setDraftLayout}
          onLayoutCommit={commitLayout}
        />
      ) : (
        <div {...stylex.props(s.spacer)} aria-hidden />
      )}
      {!isFileUpload &&
      !isSchemaBuilder &&
      !isArtifactQuery &&
      !hasConfig &&
      !hasExecutionError &&
      !data.spec.inputs.length &&
      !data.spec.outputs.length ? (
        <p {...stylex.props(s.emptyBody)}>
          {data.spec.description || "No configuration for this operator."}
        </p>
      ) : null}
    </CanvasNodeShell>
  );
}

function WorkflowNodeCard(props: NodeProps<WorkflowNode>) {
  if (props.data.compatibility.status === "supported") {
    return <SupportedWorkflowNodeCard {...props} />;
  }
  return (
    <IncompatibleWorkflowNodeCard
      id={props.id}
      data={props.data}
      selected={props.selected}
      dragging={props.dragging}
      compatibility={props.data.compatibility}
    />
  );
}

export default WorkflowNodeCard;
