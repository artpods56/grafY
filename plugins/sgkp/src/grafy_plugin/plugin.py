from grafy_core.artifacts import Artifact
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_core.runtime.resolvers import InlineModelResolver

from grafy_plugin import nodes
from grafy_plugin.artifacts import (
    SGKP_DATASET,
    SGKP_REFERENCE_CANDIDATE,
    SGKP_REFERENCE_DECISION,
)
from grafy_plugin.declaration import PLUGIN
from grafy_plugin.models import ReferenceCandidate, ReferenceDecision, SgkpDataset


_NODE_MODULES = (nodes,)


PLUGIN.register(
    Artifact(
        spec=SGKP_DATASET,
        resolver=lambda context: InlineModelResolver(
            source=SGKP_DATASET.key,
            target=SgkpDataset,
            uow=context.uow,
        ),
        writer=lambda context: InlineModelOutputWriter(
            artifact_type=SGKP_DATASET.key,
            model=SgkpDataset,
            uow=context.uow,
        ),
    )
)
PLUGIN.register(
    Artifact(
        spec=SGKP_REFERENCE_CANDIDATE,
        resolver=lambda context: InlineModelResolver(
            source=SGKP_REFERENCE_CANDIDATE.key,
            target=ReferenceCandidate,
            uow=context.uow,
        ),
        writer=lambda context: InlineModelOutputWriter(
            artifact_type=SGKP_REFERENCE_CANDIDATE.key,
            model=ReferenceCandidate,
            uow=context.uow,
        ),
    )
)
PLUGIN.register(
    Artifact(
        spec=SGKP_REFERENCE_DECISION,
        resolver=lambda context: InlineModelResolver(
            source=SGKP_REFERENCE_DECISION.key,
            target=ReferenceDecision,
            uow=context.uow,
        ),
        writer=lambda context: InlineModelOutputWriter(
            artifact_type=SGKP_REFERENCE_DECISION.key,
            model=ReferenceDecision,
            uow=context.uow,
        ),
    )
)


__all__ = ["PLUGIN"]
