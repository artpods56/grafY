import json
from uuid import UUID

from pydantic import ValidationError
import pytest

from grafy_core.domain.plugin_releases import (
    PLUGIN_INVOCATION_PROTOCOL,
    PluginArtifactBundleContract,
    PluginArtifactTypeKey,
    plugin_protocol_digest,
)
from grafy_core.runtime.plugin_protocol import (
    MAX_PLUGIN_PROGRESS_BYTES,
    MAX_PLUGIN_PROGRESS_EVENTS,
    PluginFailureCode,
    PluginFailureEnvelope,
    PluginInputArtifactBundle,
    PluginInputArtifactDependency,
    PluginInputArtifactGroup,
    PluginInputBinding,
    PluginInvocationEnvelope,
    PluginInvocationLimits,
    PluginInvocationRelease,
    PluginInvocationResultEnvelope,
    PluginOutputArtifactBundle,
    PluginOutputBinding,
    PluginOutputDeclaration,
    PluginProgressEvent,
    PluginProtocolCompatibilityError,
    PluginSecretBinding,
)


INVOCATION_ID = UUID("00000000-0000-4000-8000-000000000301")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000302")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000000303")
DEPENDENCY_ID = UUID("00000000-0000-4000-8000-000000000304")
TEXT = PluginArtifactTypeKey(id="scalar.text", schema_version=1)
IMAGE = PluginArtifactTypeKey(id="image.raster", schema_version=1)


def _invocation() -> PluginInvocationEnvelope:
    return PluginInvocationEnvelope(
        invocation_id=INVOCATION_ID,
        execution_scope_id=INVOCATION_ID,
        workspace_id=WORKSPACE_ID,
        release=PluginInvocationRelease(
            slug="notes",
            revision=4,
            source_digest="a" * 64,
            contract_digest="b" * 64,
            protocol_digest=plugin_protocol_digest(),
            descriptor_digest="d" * 64,
        ),
        operator_id="notes.summary.render",
        operator_version=1,
        config={},
        inputs=(
            PluginInputBinding(
                port="summary",
                artifact_type=TEXT,
                groups=(
                    PluginInputArtifactGroup(
                        shape="one",
                        artifacts=(
                            PluginInputArtifactBundle(
                                artifact_id=ARTIFACT_ID,
                                relative_path="inputs/p0000/g0000/a000000.json",
                                byte_count=2,
                                content_sha256="c" * 64,
                            ),
                        ),
                    ),
                ),
            ),
        ),
        input_artifact_dependencies=(
            PluginInputArtifactDependency(
                artifact_type=IMAGE,
                bundle=PluginArtifactBundleContract(
                    format="binary-file",
                    version=1,
                ),
                artifact=PluginInputArtifactBundle(
                    artifact_id=DEPENDENCY_ID,
                    relative_path="inputs/references/r000000.bin",
                    byte_count=4,
                    content_sha256="e" * 64,
                    content_type="image/png",
                ),
            ),
        ),
        outputs=(
            PluginOutputDeclaration(
                port="text",
                artifact_type=TEXT,
                shape="one",
            ),
        ),
        limits=PluginInvocationLimits(),
    )


def test_protocol_models_round_trip_deterministically_without_provider_details() -> (
    None
):
    invocation = _invocation()
    first = invocation.canonical_json_bytes()
    restored = PluginInvocationEnvelope.from_json_bytes(first)

    assert PLUGIN_INVOCATION_PROTOCOL == "grafy-plugin-invocation@7"
    assert restored == invocation
    assert restored.canonical_json_bytes() == first
    assert PLUGIN_INVOCATION_PROTOCOL.encode() in first
    for forbidden in (b"docker", b"mount", b"sqlalchemy", b"object_key"):
        assert forbidden not in first.lower()


@pytest.mark.parametrize(
    "relative_path",
    [
        "../payload.json",
        "/inputs/payload.json",
        "inputs/../payload.json",
        "inputs//payload.json",
        "inputs\\payload.json",
    ],
)
def test_protocol_rejects_unsafe_bundle_paths(relative_path: str) -> None:
    with pytest.raises(ValidationError, match="bundle path|bundle paths"):
        PluginInputArtifactBundle(
            artifact_id=ARTIFACT_ID,
            relative_path=relative_path,
            byte_count=2,
            content_sha256="c" * 64,
        )


def test_protocol_rejects_duplicate_ports_paths_and_unknown_fields() -> None:
    invocation = _invocation()
    binding = invocation.inputs[0]
    with pytest.raises(ValidationError, match="port bindings must be unique"):
        PluginInvocationEnvelope.model_validate(
            invocation.model_copy(update={"inputs": (binding, binding)}).model_dump()
        )

    dependency = invocation.input_artifact_dependencies[0]
    with pytest.raises(ValidationError, match="dependencies must be unique"):
        PluginInvocationEnvelope.model_validate(
            invocation.model_copy(
                update={
                    "input_artifact_dependencies": (dependency, dependency),
                }
            ).model_dump()
        )

    output = PluginOutputArtifactBundle(
        relative_path="outputs/o0000/a000000.json",
        byte_count=2,
        content_sha256="d" * 64,
    )
    output_binding = PluginOutputBinding(
        port="first",
        artifact_type=TEXT,
        shape="one",
        artifacts=(output,),
    )
    with pytest.raises(ValidationError, match="port bindings must be unique"):
        PluginInvocationResultEnvelope(
            invocation_id=INVOCATION_ID,
            status="succeeded",
            outputs=(output_binding, output_binding),
        )

    with pytest.raises(ValidationError, match="bundle paths must be unique"):
        PluginInvocationResultEnvelope(
            invocation_id=INVOCATION_ID,
            status="succeeded",
            outputs=(
                PluginOutputBinding(
                    port="first",
                    artifact_type=TEXT,
                    shape="one",
                    artifacts=(output,),
                ),
                PluginOutputBinding(
                    port="second",
                    artifact_type=TEXT,
                    shape="one",
                    artifacts=(output,),
                ),
            ),
        )

    payload = invocation.model_dump(mode="json")
    payload["docker_image"] = "forbidden"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PluginInvocationEnvelope.model_validate(payload)


def test_secret_metadata_contains_only_dependency_identity_and_safe_path() -> None:
    binding = PluginSecretBinding(
        name="api_key",
        config_dependencies=("base_url",),
        dependency_digest="e" * 64,
        relative_path="secrets/s0000-api_key",
    )
    payload = binding.model_dump(mode="json")

    assert payload == {
        "name": "api_key",
        "config_dependencies": ["base_url"],
        "dependency_digest": "e" * 64,
        "relative_path": "secrets/s0000-api_key",
    }
    with pytest.raises(ValidationError, match="beneath secrets"):
        PluginSecretBinding(
            name="api_key",
            dependency_digest="e" * 64,
            relative_path="inputs/api_key",
        )


def test_protocol_reports_explicit_version_incompatibility() -> None:
    payload = _invocation().model_dump(mode="json")
    payload["protocol_version"] = "grafy-plugin-invocation@99"

    with pytest.raises(PluginProtocolCompatibilityError, match="@99"):
        PluginInvocationEnvelope.from_json_bytes(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        )


def test_result_failure_is_typed_and_output_bundles_cannot_mint_host_identity() -> None:
    failure = PluginInvocationResultEnvelope(
        invocation_id=INVOCATION_ID,
        status="failed",
        failure=PluginFailureEnvelope(
            code=PluginFailureCode.OPERATOR_FAILURE,
            message="Operator notes.summary.render@1 failed",
            release_slug="notes",
            release_revision=4,
            operator_id="notes.summary.render",
            operator_version=1,
            node_id="render",
        ),
    )
    restored = PluginInvocationResultEnvelope.from_json_bytes(
        failure.canonical_json_bytes()
    )
    assert restored.failure is not None
    assert restored.failure.code is PluginFailureCode.OPERATOR_FAILURE

    output = PluginOutputArtifactBundle(
        relative_path="outputs/o0000/a000000.json",
        byte_count=2,
        content_sha256="d" * 64,
    )
    output_payload = output.model_dump(mode="json")
    assert "artifact_id" not in output_payload
    assert "object_key" not in output_payload
    assert "workspace_id" not in output_payload
    assert {code.value for code in PluginFailureCode} == {
        "contract_failure",
        "materialization_failure",
        "operator_failure",
        "output_validation",
        "timeout",
        "cancellation",
        "internal_adapter_failure",
    }


def test_progress_events_round_trip_in_order_and_legacy_results_default_empty() -> None:
    result = PluginInvocationResultEnvelope(
        invocation_id=INVOCATION_ID,
        status="succeeded",
        progress=(
            PluginProgressEvent(message="  Starting  "),
            PluginProgressEvent(message="Halfway", current=5, total=10),
            PluginProgressEvent(message="Complete", current=10, total=10),
        ),
    )

    restored = PluginInvocationResultEnvelope.from_json_bytes(
        result.canonical_json_bytes()
    )

    assert [event.message for event in restored.progress] == [
        "Starting",
        "Halfway",
        "Complete",
    ]
    legacy_payload = result.model_dump(mode="json", exclude={"progress"})
    legacy_result = PluginInvocationResultEnvelope.from_json_bytes(
        json.dumps(legacy_payload, sort_keys=True).encode("utf-8")
    )
    assert legacy_result.progress == ()


@pytest.mark.parametrize(
    ("event", "message"),
    [
        ({"message": "   "}, "must not be blank"),
        ({"message": "x" * 1_001}, "at most 1000 characters"),
        ({"message": "working", "current": -1}, "greater than or equal to 0"),
        (
            {"message": "working", "current": 9_007_199_254_740_992},
            "less than or equal to 9007199254740991",
        ),
        ({"message": "working", "total": -1}, "greater than or equal to 0"),
        (
            {"message": "working", "total": 9_007_199_254_740_992},
            "less than or equal to 9007199254740991",
        ),
        (
            {"message": "working", "current": 2, "total": 1},
            "must not exceed total",
        ),
    ],
)
def test_progress_events_reject_unbounded_values(
    event: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        PluginProgressEvent.model_validate(event)


def test_result_envelope_bounds_progress_event_count() -> None:
    event = PluginProgressEvent(message="working")

    with pytest.raises(ValidationError, match="at most 128 items"):
        PluginInvocationResultEnvelope(
            invocation_id=INVOCATION_ID,
            status="succeeded",
            progress=(event,) * (MAX_PLUGIN_PROGRESS_EVENTS + 1),
        )


def test_result_envelope_bounds_serialized_progress_bytes() -> None:
    escaped_message = "\0" * 1_000
    event = PluginProgressEvent(message=escaped_message)
    event_count = MAX_PLUGIN_PROGRESS_BYTES // len(event.canonical_json_bytes()) + 1

    with pytest.raises(ValidationError, match="progress exceeds.*byte limit"):
        PluginInvocationResultEnvelope(
            invocation_id=INVOCATION_ID,
            status="succeeded",
            progress=(event,) * event_count,
        )
