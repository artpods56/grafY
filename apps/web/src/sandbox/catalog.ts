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
    title: "Artifact drawer to input",
    summary:
      "Drag a Produced or Kept artifact onto a real port row, or onto empty canvas.",
  },
] as const;

export type SpikeId = (typeof SPIKES)[number]["id"];

export function getSpike(id: string): (typeof SPIKES)[number] | undefined {
  return SPIKES.find((spike) => spike.id === id);
}
