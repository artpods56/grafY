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
