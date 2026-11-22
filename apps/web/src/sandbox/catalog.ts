export const SPIKES = [
  {
    id: "cell-canvas",
    title: "Canvas lab",
    question: "How does the workbench card render with these canvas settings?",
  },
  {
    id: "port-types",
    title: "Port types",
    question: "Where should a generic port show its resolved type?",
  },
] as const;

export type SpikeId = (typeof SPIKES)[number]["id"];

export function getSpike(id: string): (typeof SPIKES)[number] | undefined {
  return SPIKES.find((spike) => spike.id === id);
}
