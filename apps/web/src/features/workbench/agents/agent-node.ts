import type { Node } from "@xyflow/react";
import type { SavedGraphAgent } from "@/lib/api/contract";
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
    configure: (agent: SavedGraphAgent) => void;
    remove: () => void;
  },
  "grafyAgent"
>;
