from pathlib import Path

import tomllib
from grafy_plugin_sql import SQL


def test_sql_execute_declares_password_bound_to_connection_config() -> None:
    registration = next(
        registration
        for registration in SQL.nodes
        if registration.key == ("sql.postgresql.execute", 1)
    )

    assert len(registration.secret_inputs) == 1
    assert registration.secret_inputs[0].name == "password"
    assert registration.secret_inputs[0].config_dependencies == (
        "host",
        "port",
        "database",
        "username",
        "ssl_mode",
    )


def test_sql_package_metadata_has_no_ambient_plugin_entry_point() -> None:
    project_root = Path(__file__).parents[3]
    metadata = tomllib.loads(
        (project_root / "plugins" / "sql" / "pyproject.toml").read_text()
    )

    assert metadata["project"]["name"] == "grafy-plugin-sql"
    assert "entry-points" not in metadata["project"]
