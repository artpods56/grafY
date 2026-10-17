from uuid import UUID

from grafy_core.domain.module_library import (
    Module,
    ModulePublicationState,
)


def test_publish_state_machine() -> None:
    module = Module(
        workspace_id=UUID(int=1),
        source_graph_id=UUID(int=2),
        name="Capitalize",
    )
    module.apply_publish(revision=1)
    assert module.publication_state == ModulePublicationState.PUBLISHED
    assert module.current_library_release == 1

    module.apply_publish(revision=2, name="Capitalize v2")
    assert module.publication_state == ModulePublicationState.PUBLISHED
    assert module.current_library_release == 2
    assert module.name == "Capitalize v2"


def test_retired_publication_states_still_load() -> None:
    """Rows written before deprecate and withdraw were cut must not fail to map."""

    for state in (ModulePublicationState.DEPRECATED, ModulePublicationState.WITHDRAWN):
        module = Module(
            workspace_id=UUID(int=1),
            source_graph_id=UUID(int=2),
            name="Legacy",
            publication_state=state,
            current_library_release=1,
        )
        assert module.publication_state is state
