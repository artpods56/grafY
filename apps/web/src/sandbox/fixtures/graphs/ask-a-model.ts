import type { AuthoredGraphDocument } from "@/features/workbench/authoring/graph-document";
import { defaultNodeConfig } from "@/features/workbench/authoring/types";
import {
  ASK_A_MODEL_OPERATOR_ID,
  askAModelRegistry,
} from "../ask-a-model-registry";

const spec = askAModelRegistry.nodes.find(
  (node) => node.operator_id === ASK_A_MODEL_OPERATOR_ID,
);
if (!spec) throw new Error("The recorded registry is missing Ask a model");

export const ASK_A_MODEL_FIXTURE = "ask-a-model@1";
export const ASK_A_MODEL_CARD_ID = "ask-model";

export const askAModelDocument: AuthoredGraphDocument = {
  name: "Ask a model",
  nodes: [
    {
      id: ASK_A_MODEL_CARD_ID,
      kind: "builtin",
      operator_id: spec.operator_id,
      operator_version: spec.operator_version,
      position: { x: 0, y: 0 },
      layout: null,
      config: defaultNodeConfig(spec),
      input_plugs: [],
      artifact_type_bindings: [],
    },
  ],
  edges: [],
  origins: [],
  agents: [],
};
