"""The real tiler image against a real MinIO, with the deployment's hardening.

Runs only when GRAFY_TEST_TILER_IMAGE names a built image and a Docker daemon
answers; otherwise every test here is skipped, never silently passed. CI builds
`infra/docker/tiler.Dockerfile` and sets the variable. Locally:

    docker build -f infra/docker/tiler.Dockerfile --target tiler -t grafy-tiler:local .
    GRAFY_TEST_TILER_IMAGE=grafy-tiler:local uv run pytest -m container

Everything it creates (network, containers, volume) carries one random suffix
and is removed afterwards. The read-only MinIO account is created with the same
`mc` commands docs/how-to-deploy-production.md gives the operator, so those
commands are proven here.
"""

import hashlib
import io
import json
import os
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import boto3
import pytest
from PIL import Image

from grafy_tiler.grant import Grant, sign_grant

from .conftest import Writer

IMAGE = os.environ.get("GRAFY_TEST_TILER_IMAGE")
# The same pinned MinIO the storage-gateway test uses (infra/docker/
# compose.storage-gateway-test.yaml), plus Chainguard's matching client.
MINIO = "cgr.dev/chainguard/minio@sha256:4cf4831a2bbcf13ddca09c1cbcc9faff716dd3c4247e0babc32864b8ee8e0034"
MC = "cgr.dev/chainguard/minio-client@sha256:496b0185b51d406d12b6e64e7422959bada5e12a689c8c2ef049510cc3af3b06"
BUCKET = "workbench-artifacts"
READ_ONLY_USER = "tiler-ro"
POLICY = "grafy-tiler-read"
# Same shape as docs/how-to-deploy-production.md: read objects, nothing else.
POLICY_DOCUMENT = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["s3:GetObject"],
            "Resource": [f"arn:aws:s3:::{BUCKET}/*"],
        }
    ],
}


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return (
        subprocess.run(["docker", "info"], capture_output=True, check=False).returncode
        == 0
    )


pytestmark = [
    pytest.mark.container,
    pytest.mark.skipif(IMAGE is None, reason="GRAFY_TEST_TILER_IMAGE is not set"),
    pytest.mark.skipif(
        IMAGE is not None and not _docker_available(), reason="no Docker daemon"
    ),
]


def docker(*args: str, stdin: bytes | None = None) -> str:
    result = subprocess.run(
        ["docker", *args], input=stdin, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise AssertionError(
            f"docker {' '.join(args[:3])} failed: {result.stderr.decode()[-600:]}"
        )
    return result.stdout.decode().strip()


@dataclass(frozen=True)
class Stack:
    tiler_port: int
    minio_port: int
    signing_key: str
    tiler: str
    read_only_secret: str
    admin_secret: str


@pytest.fixture(scope="module")
def stack() -> Iterator[Stack]:
    suffix = secrets.token_hex(4)
    network, minio, tiler = (
        f"grafy-tiler-it-net-{suffix}",
        f"grafy-tiler-it-minio-{suffix}",
        f"grafy-tiler-it-tiler-{suffix}",
    )
    cache = f"grafy-tiler-it-cache-{suffix}"
    admin_secret = secrets.token_urlsafe(24)
    read_only_secret = secrets.token_urlsafe(24)
    signing_key = secrets.token_urlsafe(32)

    def mc(*args: str, stdin: bytes | None = None) -> str:
        return docker(
            "run", "--rm", "-i", "--network", network,
            "-e", f"MC_HOST_local=http://admin:{admin_secret}@minio:9000",
            MC, *args,
            stdin=stdin,
        )  # fmt: skip

    try:
        docker("network", "create", network)
        docker(
            "run", "-d", "--name", minio, "--network", network, "--network-alias", "minio",
            "-p", "127.0.0.1::9000",
            "-e", "MINIO_ROOT_USER=admin", "-e", f"MINIO_ROOT_PASSWORD={admin_secret}",
            MINIO, "server", "/data",
        )  # fmt: skip
        minio_port = int(
            docker("port", minio, "9000/tcp").splitlines()[0].rsplit(":", 1)[1]
        )

        # The operator commands, verbatim in intent (see the deploy guide).
        mc("ready", "local")  # blocks until MinIO answers
        mc("mb", f"local/{BUCKET}")
        mc("admin", "policy", "create", "local", POLICY, "/dev/stdin",
           stdin=json.dumps(POLICY_DOCUMENT).encode())  # fmt: skip
        mc("admin", "user", "add", "local", READ_ONLY_USER, read_only_secret)
        mc("admin", "policy", "attach", "local", POLICY, "--user", READ_ONLY_USER)

        docker(
            "run", "-d", "--name", tiler, "--network", network, "-p", "127.0.0.1::8100",
            "--init", "--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--memory", "1536m", "--cpus", "2",
            "--pids-limit", "256", "-v", f"{cache}:/cache",
            "-e", f"TILER_SIGNING_KEYS={signing_key}",
            "-e", f"TILER_BUCKET={BUCKET}", "-e", "TILER_STORAGE=s3",
            "-e", "TILER_S3_ENDPOINT_URL=http://minio:9000",
            "-e", f"TILER_S3_ACCESS_KEY_ID={READ_ONLY_USER}",
            "-e", f"TILER_S3_SECRET_ACCESS_KEY={read_only_secret}",
            "-e", "TILER_CACHE_MAX_BYTES=67108864",
            IMAGE or "",
        )  # fmt: skip
        tiler_port = int(
            docker("port", tiler, "8100/tcp").splitlines()[0].rsplit(":", 1)[1]
        )
        _wait_for_startup(tiler)

        yield Stack(
            tiler_port, minio_port, signing_key, tiler, read_only_secret, admin_secret
        )
    finally:
        for name in (tiler, minio):
            subprocess.run(
                ["docker", "rm", "-f", name], capture_output=True, check=False
            )
        subprocess.run(
            ["docker", "network", "rm", network], capture_output=True, check=False
        )
        subprocess.run(
            ["docker", "volume", "rm", cache], capture_output=True, check=False
        )


def _wait_for_startup(container: str) -> None:
    """Block on the container's own log line instead of polling health."""
    with subprocess.Popen(
        ["docker", "logs", "--follow", container],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ) as logs:
        assert logs.stdout is not None
        try:
            for line in logs.stdout:
                if "Application startup complete" in line:
                    return
            raise AssertionError("tiler exited before it started")
        finally:
            logs.kill()


def _upload(stack: Stack, path: Path, key: str) -> Grant:
    client = boto3.client(
        "s3",
        endpoint_url=f"http://127.0.0.1:{stack.minio_port}",
        aws_access_key_id="admin",
        aws_secret_access_key=stack.admin_secret,
        region_name="us-east-1",
    )
    body = path.read_bytes()
    client.put_object(Bucket=BUCKET, Key=key, Body=body)
    return Grant(
        bucket=BUCKET,
        key=key,
        sha256=hashlib.sha256(body).hexdigest(),
        byte_size=len(body),
        page=0,
        expires_at=int(time.time()) + 60,
    )


def _get(
    stack: Stack, path: str, grant: Grant | None = None, key: str | None = None
) -> tuple[int, bytes, str]:
    headers = {}
    if grant is not None:
        headers["X-Grafy-Grant"] = sign_grant(
            grant, (key or stack.signing_key).encode()
        )
    request = urllib.request.Request(
        f"http://127.0.0.1:{stack.tiler_port}{path}", headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return (
                response.status,
                response.read(),
                response.headers.get("content-type", ""),
            )
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers.get("content-type", "")


def test_the_image_runs_hardened(stack: Stack) -> None:
    inspected = json.loads(docker("inspect", stack.tiler))[0]
    host = inspected["HostConfig"]
    assert host["ReadonlyRootfs"] is True
    assert host["CapDrop"] == ["ALL"] and "no-new-privileges" in " ".join(
        host["SecurityOpt"]
    )
    assert host["Memory"] == 1536 * 1024 * 1024 and host["NanoCpus"] == 2 * 10**9
    assert docker("exec", stack.tiler, "id", "-u") == "10001"


def test_health_answers(stack: Stack) -> None:
    status, body, _ = _get(stack, "/health")
    assert status == 200 and json.loads(body)["status"] == "ok"


def test_the_read_only_account_cannot_write_or_list_but_the_tiler_still_reads(
    stack: Stack, gray8: Writer
) -> None:
    grant = _upload(stack, gray8(), "ws-1/artifacts/ab/scan.tif")
    status, body, kind = _get(stack, "/tiles/11/2/1.jpg", grant)
    assert (status, kind) == (200, "image/jpeg")
    assert Image.open(io.BytesIO(body)).size == (276, 188)

    client = boto3.client(
        "s3",
        endpoint_url=f"http://127.0.0.1:{stack.minio_port}",
        aws_access_key_id=READ_ONLY_USER,
        aws_secret_access_key=stack.read_only_secret,
        region_name="us-east-1",
    )
    with pytest.raises(client.exceptions.ClientError):
        client.put_object(Bucket=BUCKET, Key="ws-1/should-not-exist.tif", Body=b"x")
    with pytest.raises(client.exceptions.ClientError):
        client.list_objects_v2(Bucket=BUCKET)


def test_info_thumbnail_and_a_later_page_through_the_container(
    stack: Stack, multipage: Writer
) -> None:
    from dataclasses import replace

    grant = _upload(stack, multipage(), "ws-1/artifacts/cd/book.tif")
    status, body, _ = _get(stack, "/info", replace(grant, page=2))
    assert status == 200 and json.loads(body)["width"] == 480
    status, body, _ = _get(stack, "/thumbnail?edge=128", grant)
    assert status == 200 and Image.open(io.BytesIO(body)).width == 128


def test_a_grant_signed_with_another_key_is_refused(
    stack: Stack, gray8: Writer
) -> None:
    grant = _upload(stack, gray8(), "ws-1/artifacts/ef/other.tif")
    assert _get(stack, "/info", grant, key="x" * 40)[0] == 403
    assert _get(stack, "/info")[0] == 403


def test_a_grant_for_another_bucket_is_refused_before_storage(
    stack: Stack, gray8: Writer
) -> None:
    from dataclasses import replace

    grant = _upload(stack, gray8(), "ws-1/artifacts/12/bucket.tif")
    assert _get(stack, "/info", replace(grant, bucket="private-data"))[0] == 403


def test_the_cache_volume_holds_what_was_rendered(stack: Stack, gray8: Writer) -> None:
    grant = _upload(stack, gray8(), "ws-1/artifacts/34/cached.tif")
    assert _get(stack, "/tiles/10/0/0.jpg", grant)[0] == 200
    entries = docker("exec", stack.tiler, "sh", "-c", "find /cache -type f | wc -l")
    assert int(entries) >= 2  # the image info and the tile
