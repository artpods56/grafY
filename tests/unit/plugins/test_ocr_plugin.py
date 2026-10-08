from pathlib import Path

import tomllib


def test_ocr_package_metadata_has_no_ambient_plugin_entry_point() -> None:
    project_root = Path(__file__).parents[3]
    metadata = tomllib.loads(
        (project_root / "plugins" / "ocr" / "pyproject.toml").read_text()
    )

    assert metadata["project"]["name"] == "grafy-plugin-ocr"
    assert "entry-points" not in metadata["project"]
