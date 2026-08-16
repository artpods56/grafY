import type { components, paths } from "./generated/grafy";

type Schemas = components["schemas"];

export type Session = Schemas["SessionResponse"];
export type User = Schemas["UserResponse"];
export type Workspace = Schemas["WorkspaceResponse"];
export type WorkspaceCreateRequest = Schemas["WorkspaceCreateRequest"];
export type WorkspaceMember = Schemas["WorkspaceMemberResponse"];
export type WorkspaceMemberRequest = Schemas["WorkspaceMemberRequest"];
export type WorkspaceMemberRoleRequest =
  Schemas["WorkspaceMemberRoleRequest"];
export type WorkspaceCapability = Schemas["WorkspaceCapability"];
export type WorkspaceRole = Schemas["WorkspaceRole"];

export type ArtifactTypeKey =
  Schemas["ArtifactTypeKeyResponse"];
export type ArtifactTypeSpec =
  Schemas["ArtifactTypeSpecResponse"];
export type ArtifactConversionSpec =
  Schemas["ArtifactConversionSpecResponse"];
export type ArtifactConversionInput =
  Schemas["ArtifactConversionRequest"];
export type FieldProjection =
  Schemas["FieldProjectionResponse"];
export type Port = Schemas["PortResponse"];
export type NodeSpec = Schemas["NodeSpecResponse"];
export type ImageUploadItem =
  Schemas["ImageUploadItemResponse"];
export type InputPlugInput = Schemas["RunInputPlugRequest"];
export type RunNodeInput = Schemas["RunNodeRequest"];
export type NodeConfigInput = NonNullable<
  RunNodeInput["config"]
>;
export type RunEdgeInput = Schemas["RunEdgeRequest"];
export type ArtifactConversionPathInput = NonNullable<
  RunEdgeInput["conversion_path"]
>;
export type RunEdgeCollectionMode = RunEdgeInput["collection_mode"];
export type RunEdgeProjectionInput = NonNullable<
  RunEdgeInput["projection"]
>;
export type PinnedOutputInput = Schemas["PinnedOutputRequest"];
export type ArtifactSummary =
  Schemas["ArtifactSummaryResponse"];
export type ArtifactExportFormat =
  Schemas["ArtifactExportFormatResponse"];
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
export type RunPortOutput =
  Schemas["RunPortOutputResponse"];
export type RunNodeResult =
  Schemas["RunNodeResponse"];
export type RunExecution =
  Schemas["RunExecutionResponse"];
export type RunExecutionNodeStatus =
  | NodeRunStatus
  | "running";

interface RunExecutionEventBase {
  sequence: number;
  execution_id: string;
  occurred_at: string;
}

interface RunExecutionNodeEventBase extends RunExecutionEventBase {
  node_path: string[];
  node_id: string;
  node_run_id: string | null;
  invocation_index: number | null;
  invocation_path: number[];
}

export interface RunExecutionStatusEvent extends RunExecutionEventBase {
  kind: "execution.status";
  status: RunExecution["status"];
  active_node_id: string | null;
}

export interface RunExecutionNodeStatusEvent
  extends RunExecutionNodeEventBase {
  kind: "node.status";
  status: RunExecutionNodeStatus;
}

export interface RunExecutionNodeProgressEvent
  extends RunExecutionNodeEventBase {
  kind: "node.progress";
  message: string;
  current: number | null;
  total: number | null;
}

export type RunExecutionEvent =
  | RunExecutionStatusEvent
  | RunExecutionNodeStatusEvent
  | RunExecutionNodeProgressEvent;
export type GraphExecutionStatus = Schemas["GraphExecutionStatus"];
export type GraphExecutionSummary =
  Schemas["GraphExecutionSummaryResponse"];
export type GraphExecutionNodeResult =
  Schemas["GraphExecutionNodeResultResponse"];
export type GraphExecutionDetail =
  paths["/v1/workspaces/{workspace_id}/graphs/{graph_id}/executions/{execution_id}"]["get"]["responses"][200]["content"]["application/json"];
export type GraphExecutionList =
  paths["/v1/workspaces/{workspace_id}/graphs/{graph_id}/executions"]["get"]["responses"][200]["content"]["application/json"];
export type GraphMaterializations =
  Schemas["GraphMaterializationsResponse"];
export type SavedGraphNode = Schemas["SavedGraphNodeModel"];
export type SavedGraphEdge = Schemas["SavedGraphEdgeModel"];
export type SavedGraphSummary =
  Schemas["SavedGraphSummaryResponse"];
export type GraphBrowserGraph = Schemas["GraphBrowserItemResponse"];
export type GraphBrowserList = Schemas["GraphBrowserListResponse"];
export type GraphFolder = Schemas["GraphFolderResponse"];
export type GraphFolderList = Schemas["GraphFolderListResponse"];
export type NodeSecretInput = Schemas["NodeSecretInputResponse"];
export type NodeSecretStatus = Schemas["NodeSecretStatusResponse"];
export type GraphNodeSecrets = Schemas["GraphNodeSecretsResponse"];
export type ApplyNodeSecretRequest = Schemas["ConfigureNodeSecretRequest"];
export type AppliedNodeSecret = NodeSecretStatus;

export type NodeRegistry =
  paths["/v1/workspaces/{workspace_id}/nodes"]["get"]["responses"][200]["content"]["application/json"];
export type UnavailableGraphModule =
  Schemas["UnavailableGraphModuleResponse"];
export type ModulePublicationState = Schemas["ModulePublicationState"];
export type ModuleLibraryEntry = Schemas["ModuleResponse"];
export type ModuleRelease = Schemas["ModuleReleaseResponse"];
export type ModuleList = Schemas["ModuleListResponse"];
export type PublishModuleReleaseRequest = Schemas["PublishModuleReleaseRequest"];
export type ImportModuleReleaseRequest = Schemas["ImportModuleReleaseRequest"];
export type ImportModuleReleaseResponse = Schemas["ImportModuleReleaseResponse"];
export type TemplateState = Schemas["TemplateState"];
export type GraphTemplate = Schemas["TemplateResponse"];
export type TemplateList = Schemas["TemplateListResponse"];
export type CreateTemplateRequest = Schemas["CreateTemplateRequest"];
export type UpdateTemplateMetadataRequest =
  Schemas["UpdateTemplateMetadataRequest"];
export type InstantiateTemplateRequest =
  Schemas["InstantiateTemplateRequest"];
export type TemplateInstantiationResponse =
  Schemas["TemplateInstantiationResponse"];
export type UploadResponse =
  paths["/v1/workspaces/{workspace_id}/uploads"]["post"]["responses"][200]["content"]["application/json"];
export type RunScopeInput = Schemas["GraphExecutionScope"];
export type RunRequest =
  paths["/v1/workspaces/{workspace_id}/runs"]["post"]["requestBody"]["content"]["application/json"];
export type RunResponse =
  paths["/v1/workspaces/{workspace_id}/runs"]["post"]["responses"][200]["content"]["application/json"];
export type SavedGraphList =
  paths["/v1/workspaces/{workspace_id}/graphs"]["get"]["responses"][200]["content"]["application/json"];
export type CreateSavedGraphRequest =
  paths["/v1/workspaces/{workspace_id}/graphs"]["post"]["requestBody"]["content"]["application/json"];
export type CreateSavedGraphResponse =
  paths["/v1/workspaces/{workspace_id}/graphs"]["post"]["responses"][201]["content"]["application/json"];
export type SavedGraph =
  paths["/v1/workspaces/{workspace_id}/graphs/{graph_id}"]["get"]["responses"][200]["content"]["application/json"];
export type UpdateSavedGraphRequest =
  paths["/v1/workspaces/{workspace_id}/graphs/{graph_id}"]["put"]["requestBody"]["content"]["application/json"];
export type CollaborativeHead =
  paths["/v1/workspaces/{workspace_id}/graphs/{graph_id}/head"]["get"]["responses"][200]["content"]["application/json"];
export type SubmitGraphCommandRequest =
  paths["/v1/workspaces/{workspace_id}/graphs/{graph_id}/commands"]["post"]["requestBody"]["content"]["application/json"];
export type SubmitGraphCommandResponse =
  paths["/v1/workspaces/{workspace_id}/graphs/{graph_id}/commands"]["post"]["responses"][200]["content"]["application/json"];
export type CheckpointGraphRequest =
  paths["/v1/workspaces/{workspace_id}/graphs/{graph_id}/checkpoint"]["post"]["requestBody"]["content"]["application/json"];
export type CheckpointGraphResponse =
  paths["/v1/workspaces/{workspace_id}/graphs/{graph_id}/checkpoint"]["post"]["responses"][200]["content"]["application/json"];
export type CopyExactHeadRequest =
  paths["/v1/workspaces/{workspace_id}/graphs/copies"]["post"]["requestBody"]["content"]["application/json"];
export type CopyExactHeadResponse =
  paths["/v1/workspaces/{workspace_id}/graphs/copies"]["post"]["responses"][201]["content"]["application/json"];

export type PortDirection = Port["direction"];
export type PortShape = Port["shape"];
export type RunStatus = RunResponse["status"];
export type NodeRunStatus = RunNodeResult["status"];
export type JsonSchema = NodeSpec["config_schema"];
