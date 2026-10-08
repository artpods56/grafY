from pathlib import Path

import tomllib


def test_llm_package_metadata_has_no_ambient_plugin_entry_point() -> None:
    project_root = Path(__file__).parents[3]
    metadata = tomllib.loads(
        (project_root / "plugins" / "llm" / "pyproject.toml").read_text()
    )

    assert metadata["project"]["name"] == "grafy-plugin-llm"
    assert "entry-points" not in metadata["project"]
