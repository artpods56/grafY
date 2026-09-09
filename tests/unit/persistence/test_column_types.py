from enum import StrEnum
import os

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, insert, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator
from sqlalchemy.ext.asyncio import create_async_engine

from grafy_core.domain.saved_graphs import SavedGraphDocument
from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginRuntimeArtifact,
    PluginNodeContract,
)
from grafy_core.domain.identity import (
    WorkspaceKind,
    WorkspaceRole,
    WorkspaceInvitationStatus,
)
from grafy_core.domain.module_library import ModulePublicationState
from grafy_core.domain.plugin_releases import PluginReleaseScope, PluginExecutionPolicy
from grafy_core.domain.plugin_revocations import PluginReleaseRevocationReason
from grafy_core.domain.plugin_selection import PluginFamilyLifecycle
from grafy_core.domain.templates import TemplateState
from grafy_core.domain.security_audit import (
    SecurityAuditActorKind,
    SecurityAuditOutcome,
)
from grafy_persistence import schema


MODEL_CASES = [
    (schema.SavedGraphDocumentType, SavedGraphDocument()),
    (
        schema.PluginCatalogManifestType,
        PluginCatalogManifest(
            slug="notes",
            title="Notes",
            nodes=(
                PluginNodeContract(
                    operator_id="notes.echo",
                    operator_version=1,
                    title="Echo",
                    description="Echo text",
                    config_schema={"type": "object"},
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    inputs=(),
                    outputs=(),
                ),
            ),
        ),
    ),
    (schema.PluginCapabilityManifestType, PluginCapabilityManifest()),
    (
        schema.PluginRuntimeArtifactType,
        PluginRuntimeArtifact(
            object_key="plugins/image.tar",
            archive_digest="a" * 64,
            manifest_digest="b" * 64,
            config_digest="c" * 64,
        ),
    ),
]
ENUM_CASES = [
    (schema.PluginReleaseScopeType, PluginReleaseScope, 16),
    (
        schema.PluginReleaseRevocationReasonType,
        PluginReleaseRevocationReason,
        16,
    ),
    (schema.PluginExecutionPolicyType, PluginExecutionPolicy, 24),
    (schema.PluginFamilyLifecycleType, PluginFamilyLifecycle, 16),
    (schema.WorkspaceKindType, WorkspaceKind, 16),
    (schema.WorkspaceRoleType, WorkspaceRole, 16),
    (schema.WorkspaceInvitationStatusType, WorkspaceInvitationStatus, 16),
    (schema.ModulePublicationStateType, ModulePublicationState, 32),
    (schema.TemplateStateType, TemplateState, 16),
    (schema.SecurityAuditActorKindType, SecurityAuditActorKind, 24),
    (schema.SecurityAuditOutcomeType, SecurityAuditOutcome, 16),
]


@pytest.mark.parametrize("column_type,model", MODEL_CASES)
@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()])
def test_model_storage_processors_preserve_validation_and_nulls[T: BaseModel](
    column_type: type[TypeDecorator[T]],
    model: T,
    dialect: Dialect,
) -> None:
    column = column_type()
    encoded = column.process_bind_param(model, dialect)
    assert encoded == model.model_dump(mode="json")
    assert column.process_result_value(encoded, dialect) == model
    assert column.process_bind_param(None, dialect) is None
    assert column.process_result_value(None, dialect) is None
    with pytest.raises(ValidationError):
        column.process_result_value([], dialect)


@pytest.mark.parametrize("column_type,enum_type,length", ENUM_CASES)
@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()])
def test_enum_storage_processors_preserve_values_lengths_and_errors[E: StrEnum](
    column_type: type[TypeDecorator[E]],
    enum_type: type[E],
    length: int,
    dialect: Dialect,
) -> None:
    column = column_type()
    assert str(column.compile(dialect=dialect)) == f"VARCHAR({length})"
    for value in enum_type:
        assert column.process_bind_param(value, dialect) == value.value
        assert column.process_result_value(value.value, dialect) is value
    assert column.process_bind_param(None, dialect) is None
    assert column.process_result_value(None, dialect) is None
    with pytest.raises(ValueError):
        column.process_result_value("not-a-domain-value", dialect)


@pytest.mark.filterwarnings("error:.*cache key.*")
@pytest.mark.parametrize("column_type,model", MODEL_CASES)
def test_model_columns_round_trip_with_sqlalchemy_statement_caching[T: BaseModel](
    column_type: type[TypeDecorator[T]],
    model: T,
) -> None:
    engine = create_engine("sqlite://")
    table = Table(
        "values",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("value", column_type()),
    )
    try:
        table.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(
                insert(table), [{"id": 1, "value": model}, {"id": 2, "value": None}]
            )
            statement = select(table.c.value).order_by(table.c.id)
            for _ in range(2):
                values = list(connection.scalars(statement))
                assert values == [model, None]
    finally:
        engine.dispose()


@pytest.mark.filterwarnings("error:.*cache key.*")
@pytest.mark.parametrize("column_type,enum_type,length", ENUM_CASES)
def test_enum_columns_round_trip_with_sqlalchemy_statement_caching[E: StrEnum](
    column_type: type[TypeDecorator[E]],
    enum_type: type[E],
    length: int,
) -> None:
    del length
    engine = create_engine("sqlite://")
    table = Table(
        "values",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("value", column_type()),
    )
    expected = [*enum_type, None]
    try:
        table.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(
                insert(table),
                [{"id": index, "value": value} for index, value in enumerate(expected)],
            )
            statement = select(table.c.value).order_by(table.c.id)
            for _ in range(2):
                assert list(connection.scalars(statement)) == expected
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.filterwarnings("error:.*cache key.*")
async def test_named_column_types_round_trip_on_postgresql() -> None:
    database_url = os.environ.get("GRAFY_TEST_POSTGRES_URL")
    if database_url is None:
        pytest.skip("GRAFY_TEST_POSTGRES_URL is not configured")
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("GRAFY_TEST_POSTGRES_URL must use postgresql+asyncpg")
    engine = create_async_engine(database_url)
    metadata = MetaData()
    cases: list[tuple[Table, list[BaseModel | StrEnum | None]]] = []
    for index, (model_column_type, model) in enumerate(MODEL_CASES):
        table = Table(
            f"column_contract_model_{index}",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("value", model_column_type()),
            prefixes=["TEMPORARY"],
        )
        cases.append((table, [model, None]))
    for index, (enum_column_type, enum_type, _) in enumerate(ENUM_CASES):
        table = Table(
            f"column_contract_enum_{index}",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("value", enum_column_type()),
            prefixes=["TEMPORARY"],
        )
        cases.append((table, [*enum_type, None]))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            for table, expected in cases:
                await connection.execute(
                    insert(table),
                    [
                        {"id": index, "value": value}
                        for index, value in enumerate(expected)
                    ],
                )
                statement = select(table.c.value).order_by(table.c.id)
                for _ in range(2):
                    actual = list(await connection.scalars(statement))
                    assert actual == expected
                    assert [type(value) for value in actual] == [
                        type(value) for value in expected
                    ]
    finally:
        await engine.dispose()
