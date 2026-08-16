import base64
import json
from pathlib import Path
import subprocess
import sys

from pydantic import BaseModel, ConfigDict

from grafy_agent_worker.sandbox.daytona import _EXEC_SCRIPT  # pyright: ignore[reportPrivateUsage]


class BoundedExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    output_truncated: bool


def test_daytona_wrapper_kills_child_at_combined_output_ceiling(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "fence"
    marker.write_text("expected", encoding="utf-8")
    command = base64.urlsafe_b64encode(
        json.dumps(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('x' * 1000000)",
            ],
            separators=(",", ":"),
        ).encode()
    ).decode()

    completed = subprocess.run(
        (
            sys.executable,
            "-c",
            _EXEC_SCRIPT,
            str(marker),
            "expected",
            command,
            str(tmp_path),
            "10",
            "1024",
            "-",
        ),
        check=True,
        capture_output=True,
        timeout=10,
    )
    result = BoundedExecutionResponse.model_validate_json(completed.stdout)

    assert result.output_truncated
    assert (
        len(base64.b64decode(result.stdout)) + len(base64.b64decode(result.stderr))
        <= 1024
    )
    assert result.exit_code != 0
