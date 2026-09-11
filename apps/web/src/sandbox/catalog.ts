export const SPIKES = [
  {
    id: "port-inspector",
    title: "Port inspector",
    summary:
      "Drill inspector is now shipping. Sandbox keeps the earlier tree variants for comparison.",
  },
  {
    id: "viewer-link",
    title: "Link viewers",
    summary:
      "Table row to map feature without extra ports. Four gestures for the same binding.",
  },
  {
    id: "drawer-interaction",
    title: "Canvas with real input plugs",
    summary:
      "The product canvas with real node cards, kept as a base for building an input interaction.",
  },
] as const;

export type SpikeId = (typeof SPIKES)[number]["id"];

export function getSpike(id: string): (typeof SPIKES)[number] | undefined {
  return SPIKES.find((spike) => spike.id === id);
}
