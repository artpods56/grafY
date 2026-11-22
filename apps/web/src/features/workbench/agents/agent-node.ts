import type { CanvasNodeBase } from "../canvas/types";
import type { NodeRegistry, SavedGraphAgent } from "@/lib/api/contract";
import type { LinkableDocument } from "./agent-links";
import type { AgentScope } from "@/lib/api/agents";

/** An Agent's canvas node shape, independent of the conversation UI. */
export type AgentNode = CanvasNodeBase<
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
