from collections.abc import Mapping
from io import BytesIO
from uuid import UUID

import pytest
from pydantic import SecretStr

from grafy_core.artifacts import ArtifactObject, ArtifactRef, NodeConfig
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.file_contracts import JSON_FILE
from grafy_core.nodes import NodeExecutionContext, UserFacingNodeError
from grafy_core.ports.storage import (
    ChunkReader,
    FileStreamProtocol,
    SaveFileCommand,
    StoredFile,
    StoredObjectInfo,
)
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_plugin.nodes import (
    ApplyReferenceTypesConfig,
    ApplyReferenceTypesInput,
    ClassifyReferenceConfig,
    ClassifyReferenceInput,
    ClassifyReferenceNode,
    ImportJsonInput,
    ImportSgkpJsonNode,
    SelectReferencesConfig,
    SelectReferencesInput,
    apply_reference_types,
    select_references,
)
from grafy_plugin.processing import parse_sgkp_records
from grafy_plugin.provider import ClassificationProviderError, ProviderSettings
from sample_dataset import SAMPLE_SGKP_JSON


TEST_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


class FakeSecretResolver:
    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> SecretStr:
        del workspace_id, graph_id, graph_revision, node_id, name, dependencies
        return SecretStr("test-key")

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        del workspace_id, graph_id, graph_revision, node_id, name, dependencies
        return "test-revision"


class FakeProvider:
    def __init__(self, outputs: list[str | ClassificationProviderError]) -> None:
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    async def complete(
        self,
        prompt: str,
        settings: ProviderSettings,
        api_key: SecretStr,
    ) -> str:
        del settings, api_key
        self.prompts.append(prompt)
        output = self.outputs.pop(0)
        if isinstance(output, ClassificationProviderError):
            raise output
        return output


ARTIFACT_BUCKET = "artifacts"
ARTIFACT_OBJECT_KEY = "files/sgkp_sample.json"


class RecordingFileStorage:
    """Records the one ``load`` the import node makes; other calls are bugs."""

    def __init__(self, content: bytes) -> None:
        self.content = content
        self.loaded: tuple[str, str] | None = None

    async def save(self, command: SaveFileCommand) -> StoredFile:
        raise AssertionError(f"Unexpected save to {command.bucket}/{command.path}")

    async def move(
        self,
        bucket: str,
        source_path: str,
        destination_path: str,
    ) -> None:
        raise AssertionError(
            f"Unexpected move from {bucket}/{source_path} to {destination_path}"
        )

    async def load(self, bucket: str, path: str) -> FileStreamProtocol:
        self.loaded = (bucket, path)
        return BytesIO(self.content)

    async def open_chunks(self, bucket: str, path: str) -> ChunkReader:
        raise AssertionError(f"Unexpected open_chunks for {bucket}/{path}")

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        raise AssertionError(f"Unexpected stat for {bucket}/{path}")

    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        raise AssertionError(
            f"Unexpected range load for {bucket}/{path} at {start}:{end_exclusive}"
        )

    async def delete(self, bucket: str, path: str) -> None:
        raise AssertionError(f"Unexpected delete for {bucket}/{path}")


async def seed_file_artifact(
    uow: InMemoryUnitOfWork,
    *,
    content: bytes,
    original_filename: str,
) -> ArtifactRef:
    artifact = ArtifactObject(
        workspace_id=TEST_WORKSPACE_ID,
        artifact_type=JSON_FILE.key.id,
        schema_version=JSON_FILE.key.schema_version,
        content_type="application/json",
        bucket=ARTIFACT_BUCKET,
        object_key=ARTIFACT_OBJECT_KEY,
        byte_size=len(content),
        metadata={"original_filename": original_filename},
    )
    async with uow as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    return artifact.ref()


@pytest.mark.asyncio
async def test_import_reads_sgkp_json_file_artifact() -> None:
    content = SAMPLE_SGKP_JSON
    storage = RecordingFileStorage(content)
    uow = InMemoryUnitOfWork()
    ref = await seed_file_artifact(
        uow,
        content=content,
        original_filename="sgkp_sample.json",
    )
    output = await ImportSgkpJsonNode(storage=storage, uow=uow).run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="import"),
        NodeConfig(),
        ImportJsonInput(file=ref),
    )
    assert storage.loaded == (ARTIFACT_BUCKET, ARTIFACT_OBJECT_KEY)
    assert output.dataset.source_name == "sgkp_sample.json"
    assert len(output.dataset.records) == 4
    assert output.dataset.records[0]["ID"] == "01-00001"


@pytest.mark.asyncio
async def test_select_emits_candidate_sequence_and_table() -> None:
    dataset = parse_sgkp_records(SAMPLE_SGKP_JSON, source_name="sgkp_sample.json")
    output = await select_references(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="select"),
        SelectReferencesConfig(),
        SelectReferencesInput(dataset=dataset),
    )
    assert [candidate.entry_id for candidate in output.candidates] == [
        "01-00010",
        "01-00100-a",
    ]
    assert [row["entry_id"] for row in output.table.rows] == [
        "01-00010",
        "01-00100-a",
    ]


@pytest.mark.asyncio
async def test_classify_validates_provider_json() -> None:
    dataset = parse_sgkp_records(SAMPLE_SGKP_JSON, source_name="sgkp_sample.json")
    selected = await select_references(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="select"),
        SelectReferencesConfig(),
        SelectReferencesInput(dataset=dataset),
    )
    provider = FakeProvider(
        [
            """{
              "decyzja": "dodaj_typ_miejscowosci",
              "pewnosc": "wysoka",
              "typy_miejscowosci": [{"typ": "folwark", "dowod": "folw."}],
              "ma_polozenie_administracyjne": true,
              "dowod_polozenia_administracyjnego": "pow. pleszewski",
              "uzasadnienie": "Tekst jawnie okresla typ glownego obiektu."
            }"""
        ]
    )
    node = ClassifyReferenceNode(
        provider=provider,
        node_secrets=FakeSecretResolver(),
    )
    output = await node.run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="classify"),
        ClassifyReferenceConfig(retry_delay_ms=0),
        ClassifyReferenceInput(candidate=selected.candidates[0]),
    )
    assert output.decision.decision == "dodaj_typ_miejscowosci"
    assert output.decision.settlement_types[0].type_name == "folwark"
    assert output.decision.settlement_point_types == ["Folwark"]


@pytest.mark.asyncio
async def test_classify_retries_invalid_json_then_succeeds() -> None:
    dataset = parse_sgkp_records(SAMPLE_SGKP_JSON, source_name="sgkp_sample.json")
    selected = await select_references(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="select"),
        SelectReferencesConfig(),
        SelectReferencesInput(dataset=dataset),
    )
    provider = FakeProvider(
        [
            "not-json",
            """{
              "decyzja": "brak_podstaw",
              "pewnosc": "wysoka",
              "typy_miejscowosci": [],
              "ma_polozenie_administracyjne": false,
              "dowod_polozenia_administracyjnego": "",
              "uzasadnienie": "Brak typu."
            }""",
        ]
    )
    node = ClassifyReferenceNode(
        provider=provider,
        node_secrets=FakeSecretResolver(),
    )
    output = await node.run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="classify"),
        ClassifyReferenceConfig(max_retries=2, retry_delay_ms=0),
        ClassifyReferenceInput(candidate=selected.candidates[0]),
    )
    assert output.decision.decision == "brak_podstaw"
    assert len(provider.prompts) == 2
    assert "POPRZEDNIA ODPOWIEDZ BYLA NIEPOPRAWNA" in provider.prompts[1]


@pytest.mark.asyncio
async def test_classify_surfaces_exhausted_provider_errors() -> None:
    dataset = parse_sgkp_records(SAMPLE_SGKP_JSON, source_name="sgkp_sample.json")
    selected = await select_references(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="select"),
        SelectReferencesConfig(),
        SelectReferencesInput(dataset=dataset),
    )
    node = ClassifyReferenceNode(
        provider=FakeProvider(
            [
                ClassificationProviderError("timed out", transient=True),
                ClassificationProviderError("timed out", transient=True),
            ]
        ),
        node_secrets=FakeSecretResolver(),
    )
    with pytest.raises(UserFacingNodeError, match="timed out"):
        await node.run(
            NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="classify"),
            ClassifyReferenceConfig(max_retries=2, retry_delay_ms=0),
            ClassifyReferenceInput(candidate=selected.candidates[0]),
        )


@pytest.mark.asyncio
async def test_apply_updates_dataset_and_result_table() -> None:
    dataset = parse_sgkp_records(SAMPLE_SGKP_JSON, source_name="sgkp_sample.json")
    selected = await select_references(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="select"),
        SelectReferencesConfig(),
        SelectReferencesInput(dataset=dataset),
    )
    node = ClassifyReferenceNode(
        provider=FakeProvider(
            [
                """{
                  "decyzja": "dodaj_typ_miejscowosci",
                  "pewnosc": "wysoka",
                  "typy_miejscowosci": [{"typ": "folwark", "dowod": "folw."}],
                  "ma_polozenie_administracyjne": true,
                  "dowod_polozenia_administracyjnego": "pow. pleszewski",
                  "uzasadnienie": "Tekst jawnie okresla typ glownego obiektu."
                }"""
            ]
        ),
        node_secrets=FakeSecretResolver(),
    )
    classified = await node.run(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="classify"),
        ClassifyReferenceConfig(retry_delay_ms=0),
        ClassifyReferenceInput(candidate=selected.candidates[0]),
    )
    output = await apply_reference_types(
        NodeExecutionContext(workspace_id=TEST_WORKSPACE_ID, node_id="apply"),
        ApplyReferenceTypesConfig(),
        ApplyReferenceTypesInput(
            dataset=dataset,
            decisions=[classified.decision],
        ),
    )
    assert output.dataset.records[2]["typ"] == ["odsyłacz", "folwark"]
    assert output.table.rows[0]["changed"] is True
