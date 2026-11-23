/**
 * Place a card only while the room still accepts edits on the graph that
 * started the upload or the sample request.
 */
export function mayPlaceOnInitiatingGraph(input: {
  authoringEnabled: boolean;
  activeGraphId: string | null;
  initiatingGraphId: string | null;
}): boolean {
  return (
    input.authoringEnabled &&
    input.initiatingGraphId !== null &&
    input.activeGraphId === input.initiatingGraphId
  );
}
