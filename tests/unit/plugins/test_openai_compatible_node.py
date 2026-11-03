from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_core.plugins import NodeHttpEgressInput
from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_core.prompt_contracts import (
    PROMPT_MESSAGE,
    PromptMessage,
    PromptMessageRole,
)
from grafy_core.schema_contracts import JSON_SCHEMA
from grafy_core.ports.node_secrets import JsonValue
from grafy_plugin_llm.artifacts import COMPLETION
from grafy_plugin_llm.declaration import LLM
from grafy_plugin_llm.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleExecutionError,
    OpenAICompatibleInput,
    OpenAICompatibleNode,
    OpenAICompatibleProviderError,
    OpenAICompatibleProviderResponse,
)


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


class FakeNodeSecrets:
    def __init__(
        self,
        value: SecretStr,
        error: Exception | None = None,
    ) -> None:
        self._value = value
        self._error = error
        self.project_id: UUID | None = None
        self.graph_id: str | None = None
        self.node_id: str | None = None
        self.name: str | None = None
        self.dependencies: Mapping[str, JsonValue] | None = None

    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> SecretStr:
        self.project_id = project_id
        assert workspace_id == WORKSPACE_ID
        self.graph_id = graph_id
        self.node_id = node_id
        self.name = name
        self.dependencies = dependencies
        if self._error is not None:
            raise self._error
        return self._value

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        del workspace_id, project_id, graph_id, node_id, name, dependencies
        return "0" * 64


class FakeProvider:
    def __init__(
        self,
        response: OpenAICompatibleProviderResponse,
        error: Exception | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.messages: list[PromptMessage] | None = None
        self.json_schema: str | None = None
        self.config: OpenAICompatibleConfig | None = None
        self.api_key: SecretStr | None = None

    async def complete(
        self,
        messages: list[PromptMessage],
        json_schema: str | None,
        config: OpenAICompatibleConfig,
        api_key: SecretStr,
        /,
        *,
        workspace_id: UUID,
    ) -> OpenAICompatibleProviderResponse:
        self.messages = messages
        self.json_schema = json_schema
        self.config = config
        self.api_key = api_key
        assert workspace_id == WORKSPACE_ID
        if self._error is not None:
            raise self._error
        return self._response


def object_schema() -> str:
    return (
        '{"type":"object","properties":{"answer":{"type":"integer"}},'
        '"required":["answer"],"additionalProperties":false}'
    )


def test_node_declares_many_messages_optional_schema_and_write_only_key() -> None:
    assert OpenAICompatibleNode.operator_id == ("llm.openai_compatible.chat_completion")
    assert OpenAICompatibleNode.operator_version == 1
    assert OpenAICompatibleNode.plugin_slug == "external.llm"
    assert OpenAICompatibleNode.input_contract.ports["messages"].accepts == (
        PROMPT_MESSAGE.key
    )
    assert OpenAICompatibleNode.input_contract.ports["messages"].shape is (
        PortShape.MANY
    )
    assert OpenAICompatibleNode.input_contract.ports["messages"].required
    schema_port = OpenAICompatibleNode.input_contract.ports["json_schema"]
    assert schema_port.accepts == JSON_SCHEMA.key
    assert schema_port.shape is PortShape.ONE
    assert schema_port.allows_none
    assert not schema_port.required
    assert OpenAICompatibleNode.output_contract.ports["completion"].produces == (
        COMPLETION.key
    )

    registration = next(
        contribution
        for contribution in LLM.nodes
        if contribution.key == (OpenAICompatibleNode.operator_id, 1)
    )
    assert registration.secret_inputs[0].name == "api_key"
    assert registration.secret_inputs[0].config_dependencies == ("base_url",)
    assert "api_key" not in OpenAICompatibleConfig.model_fields

    assert registration.required_capabilities == (
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    )
    assert registration.http_egress is not None
    assert registration.http_egress.configured_inputs == (
        NodeHttpEgressInput(config_field="base_url"),
    )
    assert registration.http_egress.dynamic_destinations is False


async def test_node_resolves_bound_secret_and_builds_completion_artifact() -> None:
    project_id = uuid4()
    secret = SecretStr("secret-provider-key")
    secrets = FakeNodeSecrets(secret)
    provider = FakeProvider(
        OpenAICompatibleProviderResponse(
            content="The answer is 42.",
            model="provider-model-2026-01",
            response_id="chatcmpl-123",
            finish_reason="stop",
            usage={"total_tokens": 20},
        )
    )
    node = OpenAICompatibleNode(provider=provider, node_secrets=secrets)
    messages = [
        PromptMessage(
            role=PromptMessageRole.SYSTEM,
            text="Answer concisely.",
        ),
        PromptMessage(
            role=PromptMessageRole.USER,
            text="What is 6 times 7?",
        ),
    ]
    config = OpenAICompatibleConfig(
        base_url="https://gateway.example/v1/",
        model="vendor/model",
    )

    output = await node.run(
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id="drafts",
            node_id="completion-1",
        ),
        config,
        OpenAICompatibleInput(messages=messages),
    )

    assert secrets.project_id == project_id
    assert secrets.graph_id == "drafts"
    assert secrets.node_id == "completion-1"
    assert secrets.name == "api_key"
    assert secrets.dependencies == {"base_url": "https://gateway.example/v1"}
    assert provider.messages == messages
    assert provider.json_schema is None
    assert provider.config == config
    assert provider.api_key is secret
    serialized = output.completion.model_dump(mode="json", by_alias=True)
    assert serialized == {
        "content": "The answer is 42.",
        "structured_value": None,
        "model": "provider-model-2026-01",
        "protocol": "openai_chat_completions",
        "base_url": "https://gateway.example/v1",
        "response_id": "chatcmpl-123",
        "finish_reason": "stop",
        "message_count": 2,
        "source_image_artifact_ids": [],
        "schema": None,
        "schema_name": None,
        "schema_strict": None,
        "usage": {"total_tokens": 20},
    }
    assert "secret-provider-key" not in str(serialized)


async def test_node_does_not_use_materialization_graph_as_secret_context() -> None:
    secrets = FakeNodeSecrets(SecretStr("secret-provider-key"))
    node = OpenAICompatibleNode(
        provider=FakeProvider(
            OpenAICompatibleProviderResponse(
                content="Done",
                model="provider-model",
            )
        ),
        node_secrets=secrets,
    )

    await node.run(
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            node_id="completion-1",
        ),
        OpenAICompatibleConfig(),
        OpenAICompatibleInput(
            messages=[
                PromptMessage(
                    role=PromptMessageRole.USER,
                    text="Complete it.",
                )
            ]
        ),
    )

    assert secrets.project_id is None
    assert secrets.graph_id is None


async def test_node_builds_schema_validated_completion_artifact() -> None:
    schema = object_schema()
    image_id = uuid4()
    node = OpenAICompatibleNode(
        provider=FakeProvider(
            OpenAICompatibleProviderResponse(
                content='{"answer":42}',
                structured_value={"answer": 42},
                model="structured-model",
            )
        ),
        node_secrets=FakeNodeSecrets(SecretStr("secret-provider-key")),
    )

    output = await node.run(
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            project_id=uuid4(),
            graph_id="drafts",
            node_id="structured-1",
        ),
        OpenAICompatibleConfig(schema_name="answer", strict=True),
        OpenAICompatibleInput(
            messages=[
                PromptMessage(
                    role=PromptMessageRole.USER,
                    text="Return the answer.",
                    image_refs=[
                        ArtifactRef.from_key(
                            artifact_id=image_id,
                            key=RASTER_IMAGE.key,
                        )
                    ],
                )
            ],
            json_schema=schema,
        ),
    )

    assert output.completion.structured_value == {"answer": 42}
    assert output.completion.json_schema == schema
    assert output.completion.schema_name == "answer"
    assert output.completion.schema_strict is True
    assert output.completion.source_image_artifact_ids == [image_id]


async def test_node_maps_provider_error_without_rendering_secret_or_body() -> None:
    sensitive_provider_error = RuntimeError(
        "Authorization: Bearer secret-provider-key; response body: private"
    )
    node = OpenAICompatibleNode(
        provider=FakeProvider(
            OpenAICompatibleProviderResponse(
                content="unused",
                model="unused",
            ),
            error=sensitive_provider_error,
        ),
        node_secrets=FakeNodeSecrets(SecretStr("secret-provider-key")),
    )

    with pytest.raises(
        OpenAICompatibleExecutionError,
        match=("text output.*gpt-4.1-mini.*https://api.openai.com/v1.*1 messages"),
    ) as captured:
        await node.run(
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                project_id=uuid4(),
                graph_id="drafts",
                node_id="completion-1",
            ),
            OpenAICompatibleConfig(),
            OpenAICompatibleInput(
                messages=[
                    PromptMessage(
                        role=PromptMessageRole.USER,
                        text="Complete it.",
                    )
                ]
            ),
        )

    assert "secret-provider-key" not in str(captured.value)
    assert "private" not in str(captured.value)
    assert captured.value.__cause__ is sensitive_provider_error


async def test_node_surfaces_sanitized_provider_error_with_its_cause() -> None:
    provider_error = OpenAICompatibleProviderError(
        "Chat Completions request returned HTTP 400. Check whether the model "
        "supports images and strict JSON Schema response formatting."
    )
    node = OpenAICompatibleNode(
        provider=FakeProvider(
            OpenAICompatibleProviderResponse(
                content="unused",
                model="unused",
            ),
            error=provider_error,
        ),
        node_secrets=FakeNodeSecrets(SecretStr("secret-provider-key")),
    )

    with pytest.raises(
        OpenAICompatibleExecutionError,
        match="HTTP 400.*images.*strict JSON Schema",
    ) as captured:
        await node.run(
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                project_id=uuid4(),
                graph_id="drafts",
                node_id="completion-1",
            ),
            OpenAICompatibleConfig(),
            OpenAICompatibleInput(
                messages=[
                    PromptMessage(
                        role=PromptMessageRole.USER,
                        text="Complete it.",
                    )
                ]
            ),
        )

    assert str(captured.value) == str(provider_error)
    assert captured.value.__cause__ is provider_error
    assert "secret-provider-key" not in str(captured.value)


async def test_node_maps_secret_lookup_error_without_rendering_secret() -> None:
    sensitive_lookup_error = RuntimeError("Could not decrypt secret-provider-key")
    node = OpenAICompatibleNode(
        provider=FakeProvider(
            OpenAICompatibleProviderResponse(
                content="unused",
                model="unused",
            )
        ),
        node_secrets=FakeNodeSecrets(
            SecretStr("unused"),
            error=sensitive_lookup_error,
        ),
    )

    with pytest.raises(
        OpenAICompatibleExecutionError,
        match="could not resolve its API key.*completion-1.*gpt-4.1-mini",
    ) as captured:
        await node.run(
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                project_id=uuid4(),
                graph_id="drafts",
                node_id="completion-1",
            ),
            OpenAICompatibleConfig(),
            OpenAICompatibleInput(
                messages=[
                    PromptMessage(
                        role=PromptMessageRole.USER,
                        text="Complete it.",
                    )
                ]
            ),
        )

    assert "secret-provider-key" not in str(captured.value)
    assert captured.value.__cause__ is sensitive_lookup_error


async def test_node_uses_sdk_egress_guard_for_private_destination() -> None:
    from tests.unit.plugins.test_openai_compatible_provider import FakeStorage
    from grafy_core.runtime.in_memory import InMemoryUnitOfWork
    from grafy_plugin_llm.openai_compatible_sdk import OpenAICompatibleSdkProvider
    from tests.support.egress import loopback_http_listener, no_grants

    async with loopback_http_listener() as listener:
        node = OpenAICompatibleNode(
            provider=OpenAICompatibleSdkProvider(
                uow=InMemoryUnitOfWork(),
                storage=FakeStorage(),
                egress_policy=no_grants(),
            ),
            node_secrets=FakeNodeSecrets(SecretStr("graph-provider-key")),
        )
        with pytest.raises(OpenAICompatibleExecutionError, match="may not be dialed"):
            await node.run(
                NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="completion-1"),
                OpenAICompatibleConfig(base_url=f"{listener.base_url}/v1"),
                OpenAICompatibleInput(
                    messages=[PromptMessage(role=PromptMessageRole.USER, text="Hello")]
                ),
            )
        assert listener.requests == []
