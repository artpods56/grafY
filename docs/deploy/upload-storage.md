# Upload object storage receive bounds

Local API content routes reject excess bytes while reading the request body.
Presigned MinIO/S3 uploads must enforce the same bound at the storage proxy:

- Configure the browser-facing signing endpoint with
  `GRAFY_S3_SIGNING_ENDPOINT_URL` when it differs from the internal
  `GRAFY_S3_ENDPOINT_URL`. Signatures use the signing host directly.
- Signed PUT targets require `If-None-Match: *` as part of the signature so a
  completed object cannot be replaced through the same upload URL.
- Bound request duration and body size on the MinIO/proxy path to
  `GRAFY_UPLOAD_RECEIVE_TIMEOUT_SECONDS` and `GRAFY_STAGED_UPLOAD_MAX_BYTES`.
  Completion checks accepted artifact size, but does not by itself stop excess
  bytes from reaching object storage.
- Abandoned upload cleanup expires pending rows after
  `GRAFY_UPLOAD_LIFETIME_SECONDS` and retains terminal tracking until target TTL
  plus the receive timeout have elapsed, so a late in-flight PUT cannot leave
  unreclaimable bytes.

## Same-origin uploads through the Compose gateway

MinIO stays on a private Docker network. Browsers upload through the gateway's
`/storage/` location on the public origin, so the page never sees the internal
`http://minio:9000` endpoint (which HTTPS pages block as mixed content).

```dotenv
GRAFY_STORAGE_BACKEND=s3
GRAFY_STORAGE_BUCKET=workbench-artifacts
GRAFY_S3_ENDPOINT_URL=http://minio:9000
GRAFY_S3_SIGNING_ENDPOINT_URL=https://grafy.example.com/storage
GRAFY_S3_FORCE_PATH_STYLE=true
```

Include `infra/docker/compose.shared-storage.yaml` so both the API and the
gateway join the external MinIO network (`GRAFY_S3_DOCKER_NETWORK`, default
`shared-storage`, where MinIO answers as `minio:9000`).

### How the `/storage` prefix and SigV4 fit together

SigV4 signs the `Host` header and the request path. MinIO has no notion of the
`/storage` prefix, so it verifies `/<bucket>/<key>`. The API therefore signs
against the origin of `GRAFY_S3_SIGNING_ENDPOINT_URL` only and inserts its path
(`/storage`) into the returned URL afterwards. The gateway strips that prefix
from the raw request URI and forwards the rest, including the signed query,
byte-for-byte. Signing a URL that includes `/storage` would fail with
`SignatureDoesNotMatch`.

Every proxy between the browser and MinIO must forward `Host` unchanged (the
gateway uses `$http_host`, keeping a non-default port). A TLS edge in front of
the gateway that sets `Host $host` is fine on the default HTTPS port.

### What the gateway location allows

`infra/docker/gateway/nginx.conf` `location ^~ /storage/`:

- only `PUT`; other methods get `403` before reaching MinIO;
- only `/storage/workbench-artifacts/<key>?<query>`; every other bucket, the
  bucket root, MinIO admin/health paths and query-less requests get `404`. A
  non-default `GRAFY_STORAGE_BUCKET` must be changed in the `map` as well;
- `client_max_body_size 64m`, the `GRAFY_STAGED_UPLOAD_MAX_BYTES` ceiling.
  Oversized bodies get `413` before MinIO stores anything. An edge proxy in
  front of the gateway needs a limit of at least 64 MiB;
- request and response streaming (`proxy_request_buffering off`,
  `proxy_buffering off`), cookies and Authorization headers stripped;
- 60 s idle timeouts while receiving and forwarding the body. Open-source
  nginx cannot cap the total duration of one request, so a body trickled
  slowly can outlast `GRAFY_UPLOAD_RECEIVE_TIMEOUT_SECONDS`; upload cleanup
  remains the backstop for bytes that land late;
- access and error logging disabled for upload requests because signed query
  strings grant temporary access. Configure the outer TLS proxy to omit query
  strings for this route as well;
- MinIO is resolved per request through Docker DNS, so the gateway still
  starts (and `/storage/` returns `502`) when no MinIO is attached.

### Verify

```bash
just test-storage-gateway
```

starts the pinned MinIO behind the real gateway config
(`infra/docker/compose.storage-gateway-test.yaml`) and runs
`tests/integration/uploads/test_storage_gateway.py`: a signed create-only PUT
succeeds and cannot be replayed, a tampered path is rejected, non-`PUT`
methods, other buckets and oversize bodies are refused.

## Keep an existing direct-path upload deployment

Deployments already signing against the public origin without `/storage` can
keep the direct `/workbench-artifacts/objects/` route. Include
`infra/docker/compose.minio-uploads.yaml` after the base Compose file and set:

```dotenv
GRAFY_S3_SIGNING_ENDPOINT_URL=https://grafy.example.com
GRAFY_S3_FORCE_PATH_STYLE=true
```

The TLS edge must forward `/workbench-artifacts/objects/` to the gateway without
changing its path, query string, or public Host header. This route preserves the
signed object path directly; it does not strip a prefix. The same signer supports
both endpoint forms. Keep `GRAFY_STORAGE_BUCKET=workbench-artifacts`, or update
the supplied route when using another bucket.

The override joins the gateway to the existing private MinIO network. Set
`GRAFY_STORAGE_DOCKER_NETWORK` if that network has another name. The API also
needs access to MinIO, for example through `compose.shared-storage.yaml`. The
direct route is opt-in; the default `/storage/` route remains available.

The direct route permits PUT only, limits bodies to 64 MiB, strips cookies and
Authorization headers, and disables access and error logging. It uses
1800-second inactivity timeouts rather than the default route's 60 seconds;
lower these when the API upload limits are lower. Neither route imposes a total
receive-duration deadline. Configure the outer TLS proxy to omit signed query
strings too.

Verify a small signed PUT through the public HTTPS origin, compare the stored
bytes, and confirm that an unsigned PUT and a second PUT to the same object
are rejected. Remove the test object afterward.
