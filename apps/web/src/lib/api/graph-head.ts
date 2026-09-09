import type { CollaborativeHead, LegacyCollaborativeHead } from "./contract";

/** Adapt the existing v1 head transport to the document used by client state. */
export function collaborativeHeadFromLegacy(
  head: LegacyCollaborativeHead,
): CollaborativeHead {
  const { nodes, edges, presentation, ...metadata } = head;
  return {
    ...metadata,
    document: {
      schema_version: 6,
      nodes: nodes.map(({ plugin_release, ...node }) => ({
        ...node,
        artifact_type_bindings: node.artifact_type_bindings ?? [],
        input_plugs: node.input_plugs ?? [],
        plugin_release_pin: plugin_release,
      })),
      edges: edges.map((edge) => ({
        ...edge,
        conversion_path: edge.conversion_path ?? [],
      })),
      presentation: {
        viewers: presentation?.viewers ?? [],
        links: presentation?.links ?? [],
        bindings: presentation?.bindings ?? [],
        annotations: presentation?.annotations ?? [],
      },
    },
  };
}
