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
  {
    id: "ui-kit",
    title: "Component kit",
    question: "What does each kit part look like at every size it declares?",
  },
  {
    id: "studio-theme",
    title: "Studio theme workbench",
    question:
      "How do the app shell and UI kit feel when aligned with the cool, floating studio aesthetic of the canvas?",
  },
  {
    id: "credentials",
    title: "Node credentials dialog",
    question: "How does a node's credentials dialog read in each state?",
  },
] as const;

export type SpikeId = (typeof SPIKES)[number]["id"];

export function getSpike(id: string): (typeof SPIKES)[number] | undefined {
  return SPIKES.find((spike) => spike.id === id);
}
