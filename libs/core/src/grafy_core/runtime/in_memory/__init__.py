"""Dictionary-backed adapters for the single-process workbench and the tests.

The contracts these classes keep are the ones the SQL adapters keep, and they are
what makes them usable as stand-ins:

* **Task isolation.** One unit of work is entered by one task at a time; a nested
  entry fails rather than sharing a transaction.
* **Clone in, copy out.** A transaction works on a deep clone of the store, and
  entities are cloned again on the way in and out, so a mutated domain object never
  writes itself into committed state behind the caller's back.
* **Rollback.** A commit publishes the working clone; a rollback, or any exception
  out of ``async with``, throws it away.
* **Workspace scoping.** Every read carries ``workspace_id``, so a row of another
  Workspace is indistinguishable from one that was never there.

Where the SQL adapter turns a primary-key violation into ``ConcurrentWriteError``
(an appended checkpoint revision, a command receipt, a checkpoint mapping) this one
raises the same error on the same key. What it cannot imitate is a real row lock:
``lock_head`` is an ordinary read, and the unit of work's transaction lock is what
serialises writers here.
"""

from grafy_core.runtime.in_memory.agents import (
    InMemoryAgentConversationRepository as InMemoryAgentConversationRepository,
    InMemoryAgentTurnRepository as InMemoryAgentTurnRepository,
)
from grafy_core.runtime.in_memory.artifacts import (
    InMemoryArtifactRepository as InMemoryArtifactRepository,
    InMemoryLibraryFolderRepository as InMemoryLibraryFolderRepository,
)
from grafy_core.runtime.in_memory.collaboration import (
    InMemoryCollaborationRepository as InMemoryCollaborationRepository,
)
from grafy_core.runtime.in_memory.projects import (
    InMemoryProjectRepository as InMemoryProjectRepository,
)
from grafy_core.runtime.in_memory.runs import (
    InMemoryResultStoreRepository as InMemoryResultStoreRepository,
    InMemoryRunRepository as InMemoryRunRepository,
)
from grafy_core.runtime.in_memory.store import InMemoryDataStore as InMemoryDataStore
from grafy_core.runtime.in_memory.uploads import (
    InMemoryUploadRepository as InMemoryUploadRepository,
)
from grafy_core.runtime.in_memory.uow import InMemoryUnitOfWork as InMemoryUnitOfWork

__all__ = [
    "InMemoryAgentConversationRepository",
    "InMemoryAgentTurnRepository",
    "InMemoryArtifactRepository",
    "InMemoryCollaborationRepository",
    "InMemoryDataStore",
    "InMemoryLibraryFolderRepository",
    "InMemoryProjectRepository",
    "InMemoryResultStoreRepository",
    "InMemoryRunRepository",
    "InMemoryUnitOfWork",
    "InMemoryUploadRepository",
]
