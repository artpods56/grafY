"""Stage a saved graph and its initial collaborative checkpoint together."""

from uuid import UUID, uuid4

from grafy_core.domain.collaboration import CollaborativeGraphHead, GraphCheckpointMapping
from grafy_core.domain.saved_graphs import SavedGraph
from grafy_core.ports.collaboration import CollaborationRepositoryPort
from grafy_core.ports.saved_graphs import SavedGraphRepositoryPort


async def stage_checkpointed_graph(
    graph: SavedGraph,
    *,
    graphs: SavedGraphRepositoryPort,
    collaboration: CollaborationRepositoryPort,
    room_epoch: UUID | None = None,
    collaboration_sequence: int = 0,
) -> CollaborativeGraphHead:
    """Stage initial state in the caller's transaction without committing it."""

    head = CollaborativeGraphHead(
        workspace_id=graph.workspace_id,
        graph_id=graph.id,
        room_epoch=uuid4() if room_epoch is None else room_epoch,
        collaboration_sequence=collaboration_sequence,
        checkpoint_sequence=collaboration_sequence,
        checkpoint_revision=graph.revision,
        name=graph.name,
        document=graph.document,
    )
    mapping = GraphCheckpointMapping(
        workspace_id=graph.workspace_id,
        graph_id=graph.id,
        room_epoch=head.room_epoch,
        collaboration_sequence=head.collaboration_sequence,
        saved_revision=graph.revision,
    )
    await graphs.add(graph)
    await graphs.add_revision(graph.snapshot())
    await collaboration.add_head(head)
    await collaboration.add_checkpoint_mapping(mapping)
    return head
