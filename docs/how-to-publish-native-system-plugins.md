# How to publish native System Plugins

Use this guide to rebuild the native runtime inputs and publish or promote a global System Plugin release. The registry and image recipes are opt-in. They do not run as part of the default Grafy Compose stack.

## Build the native runtime image

The image starts from the digest-pinned Astral uv Python 3.14 Trixie image. It copies the uv binary from the pinned Bookworm image used by Grafy's API. That keeps `uv sync --locked` aligned with the committed Plugin lockfiles. The image installs GDAL and its Python bindings, NumPy, Pillow, Tesseract, and the English OCR data. `python3-pil` is explicit because the minimal install does not guarantee Pillow, and GDAL 3.10's `gdal2tiles.py` imports PIL.

Debian Trixie's `python3-gdal` package targets system Python 3.13 and does not support Python 3.14. `gdal2tiles.py` uses those system bindings. Plugin code uses the Python 3.14 interpreter from uv and its own locked dependencies. See Debian's [`python3-gdal` package](https://packages.debian.org/trixie/python3-gdal) and the [GDAL 3.10 `gdal2tiles` reference](https://gdal.org/_/downloads/en/release-3.10/pdf/).

Start the loopback registry and publish the image:

```bash
just plugin-native-registry-up
just plugin-native-base-publish
```

The build defaults to `linux/amd64` and to `127.0.0.1:5000/grafy-plugin-base:gdal-tesseract`. Set `GRAFY_PLUGIN_NATIVE_BUILD_PLATFORM` for another target. Set `GRAFY_PLUGIN_RUNTIME_NATIVE_BASE_IMAGE` or `GRAFY_PLUGIN_NATIVE_BASE_TAG` to change the image name or tag. The recipe prints the repository and the registry manifest digest as separate environment assignments. Copy both into the deployment environment file:

```dotenv
GRAFY_PLUGIN_RUNTIME_PROFILE=python-uv-gdal-tesseract
GRAFY_PLUGIN_RUNTIME_NATIVE_BASE_IMAGE=127.0.0.1:5000/grafy-plugin-base
GRAFY_PLUGIN_RUNTIME_NATIVE_BASE_IMAGE_DIGEST=<digest printed by the recipe, without sha256:>
```

Keep the registry bound to loopback. It has no TLS or authentication. Do not publish it on a public or shared network. The registry image is pinned to Docker Official Image `registry:2.8.3` by its multi-platform manifest digest, and its named volume stores data under `/var/lib/registry`.

The `uv` image names and `COPY --from` form follow Astral's [uv Docker guide](https://docs.astral.sh/uv/guides/integration/docker/). Docker documents the same external-image copy contract in its [Dockerfile reference](https://docs.docker.com/reference/dockerfile/). Docker documents pushed manifest digests through Buildx's [`--metadata-file`](https://docs.docker.com/reference/cli/docker/buildx/build/).

## Build the publisher image

The `publisher` service builds from the checked-in `publisher` target in `infra/docker/api.Dockerfile`. That target extends `api-plugins`, which installs the CLI and copies the Docker CLI and buildx plugin for sibling sandbox containers.

Build it from the same source revision as the API. Force the local development tag during the build, even when `.env.production` sets a digest reference:

```bash
GRAFY_PUBLISHER_IMAGE=grafy-publisher:local docker compose \
  --env-file .env.production \
  -f infra/docker/compose.yaml \
  --profile publisher \
  build publisher
```

Push that image to the operator's registry and copy the reported manifest digest into `GRAFY_PUBLISHER_IMAGE`:

```bash
publisher_repo=127.0.0.1:5000/grafy-publisher
publisher_version=<source-revision>
docker tag grafy-publisher:local "$publisher_repo:$publisher_version"
docker push "$publisher_repo:$publisher_version"
docker buildx imagetools inspect "$publisher_repo:$publisher_version"
```

Set `GRAFY_PUBLISHER_IMAGE` to `127.0.0.1:5000/grafy-publisher@sha256:<manifest-digest>`. The publisher image may use a different registry from the native runtime base.

## Stage source for a published application release

For a production release with CI-published images, use
`ghcr.io/artpods56/grafy-publisher:<sha>` instead of rebuilding a local publisher.
Pull that image explicitly; the ordinary application deployment excludes the
publisher profile.

Archive Plugin source from the same commit, not an older host checkout:

```bash
git archive <sha> --output=/tmp/grafy-release.tar
shasum -a 256 /tmp/grafy-release.tar
```

Transfer the archive to a protected operation directory on the host. Compare its
SHA-256 digest with the local value before extracting `plugins/` into a fresh
source directory. Set these variables for the publisher's Compose invocation:

```dotenv
GRAFY_PUBLISHER_IMAGE=ghcr.io/artpods56/grafy-publisher:<sha>
GRAFY_PUBLISHER_SOURCE_ROOT=<absolute-path-to-extracted-plugins>
GRAFY_PUBLISHER_SCRATCH_ROOT=<absolute-host-scratch-path>
```

Mount the scratch directory at the same absolute path inside the publisher.
Its verification sandboxes are sibling containers, so Docker resolves bind
mounts on the host. Use the deployed release's Compose files, environment file,
and site override, including its storage network and network-policy mount.

Read `plugins/system-plugins.toml` from the archive to choose global publication
inputs and loader targets. Do not treat every directory under `plugins/` as a
System Plugin. A directory outside the inventory needs its own publication scope.
For `ai-ihpan`, leave Notarius unpublished unless the owner requests publication
in an appropriate scope.

To update the application and Plugins together, deploy the application first.
Publish the changed Plugins against its SDK and inventory, then promote their
exact returned revisions. When one Plugin produces a type owned by another,
publish and promote the type owner first. For example, update Image before
Mistral when their shared `image.regions` contract changes.

## Issue and rotate the platform token

Global publication and promotion use a `PlatformAccessToken`. The token needs both `plugin.publish_global` and `plugin.promote_global`. Keep the bearer value in a mode-0600 file outside the checkout, for example `/opt/graphy/.deployment/plugin-publishing-token`. Keep token file paths out of `grafy.env`; pass the path to the publisher as a bind mount.

The issue record does not identify the current token file path. Use the path above for a replacement, and have the deployment operator confirm the existing path before revoking the current token.

The CLI prints the bearer value once. Run issuance from a trusted shell and redirect stdout directly to the protected file so the value does not appear in terminal history, logs, or copied command output:

```bash
umask 077
docker exec grafy-api-1 .venv/bin/grafy admin platform-token create \
  --principal plugin-release-operator \
  --label "Plugin publishing" \
  --scope plugin.publish_global \
  --scope plugin.promote_global \
  --expires-at <UTC-expiry> \
  > /opt/graphy/.deployment/plugin-publishing-token
chmod 600 /opt/graphy/.deployment/plugin-publishing-token
```

Use a short-lived token for a one-time publication. Read the current token inventory with `grafy admin platform-token list`; expiry and revocation state are deployment data, not fixed dates in this guide. Revoke the operation's token by its database ID with `grafy admin platform-token revoke <token-id>`. Remove its protected file and temporary container copies even if publication or promotion fails. The database stores token metadata and digests, not the bearer value.

## Publish a candidate

Build and run one publisher container from the production Compose files. The container needs the protected token file, the network policy manifest, the configured egress broker image, and membership in the `shared-storage` network. The broker image and manifest must already be configured for the deployment. Do not pass the bearer value as an argument or environment value.

```bash
publisher=pub-plugin-release
token_file=/opt/graphy/.deployment/plugin-publishing-token
policy_file=/opt/graphy/.deployment/network-policy.toml

docker compose \
  --env-file .env.production \
  -f infra/docker/compose.yaml \
  -f infra/docker/compose.plugin-runtime.yaml \
  --profile publisher \
  run -d --name "$publisher" --no-deps --entrypoint sleep \
  -e GRAFY_TOKEN_FILE=/run/secrets/grafy-token \
  -e GRAFY_NETWORK_POLICY_MANIFEST=/etc/grafy/network-policy.toml \
  -v "$token_file:/run/secrets/grafy-token:ro" \
  -v "$policy_file:/etc/grafy/network-policy.toml:ro" \
  publisher 900

docker network connect shared-storage "$publisher"
docker exec -e GRAFY_TOKEN_FILE=/run/secrets/grafy-token "$publisher" \
  .venv/bin/grafy plugin publish /publisher-input/<plugin-directory> \
  --global \
  --slug <plugin-slug> \
  --sandbox-image "$GRAFY_PUBLISHER_IMAGE"
```

Record the returned release revision. Global publication creates an inactive candidate. It does not change the selected release.

## Promote the exact revision

Promote through the API container because admission uses the API's configured broker and policy manifest. Copy the protected token file into the container, run promotion for the exact slug and revision, then remove the temporary copy:

```bash
docker cp "$token_file" grafy-api-1:/tmp/grafy-platform-token
docker exec grafy-api-1 chmod 600 /tmp/grafy-platform-token
docker exec -e GRAFY_TOKEN_FILE=/tmp/grafy-platform-token grafy-api-1 \
  .venv/bin/grafy plugin promote <plugin-slug>@<revision>
docker exec grafy-api-1 rm /tmp/grafy-platform-token
```

Verify the selected revision and a representative run. Revoke the one-time token after the operation, then remove its protected file. Add `--if-generation <generation>` only when an automated promotion must reject a concurrent selection change.

## Resolve promotion failures and verify cleanup

If publication succeeds but promotion fails, keep the returned release inactive
and read the admission error. Do not republish the same candidate just to retry
promotion.

For `network_profile_disabled`, assign the Plugin an appropriate profile in the
deployment's network-policy manifest. Provider-backed Plugins on `ai-ihpan` use
`configured-public`, restricted to public HTTPS and one origin per execution.
Validate changes with `grafy network-policy validate`. Restart the API to load a
changed manifest, then retry promotion through the API container.

For unsupported `postgresql.egress`, configure a permitted PostgreSQL destination
and its broker before promotion. HTTP policy does not grant database access.
Keep SQL inactive when the deployment has no permitted database destination.

After publication, verify the selected revisions, stored runtime artifacts, and
catalog readiness in each affected Workspace. Run a representative graph when
its inputs and credentials are available. Existing saved nodes retain their
exact release pins; promotion does not upgrade those nodes automatically.

Revoke the temporary platform token, remove both credential copies, and stop the
one-shot publisher container. Check that no active token for the operation
remains. Save publication logs, promotion results, and selection records beside
the application deployment log. Keep immutable releases required by saved graphs
or rollback.

## Retire images through the operator

Check the active deployment configuration, retained release records, rollback window, and all runtime hosts before retiring an image. Keep any base image digest that a retained Plugin release can still require. Schedule registry garbage collection only after the operator confirms that no retained tag or manifest references the image.

The deployment has reported `grafy-publisher:local`, `grafy-plugin-base-gdal:local`, and `grafy-plugin-base-gdal2:local` as experiments. This guide does not delete them. The operator owns their retirement after checking host references and rollback needs. Do not use broad Docker image pruning or registry garbage collection as a substitute for that check.
