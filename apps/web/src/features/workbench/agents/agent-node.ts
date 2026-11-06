import type { Node } from "@xyflow/react";
import type { NodeRegistry, SavedGraphAgent } from "@/lib/api/contract";
import type { LinkableDocument } from "./agent-links";
import type { AgentScope } from "@/lib/api/agents";

/**
 * An Agent as a React Flow node. It lives apart from `AgentCard` so the canvas
 * model can name it without importing the card and the chrome the card draws
 * with, which import the canvas model back.
 */
export type AgentNode = Node<
  {
    remoteSelectionColor?: string | null;
    agent: SavedGraphAgent;
    scope: AgentScope | null;
    canEdit: boolean;
    canSend: boolean;
    /**
     * What the Agent's links are chosen from: this Graph's nodes and cards and the
     * catalog that says what each can do. Absent where a card is drawn without a Graph.
     */
    links?: {
      document: LinkableDocument & {
        presentation?: {
          viewers: readonly {
            id: string;
            artifact_ref?: {
              artifact_type: string;
              schema_version: number;
            } | null;
          }[];
        };
      };
      registry: NodeRegistry;
    };
    configure: (agent: SavedGraphAgent) => void;
    remove: () => void;
  },
  "grafyAgent"
>;
