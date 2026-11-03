import type { components, paths } from "./generated/grafy";

type Schemas = components["schemas"];

export type Session = Schemas["SessionResponse"];
export type User = Schemas["UserResponse"];
export type Workspace = Schemas["WorkspaceResponse"];
export type WorkspaceCreateRequest = Schemas["WorkspaceCreateRequest"];
export type WorkspaceMember = Schemas["WorkspaceMemberResponse"];
export type WorkspaceMemberRoleRequest = Schemas["WorkspaceMemberRoleRequest"];
export type WorkspaceInvitationCandidateRequest =
  Schemas["WorkspaceInvitationCandidateRequest"];
export type WorkspaceInvitationCandidate =
  Schemas["WorkspaceInvitationCandidateResponse"];
export type WorkspaceInvitationCreateRequest =
  Schemas["WorkspaceInvitationCreateRequest"];
export type WorkspaceInvitation = Schemas["WorkspaceInvitationOwnerResponse"];
export type WorkspaceInvitationForRecipient =
  Schemas["WorkspaceInvitationRecipientResponse"];
export type WorkspaceCapability = Schemas["WorkspaceCapability"];
export type WorkspaceRole = Schemas["WorkspaceRole"];
export type PersonalAccessToken = Schemas["PersonalAccessTokenResponse"];
export type PersonalAccessTokenCreated =
  Schemas["PersonalAccessTokenCreatedResponse"];
export type PersonalAccessTokenCreateRequest =
  Schemas["PersonalAccessTokenCreateRequest"];

export type ArtifactTypeKey = Schemas["ArtifactTypeKeyResponse"];
export type ArtifactTypeSpec = Schemas["ArtifactTypeSpecResponse"];
export type ArtifactConversionSpec = Schemas["ArtifactConversionSpecResponse"];
export type FieldProjection = Schemas["FieldProjectionResponse"];
export type Port = Schemas["PortResponse"];
export type NodeSpec = Schemas["NodeSpecResponse"];
export type PluginSpec = Schemas["PluginSpecResponse"];
export type ImageUploadItem = Schemas["ImageUploadItemResponse"];

/** One plug on a node instance: a caller-supplied input port. */
export type InputPlug = Schemas["GraphInputPlug"];
/** A node's configuration is an open JSON object keyed by config variable. */
export type NodeConfig = NonNullable<Schemas["GraphNode"]["config"]>;

export type ArtifactRef = Schemas["ArtifactRef"];
export type ArtifactRefSequence = Schemas["ArtifactRefSequence"];
export type ArtifactOutputValue = Schemas["ArtifactOutputValue"];
export type ArtifactSummary = Schemas["ArtifactSummaryResponse"];
export type ArtifactExportFormat = Schemas["ArtifactExportFormatResponse"];
export type TablePage = Schemas["TablePageResponse"];
export type TableCell = Schemas["TableCellResponse"];
export type TableSchema = Schemas["TableSchemaResponse"];
export type GeoBounds = Schemas["GeoBounds"];
export type GeoRenderVectorSource = Schemas["GeoVectorRenderSourceResponse"];
export type GeoRenderRasterSource = Schemas["GeoRasterRenderSourceResponse"];
export type GeoRenderFillStyle = Schemas["GeoFillStyle"];
export type GeoRenderLineStyle = Schemas["GeoLineStyle"];
export type GeoRenderPointStyle = Schemas["GeoPointStyle"];
export type GeoRenderPointCategory = Schemas["GeoPointCategory"];
export type GeoRenderLabelStyle = Schemas["GeoLabelStyle"];
export type GeoRenderVectorStyle = Schemas["GeoVectorStyle"];
export type GeoRenderCategorizedPointStyle =
  Schemas["GeoCategorizedPointStyle"];
export type GeoRenderRasterStyle = Schemas["GeoRasterStyle"];
export type GeoRenderLayer = Schemas["GeoRenderLayerResponse"];
export type GeoRenderDescriptor = Schemas["GeoRenderResponse"];
export type GeoFeatureQuery = Schemas["GeoFeatureQueryResponse"];

// --- Graph documents -------------------------------------------------------
// A Graph is the unit of authoring. It always lives inside a Project, so a
// document never travels alone: the Project document carries every Graph.

export type SavedGraphDocument = Schemas["GraphDocument"];
export type SavedGraphNode = Schemas["GraphNode"];
export type SavedGraphEdge = Schemas["GraphEdge"];
export type SavedGraphOrigin = Schemas["GraphOrigin"];
export type GraphPresentationDocument = Schemas["GraphPresentationDocument"];
export type GraphNodeKind = SavedGraphNode["kind"];

/** A Graph inside a Project document: its own id, name and document. */
export type GraphDefinition = Schemas["GraphDefinition"];

/**
 * The authoring view of one Graph inside a Project. The revision is the
 * Project's collaboration sequence, which is what a save is compared against.
 */
export interface SavedGraph {
  readonly id: string;
  readonly name: string;
  readonly revision: number;
  readonly created_at: string;
  readonly updated_at: string;
  readonly document: SavedGraphDocument;
}

// --- Projects --------------------------------------------------------------

export type Project = Schemas["ProjectResponse"];
export type ProjectSummary = Schemas["ProjectSummaryResponse"];
export type CreateProjectRequest = Schemas["CreateProjectRequest"];
export type ProjectDocument = Schemas["ProjectDocument"];
export type ProjectHead = Schemas["ProjectHeadResponse"];
/** The room's name for the head the author's document is projected from. */
export type CollaborativeHead = ProjectHead;

export type ProjectCommandReceipt = Schemas["ProjectCommandReceiptResponse"];
export type SubmitProjectCommandRequest =
  Schemas["SubmitProjectCommandRequest"];
export type SubmitProjectCommandResponse =
  Schemas["SubmitProjectCommandResponse"];
/** One entry of a Project command batch: a project-level command or one inside a Graph. */
export type ProjectCommand = SubmitProjectCommandRequest["commands"][number];
export type InGraphCommand = Schemas["InGraphCommand"];
/** A command addressed to one Graph, without its Project wrapper. */
export type GraphCommandInput = InGraphCommand["command"];

export type CheckpointProjectRequest = Schemas["CheckpointProjectRequest"];
export type CheckpointProjectResponse = Schemas["CheckpointProjectResponse"];
export type ProjectCheckpointList = Schemas["ProjectCheckpointListResponse"];
export type ProjectCheckpoint = Schemas["ProjectCheckpointResponse"];
export type ProjectCheckpointSummary =
  Schemas["ProjectCheckpointSummaryResponse"];

export type CopyExactHeadRequest = Schemas["CopyExactHeadRequest"];
export type CopyExactHeadResponse = Schemas["ProjectResponse"];

export type ProjectBrowserGraph = Schemas["ProjectBrowserItemResponse"];
export type ProjectBrowserList = Schemas["ProjectBrowserListResponse"];
/** @deprecated use ProjectBrowserGraph. */
export type GraphBrowserGraph = ProjectBrowserGraph;
/** @deprecated use ProjectBrowserList. */
export type GraphBrowserList = ProjectBrowserList;
export type SavedGraphSummary = ProjectSummary;
/** The `/me/projects` feed: every Project this person can reach, by workspace. */
export type ProjectList = Schemas["ProjectListResponse"];

export type ProjectFolder = Schemas["ProjectFolderResponse"];
export type ProjectFolderList = Schemas["ProjectFolderListResponse"];
export type ProjectFolderWriteRequest = Schemas["ProjectFolderWriteRequest"];
export type AssignProjectFolderRequest = Schemas["AssignProjectFolderRequest"];
export type ProjectOrganization = Schemas["ProjectOrganizationResponse"];
export type UserProjectState = Schemas["UserProjectStateResponse"];

// --- Runs and instances ----------------------------------------------------
// A Run is a demand for freshness, not an execution history entry. Results
// belong to the node instance that produced them and are addressed by
// (project, graph, call path, node).

export type RunStatus = Schemas["RunStatus"];
export type Run = Schemas["RunResponse"];
export type RunList = Schemas["RunListResponse"];
export type RunTargetInput = Schemas["RunTargetRequest"];
export type StartRunRequest = Schemas["StartRunRequest"];

/**
 * One step of an edge's conversion path, as the Graph stores it.
 *
 * The client used to send a run request that carried edges, origins and pinned
 * values; the head is the request now, so these are stored-Graph shapes rather
 * than input shapes.
 */
export type GraphConversion = Schemas["GraphConversion"];

/** One input plug of a stored node: which port of the operator it stands for. */
export type GraphInputPlug = Schemas["GraphInputPlug"];

/** A projected read of an upstream field, as the Graph stores it. */
export type GraphProjectionShape = Schemas["GraphProjection"];

/** How an edge feeds its target: one value, or one per item of a map. */
export type EdgeCollectionMode = SavedGraphEdge["collection_mode"];

/**
 * One Graph as a person authors it: its name beside its document.
 *
 * A Project holds the Graphs, so this is not a save request of its own — it is
 * the unit a `replace_document` command carries and the unit the canvas edits.
 */
export interface GraphDraft {
  readonly name: string;
  readonly document: SavedGraphDocument;
}

/** @deprecated use EdgeCollectionMode. */
export type RunEdgeCollectionMode = EdgeCollectionMode;
/** @deprecated use GraphProjectionShape. */
export type RunEdgeProjectionInput = GraphProjectionShape;
/** @deprecated use GraphInputPlug. */
export type InputPlugInput = GraphInputPlug;
/** @deprecated use SavedGraphNode. */
export type RunNodeInput = SavedGraphNode;
/** @deprecated use GraphConversion. */
export type ArtifactConversionInput = GraphConversion;
/** @deprecated use the conversion path of a stored edge. */
export type ArtifactConversionPathInput = readonly GraphConversion[];
/** @deprecated a saved Graph is authored, not posted whole. */
export type CreateSavedGraphRequest = GraphDraft;
// GraphNodeSecrets is gone rather than aliased. A name that puts Graph where the
// API puts Project is not merely untidy: it is what made a hook importing
// getGraphNodeSecrets look plausible for a whole port cycle while the route had
// moved under the Project.
/** @deprecated a browser entry is a Project; the Graph it names is where it opens. */
export type ProjectBrowserItem = ProjectBrowserGraph;

export type InstanceKey = Schemas["InstanceKeyResponse"];
export type InstanceStateName = Schemas["InstanceState"];
export type InstanceState = Schemas["InstanceStateResponse"];
export type InstanceStateList = Schemas["InstanceStateListResponse"];
export type InstanceResult = Schemas["InstanceResultResponse"];

/**
 * One artifact of a stored result, as the canvas sees it. A stored result
 * carries artifact *references*; the bytes and their export formats live behind
 * the artifact routes, so a reference is enough to render a card and the card
 * reaches `/artifacts/{id}/content` for the bytes themselves.
 */
export interface RunPortArtifact {
  readonly artifact_id: string;
  readonly artifact_type: string;
  readonly schema_version: number;
  readonly content_hash: string | null;
}

/**
 * One output port of a stored result. Derived from an InstanceResult's
 * `outputs` map; the canvas reads runs through this shape.
 */
export interface RunPortOutput {
  readonly port: string;
  readonly kind: "single" | "sequence";
  readonly artifacts: readonly RunPortArtifact[];
  readonly value: ArtifactOutputValue;
}

/** One node instance's state plus the outputs of the result it last produced. */
export interface RunNodeResult {
  readonly node_id: string;
  readonly status: "succeeded" | "failed" | "skipped";
  readonly error: string | null;
  readonly outputs: readonly RunPortOutput[];
  readonly result_fingerprint: string | null;
  readonly created_at: string | null;
}

export type NodeRunStatus = RunNodeResult["status"];

/** The state of a node instance the canvas renders on a card. */
export type RunExecutionNodeStatus = InstanceStateName;

/** The Project's active Runs, as the room reports them. */
export interface ActiveRunSummary {
  readonly run_id: string;
  readonly graph_id: string;
  readonly targets: readonly RunTargetInput[];
  readonly starter: {
    readonly actor_id: string;
    readonly display_name: string;
    readonly color: string;
  } | null;
  readonly started_at: string;
  readonly cancellable: boolean;
}

export type ActiveRunLifecycleStatus = RunStatus;
export type TerminalRunStatus =
  "succeeded" | "failed" | "cancelled" | "interrupted";

// --- Secrets ---------------------------------------------------------------

export type NodeSecretInput = Schemas["NodeSecretInputResponse"];
export type NodeSecretStatus = Schemas["NodeSecretStatusResponse"];
export type NodeSecretResolution = Schemas["NodeSecretResolutionResponse"];
export type ProjectNodeSecrets = Schemas["ProjectNodeSecretsResponse"];
export type ApplyNodeSecretRequest = Schemas["ConfigureNodeSecretRequest"];
export type AppliedNodeSecret = NodeSecretStatus;

// --- Catalog ---------------------------------------------------------------

export type NodeRegistry =
  paths["/v1/workspaces/{workspace_id}/nodes"]["get"]["responses"][200]["content"]["application/json"];

export type PortDirection = Port["direction"];
export type PortShape = Port["shape"];
export type JsonSchema = NodeSpec["config_schema"];

// --- Library ---------------------------------------------------------------

export type LibraryProvenance = Schemas["LibraryProvenanceResponse"];
export type LibraryItem = Schemas["LibraryItemResponse"];
export type LibraryList = Schemas["LibraryListResponse"];
export type LibraryFolder = Schemas["LibraryFolderResponse"];
export type LibraryFolderList = Schemas["LibraryFolderListResponse"];
export type SaveInstanceArtifactRequest =
  Schemas["SaveInstanceArtifactRequest"];
export type SaveUploadedArtifactRequest =
  Schemas["SaveUploadedArtifactRequest"];

// --- Uploads ---------------------------------------------------------------

export type UploadResponse = Schemas["ImageUploadItemResponse"];
export type UploadTarget = Schemas["UploadTargetResponse"];
