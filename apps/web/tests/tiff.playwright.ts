import { test, expect, type Page, type APIResponse } from "@playwright/test";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";
import type { components } from "../src/lib/api/generated/grafy";

type Schemas = components["schemas"];

async function post(
  page: Page,
  path: string,
  data: unknown,
): Promise<APIResponse> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "grafy_csrf")?.value;
  const response = await page.request.post(`/api/v1${path}`, {
    data,
    headers: {
      Origin: process.env.E2E_STACK_ORIGIN ?? "",
      ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
    },
  });
  expect(
    response.ok(),
    `${path}: ${response.status()} ${await response.text()}`,
  ).toBeTruthy();
  return response;
}

test("real TIFF artifacts on a saved canvas", async ({ page }) => {
  const fixtures = process.env.TIFF_FIXTURE_DIR;
  if (!fixtures || !process.env.E2E_STACK_ORIGIN)
    throw new Error(
      "Set TIFF_FIXTURE_DIR and E2E_STACK_ORIGIN; see docs/how-to-run-e2e.md",
    );
  const evidence = resolve("../../artifacts/e2e-tiff");
  await mkdir(evidence, { recursive: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Continue with SSO" }).click();
  await page.getByRole("textbox", { name: "Username or email" }).fill("owner");
  await page
    .getByRole("textbox", { name: "Password", exact: true })
    .fill("owner");
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(
    page.locator(".grafy-workspace-rail__account-email"),
  ).toContainText("owner@grafy.local");
  const response = await page.request.get("/api/v1/workspaces");
  expect(response.ok()).toBeTruthy();
  const workspaces: Schemas["WorkspaceResponse"][] = await response.json();
  const workspace = workspaces[0];
  if (!workspace) throw new Error("No Workspace after login");
  const base = `/workspaces/${workspace.id}`;
  const project: Schemas["ProjectResponse"] = await (
    await post(page, `${base}/projects`, { name: "TIFF archive demonstration" })
  ).json();
  const projectPath = `${base}/projects/${project.id}`;
  const artifacts: { id: string; filename: string }[] = [];
  for (const filename of [
    "register-rgb.tif",
    "register-gray16.tif",
    "register-pages.tif",
    "register-alpha.tif",
  ]) {
    const bytes = await readFile(resolve(fixtures, filename));
    const target: Schemas["UploadTargetResponse"] = await (
      await post(page, `${base}/uploads`, {
        filename,
        byte_size: bytes.length,
        content_type: "image/tiff",
      })
    ).json();
    const cookies = await page.context().cookies();
    const csrf = cookies.find((cookie) => cookie.name === "grafy_csrf")?.value;
    const upload = await page.request.put(
      target.kind === "api" ? `/api${target.url}` : target.url,
      {
        data: bytes,
        headers: {
          ...target.headers,
          "Content-Type": "image/tiff",
          Origin: process.env.E2E_STACK_ORIGIN ?? "",
          ...(target.kind === "api" && csrf
            ? { "X-CSRF-Token": decodeURIComponent(csrf) }
            : {}),
        },
      },
    );
    expect(upload.ok()).toBeTruthy();
    const item: Schemas["ImageUploadItemResponse"] = await (
      await post(page, `${base}/uploads/${target.upload_id}/complete`, {})
    ).json();
    if (!item.artifact_id) throw new Error(`No artifact for ${filename}`);
    await post(page, `${base}/library/artifacts/from-upload`, {
      artifact_id: item.artifact_id,
      original_filename: filename,
    });
    artifacts.push({ id: item.artifact_id, filename });
  }
  const headResponse = await page.request.get(`/api/v1${projectPath}/head`);
  const head: Schemas["ProjectHeadResponse"] = await headResponse.json();
  await post(page, `${projectPath}/commands`, {
    command_id: randomUUID(),
    room_epoch: head.room_epoch,
    observed_sequence: head.collaboration_sequence,
    commands: [
      {
        kind: "in_graph",
        graph_id: "main",
        command: {
          kind: "replace_presentation",
          presentation: {
            viewers: artifacts.map((artifact, index) => ({
              id: `artifact-viewer-${randomUUID()}`,
              artifact_ref: {
                artifact_id: artifact.id,
                artifact_type: "file.tiff",
                schema_version: 1,
              },
              // Height follows the scan aspect (about 440px with the label), so
              // a tighter row step lets the next card cover this card's zoom bar.
              position: {
                x: (index % 2) * 720,
                y: Math.floor(index / 2) * 640,
              },
              layout: { width: 550, body_height: 360 },
            })),
          },
        },
      },
    ],
  });
  const latest: Schemas["ProjectHeadResponse"] = await (
    await page.request.get(`/api/v1${projectPath}/head`)
  ).json();
  await post(page, `${projectPath}/checkpoints`, {
    expected_room_epoch: latest.room_epoch,
    expected_sequence: latest.collaboration_sequence,
  });
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/image/")) requests.push(request.url());
  });
  const url = `/workspaces/${workspace.slug}/projects/${project.id}`;
  await page.goto(url);
  const views = page.locator("[data-tiff-viewport]");
  await expect(views).toHaveCount(4);
  await expect(page.getByText("Loading image…", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByText("This file cannot be displayed.", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Fit", exact: true }).click();
  const tileUrls = () => requests.filter((url) => url.includes("/tiles/"));
  const initial = requests.slice();
  const first = page.getByRole("region", { name: "register-rgb.tif scan" });
  const zoomIn = first.getByRole("button", { name: "Zoom in", exact: true });
  // One step still shows tiles from the fitted view. Three steps reach a
  // level where a drag across the card has to fetch new tiles.
  for (let step = 0; step < 3; step += 1) {
    const before = tileUrls().length;
    await zoomIn.click();
    await expect.poll(() => tileUrls().length).toBeGreaterThan(before);
  }
  await expect
    .poll(async () => {
      const mark = tileUrls().length;
      await new Promise((resolveQuiet) => setTimeout(resolveQuiet, 500));
      return tileUrls().length === mark;
    })
    .toBe(true);
  await page.screenshot({ path: resolve(evidence, "zoom.png") });
  const zoom = requests.slice(initial.length);
  const box = await first.locator("[data-tiff-viewport]").boundingBox();
  if (!box) throw new Error("No image viewport");
  const tilesBeforePan = tileUrls().length;
  const requestsBeforePan = requests.length;
  await page.mouse.move(box.x + box.width * 0.85, box.y + box.height * 0.35);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.15, box.y + box.height * 0.7, {
    steps: 24,
  });
  await page.mouse.up();
  await expect.poll(() => tileUrls().length).toBeGreaterThan(tilesBeforePan);
  const pan = requests.slice(requestsBeforePan);
  await page.getByRole("button", { name: "Next page", exact: true }).click();
  await expect(page.getByText("Page 2 of 3", { exact: true })).toBeVisible();
  await expect
    .poll(() =>
      requests.some((url) => url.includes("/tiles/") && url.endsWith("page=1")),
    )
    .toBeTruthy();
  await page.screenshot({ path: resolve(evidence, "canvas.png") });
  const denied = await page.request.get(
    `/api/v1/workspaces/${randomUUID()}/artifacts/${artifacts[0]?.id}/image/info`,
  );
  expect([403, 404]).toContain(denied.status());
  await writeFile(
    resolve(evidence, "requests.json"),
    JSON.stringify(
      {
        url: new URL(url, process.env.E2E_STACK_ORIGIN).href,
        initial,
        zoom,
        pan,
        all: requests,
        wrongWorkspaceStatus: denied.status(),
      },
      null,
      2,
    ),
  );
});
