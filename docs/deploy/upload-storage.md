# Upload object storage receive bounds

Local API content routes reject excess bytes while reading the request body.
Presigned MinIO/S3 uploads must enforce the same bound at the storage proxy:

- Configure the browser-facing signing hostname with
  `GRAFY_S3_SIGNING_ENDPOINT_URL` when it differs from the internal
  `GRAFY_S3_ENDPOINT_URL`. Signatures use the signing hostname directly.
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

## Route browser uploads through the same-origin gateway

For an existing MinIO service named `minio` on the `shared-storage` Docker
network, add `infra/docker/compose.minio-uploads.yaml` after the base Compose
file. Set these values in the deployment environment:

```dotenv
GRAFY_STORAGE_BACKEND=s3
GRAFY_STORAGE_BUCKET=workbench-artifacts
GRAFY_S3_ENDPOINT_URL=http://minio:9000
GRAFY_S3_SIGNING_ENDPOINT_URL=https://graphs.example.com
GRAFY_S3_FORCE_PATH_STYLE=true
```

Replace the signing origin with the application's public HTTPS origin. Keep
the bucket name `workbench-artifacts` for the supplied route; change the route
too if the deployment uses another bucket. The TLS edge must forward
`/workbench-artifacts/objects/` to the gateway without changing its path, query
string, or public Host header. Do not add a `/storage` prefix or rewrite a URL
after signing it.

The override connects the gateway to MinIO's private network without publishing
MinIO's port. Set `GRAFY_STORAGE_DOCKER_NETWORK` if that network has another name.
The route permits PUT only, preserves signed headers including `If-None-Match`,
and removes application cookies and Authorization headers before forwarding.
MinIO validates each signature; buckets remain private.

The supplied route limits bodies to 64 MiB and uses 1800-second inactivity
timeouts. Lower these values when the API upload limits are lower. Nginx's
inactivity timeouts are not a total receive-duration deadline. Access and error
logging are disabled for this route because both can contain signed URLs.
Configure the outer TLS proxy to omit query strings for this route as well.

Verify a small signed PUT through the public HTTPS origin, compare the stored
bytes, and confirm that an unsigned PUT and a second PUT to the same object
are rejected. Remove the test object afterward.
