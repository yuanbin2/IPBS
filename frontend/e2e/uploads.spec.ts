import { chromium, expect, test as playwrightTest, type Page, type Request } from "@playwright/test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const username = "upload-e2e-operator";
const password = "Upload-e2e-only-2026!";
const pngBytes = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGNUrrjDwMDAxAAGABEFAXsZWVM7AAAAAElFTkSuQmCC",
  "base64",
);

const test = playwrightTest.extend<{ page: Page }>({
  browser: [async ({}, use) => {
    const channel = process.env.E2E_BROWSER_CHANNEL as "msedge" | "chrome" | undefined;
    const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
    try {
      await use(browser);
    } finally {
      await browser.close();
    }
  }, { scope: "worker" }],
  page: async ({ browser }, use) => {
    const context = await browser.newContext();
    try {
      await use(await context.newPage());
    } finally {
      await context.close();
    }
  },
});

async function login(page: Page, destination: string) {
  await page.goto(`/login?redirect=${encodeURIComponent(destination)}`);
  await page.getByPlaceholder("用户名").fill(username);
  await page.getByPlaceholder("密码，至少 8 位").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${destination.replaceAll("/", "\\/")}$`));
}

function expectMultipart(request: Request) {
  const contentType = request.headers()["content-type"] ?? "";
  expect(contentType).toMatch(/^multipart\/form-data;\s*boundary=[^;\s]+/i);
}

function expectParsedFields(responseHeaders: Record<string, string>, expected: string[]) {
  expect((responseHeaders["x-e2e-multipart-fields"] ?? "").split(",").sort()).toEqual([...expected].sort());
}

async function serveInstalledVditorAssets(page: Page) {
  const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const packageRoot = resolve(frontendRoot, "node_modules/vditor");
  await page.route(/^https:\/\/unpkg\.com\/vditor@4\.0\.0\/dist\/js\/(?:i18n|icons|lute)\/[\w.-]+\.js(?:\?.*)?$/, async (route) => {
    const requestedPath = new URL(route.request().url()).pathname.split("/vditor@4.0.0/")[1];
    await route.fulfill({ path: resolve(packageRoot, requestedPath) });
  });
}

test("operator uploads a blog image, inserts Markdown, reads it back, and sees validation errors", async ({ page }) => {
  await serveInstalledVditorAssets(page);
  await login(page, "/blog");
  await page.getByRole("button", { name: "写博客", exact: true }).click();
  await expect(page.getByRole("heading", { name: "写新博客" })).toBeVisible();

  const imageInput = page.locator('.vditor-toolbar input[type="file"]');
  await expect(imageInput).toHaveAttribute("accept", "image/*");
  const imageRequestPromise = page.waitForRequest((request) => request.url().includes("/api/agent/blog/images/"));
  const imageResponsePromise = page.waitForResponse((response) => response.url().includes("/api/agent/blog/images/"));
  await imageInput.setInputFiles({ name: "e2e-image.png", mimeType: "image/png", buffer: pngBytes });
  const imageRequest = await imageRequestPromise;
  const imageResponse = await imageResponsePromise;
  expectMultipart(imageRequest);
  expectParsedFields(imageResponse.headers(), ["image"]);
  expect(imageResponse.status()).toBe(201);
  const uploadPayload = await imageResponse.json();
  expect(uploadPayload.url).toMatch(/^\/media\/blog\/[0-9a-f]{32}\.png$/);
  expect(uploadPayload.markdown).toContain(`![e2e-image](${uploadPayload.url})`);

  await expect.poll(async () => {
    const drafts = await page.evaluate(() => Object.keys(localStorage)
      .filter((key) => key.startsWith("blogWriterDraft:v2:"))
      .map((key) => localStorage.getItem(key))
      .filter(Boolean)
      .map((value) => JSON.parse(value!).draft?.content ?? ""));
    return drafts.join("\n");
  }).toContain(`![e2e-image](${uploadPayload.url})`);

  const readResult = await page.evaluate(async (url) => {
    const response = await fetch(url);
    return {
      status: response.status,
      contentType: response.headers.get("content-type"),
      nosniff: response.headers.get("x-content-type-options"),
      bytes: Array.from(new Uint8Array(await response.arrayBuffer())),
    };
  }, uploadPayload.url);
  expect(readResult.status).toBe(200);
  expect(readResult.contentType).toBe("image/png");
  expect(readResult.nosniff).toBe("nosniff");
  expect(Buffer.from(readResult.bytes)).toEqual(pngBytes);

  const invalidRequestPromise = page.waitForRequest((request) => request.url().includes("/api/agent/blog/images/"));
  const invalidResponsePromise = page.waitForResponse((response) => response.url().includes("/api/agent/blog/images/"));
  await imageInput.setInputFiles({
    name: "vector.svg",
    mimeType: "image/svg+xml",
    buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>'),
  });
  const invalidRequest = await invalidRequestPromise;
  const invalidResponse = await invalidResponsePromise;
  expectMultipart(invalidRequest);
  expectParsedFields(invalidResponse.headers(), ["image"]);
  expect(invalidResponse.status()).toBe(400);
  await expect(page.locator(".editor-error")).toContainText(/invalid|unsupported|格式|图片/i);
  await expect(page.locator('.vditor-wysiwyg img[src*="vector.svg"]')).toHaveCount(0);
});

test("operator uploads a supported knowledge document and receives the processed state", async ({ page }) => {
  await login(page, "/knowledge");
  await expect(page.getByRole("heading", { name: "上传文档" })).toBeVisible();

  const fileInput = page.locator(".upload-zone input[type=file]");
  await fileInput.setInputFiles({
    name: "browser-upload.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Browser E2E document. LangGraph controls agent state transitions."),
  });
  const title = `浏览器上传文档 ${Date.now()}`;
  await page.getByPlaceholder("文档标题").fill(title);
  const uploadRequestPromise = page.waitForRequest((request) => request.url().includes("/api/agent/documents/") && request.method() === "POST");
  const uploadResponsePromise = page.waitForResponse((response) => response.url().includes("/api/agent/documents/") && response.request().method() === "POST");
  await page.getByRole("button", { name: "上传并处理" }).click();
  const request = await uploadRequestPromise;
  const response = await uploadResponsePromise;
  expectMultipart(request);
  expectParsedFields(response.headers(), ["file", "title", "knowledge_base_id"]);
  expect(response.status()).toBe(202);
  const payload = await response.json();
  expect(payload.id).toBeTruthy();
  expect(payload.title).toBe(title);
  expect(payload.content_type).toBe("text/plain");
  expect(payload.task_state).toBe("SUCCESS");
  expect(payload.task_result).toBeTruthy();
  await expect(page.locator(".document-card").filter({ hasText: title }).locator(".doc-status-icon.ready")).toBeVisible();
  await expect(page.locator(".document-card").filter({ hasText: title })).toContainText(/\d+ 片段/);
});
