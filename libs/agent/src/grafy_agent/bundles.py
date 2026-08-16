from grafy_agent.errors import AgentRuntimeError
from grafy_agent.models import NodeSourceBundle, SandboxArchive
from grafy_core.source_bundles import (
    MAX_SOURCE_BUNDLE_FILES,
    SourceBundleError,
    digest_source_subset,
    read_source_bundle,
)


MAX_BUNDLE_FILES = MAX_SOURCE_BUNDLE_FILES


def inspect_node_source_bundle(archive: SandboxArchive) -> NodeSourceBundle:
    try:
        index = read_source_bundle(archive.data)
    except SourceBundleError as exc:
        raise AgentRuntimeError(str(exc)) from exc
    return NodeSourceBundle(
        archive=archive,
        source_digest=index.archive_sha256,
        lock_digest=index.file("uv.lock").sha256,
        tests_digest=digest_source_subset(index, prefix="tests/"),
        implementation_digest=digest_source_subset(index, prefix="src/"),
        file_count=len(index.files),
    )


__all__ = ["MAX_BUNDLE_FILES", "inspect_node_source_bundle"]
