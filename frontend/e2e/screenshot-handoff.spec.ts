/**
 * B-045 截图交接的站内接收路径（mock 扩展）+ 本地 OCR + 私有笔记落库。
 * 真实侧载的采集与跨扩展验收见 browser-extension/README.md 人工步骤与
 * clip-extension.spec.ts 的说明；这里用假扩展驱动 screenshot-v1 协议，
 * OCR 部分（模型加载、wasm 推理）是真实的。
 */

import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const password = "Upload-e2e-only-2026!";
const operator = "upload-e2e-operator";
const nonce = "b".repeat(32);
const fixturesDir = resolve(dirname(fileURLToPath(import.meta.url)), "fixtures");

const tilePng = readFileSync(resolve(fixturesDir, "ocr-zh-article.png"));
const tileBase64 = tilePng.toString("base64");
const tileSha256 = createHash("sha256").update(tilePng).digest("hex");

function shotMeta(overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    meta: {
      kind: "screenshot",
      version: 1,
      mode: "longpage",
      sourceUrl: "https://example.org/article/long-page?utm_source=share",
      titleCandidate: "长页示例文章",
      capturedAt: "2026-10-04T08:00:00.000Z",
      dpr: 1,
      viewport: { width: 760, height: 430 },
      covered: { top: 0, bottom: 430 },
      truncated: false,
      warnings: [],
      tileCount: 1,
      tiles: [{ index: 0, mime: "image/png", bytes: tilePng.length, sha256: tileSha256, width: 760, height: 430, scrollX: 0, scrollY: 0 }],
      totalBytes: tilePng.length,
      ...overrides,
    },
  };
}

async function serveInstalledVditorAssets(page: Page) {
  const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../node_modules/vditor");
  await page.route(/^https:\/\/unpkg\.com\/vditor@4\.0\.0\/dist\/js\/(?:i18n|icons|lute)\/[\w.-]+\.js(?:\?.*)?$/, async (route) => {
    const path = new URL(route.request().url()).pathname.split("/vditor@4.0.0/")[1];
    await route.fulfill({ path: resolve(packageRoot, path) });
  });
}

async function login(page: Page) {
  await page.goto("/login?redirect=%2Fblog");
  await page.getByPlaceholder("用户名").fill(operator);
  await page.getByPlaceholder("密码，至少 8 位").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/blog$/);
}

/** 注入假扩展（须在首次 goto 前调用）；handler 源码在页面上下文执行。 */
async function installFakeScreenshotExtension(page: Page, handlerSource: string) {
  await page.addInitScript(
    ({ source }) => {
      (window as unknown as { __shotCalls?: unknown[] }).__shotCalls = [];
      const calls = (window as unknown as { __shotCalls?: unknown[] }).__shotCalls as unknown[];
      const runtime = {
        sendMessage(extensionId: string, message: unknown, callback: (response: unknown) => void) {
          calls.push(JSON.parse(JSON.stringify(message)));
          const configured = new Function(`return (${source});`)();
          const response = typeof configured === "function" ? configured(message) : configured;
          callback(response);
        },
        lastError: undefined as { message?: string } | undefined,
      };
      (globalThis as unknown as { chrome?: unknown }).chrome = { runtime };
    },
    { source: handlerSource },
  );
}

function singleTileScript(overrides: Record<string, unknown> = {}): string {
  const meta = shotMeta(overrides);
  return `(message) => {
    if (message.type === "blog.screenshot.get-meta") return ${JSON.stringify(meta)};
    if (message.type === "blog.screenshot.get-tile-chunk") return { ok: true, tileIndex: message.tileIndex, chunkIndex: 0, chunkCount: 1, chunk: ${JSON.stringify(tileBase64)} };
    if (message.type === "blog.screenshot.ack") return { ok: true };
    if (message.type === "blog.screenshot.cancel") return { ok: true };
    return { ok: false, code: "wrong_type" };
  }`;
}

test("截图交接 → 本地 OCR → 校对 → 默认保存为私有笔记（含来源）", async ({ page }) => {
  test.setTimeout(300_000);
  await serveInstalledVditorAssets(page);
  await installFakeScreenshotExtension(page, singleTileScript());
  await login(page);
  // fragment 立即清除（登录后已在 /blog，追加 fragment 是同文档导航，
  // 由 hashchange 触发消费）
  await page.goto(`/blog#shot=${nonce}&ext=fakeextension&kind=screenshot`);
  await expect.poll(() => page.evaluate(() => window.location.hash), { timeout: 15_000 }).toBe("");

  const dialog = page.getByRole("dialog", { name: /截图识别为 Markdown/ });
  await expect(dialog).toBeVisible();
  const blocksPane = dialog.locator(".ocr-blocks-pane");
  await expect(blocksPane.locator(".ocr-block-card").first()).toBeVisible({ timeout: 150_000 });
  await expect(dialog.locator(".ocr-preview-body")).toContainText("当网页正文确实显示在屏幕上", { timeout: 30_000 });
  // 单张截图只进行一次本地识别；来源卡保持可核对。
  const sourceCard = dialog.locator(".ocr-source-card");
  await expect(sourceCard).toContainText("长页示例文章");
  await expect(sourceCard).toContainText("example.org/article/long-page");
  // utm 追踪参数不进入来源链接
  expect(await sourceCard.innerText()).not.toContain("utm_source");

  // ack 恰好一次
  const calls = (await page.evaluate(() => (window as unknown as { __shotCalls: Array<{ type: string }> }).__shotCalls)) as Array<{ type: string }>;
  expect(calls.filter((call) => call.type === "blog.screenshot.ack")).toHaveLength(1);

  // 放入私有笔记 → 抽屉草稿 → 保存落库
  await dialog.getByRole("button", { name: "放入私有笔记" }).click();
  const drawer = page.locator(".private-notes-drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("来自网页剪藏的未保存笔记");
  const titleInput = drawer.getByLabel("笔记标题");
  await expect(titleInput).not.toBeEmpty();
  const draftTitle = await titleInput.inputValue();
  await drawer.getByRole("button", { name: "保存私有笔记" }).click();
  // 保存成功后列表刷新，笔记行出现（提示 toast 在抽屉外，不能在 drawer 内找）
  await expect(drawer.locator(".private-note-row").first()).toContainText(draftTitle.slice(0, 10), { timeout: 20_000 });

  // 刷新后能检索到（标题来自识别出的标题块），且来源字段已写入
  await page.reload();
  await page.getByRole("button", { name: "我的笔记", exact: true }).click();
  const drawer2 = page.locator(".private-notes-drawer");
  await expect(drawer2).toBeVisible();
  await drawer2.getByLabel("搜索私有笔记").fill(draftTitle.slice(0, 6));
  await drawer2.getByRole("button", { name: "查找", exact: true }).click();
  await expect(drawer2.locator(".private-note-row").first()).toContainText(draftTitle.slice(0, 6), { timeout: 15_000 });
});

test("可选博客草稿：覆盖需确认，应用后不自动发布", async ({ page }) => {
  test.setTimeout(300_000);
  await serveInstalledVditorAssets(page);
  await installFakeScreenshotExtension(page, singleTileScript());
  await login(page);
  // 先在写作台放入旧草稿内容，验证覆盖确认
  await page.getByRole("button", { name: "写博客", exact: true }).click();
  await expect(page.locator(".vditor-wysiwyg")).toBeVisible();
  await page.locator(".vditor-wysiwyg").click();
  await page.keyboard.type("旧草稿内容，不应被静默覆盖。");
  await page.getByRole("button", { name: "截图识别", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: /截图识别为 Markdown/ });
  await expect(dialog).toBeVisible();
  // 写作台入口是手动上传：用合成截图驱动本地 OCR
  await dialog.locator('input[type="file"]').setInputFiles({
    name: "ocr-zh-article.png",
    mimeType: "image/png",
    buffer: tilePng,
  });
  await expect(dialog.locator(".ocr-blocks-pane .ocr-block-card").first()).toBeVisible({ timeout: 180_000 });

  await dialog.locator(".ocr-target-btn").filter({ hasText: "博客草稿" }).click();
  await dialog.getByRole("button", { name: "应用到博客草稿" }).click();
  // 已有草稿内容 → 必须确认
  const confirmDialog = page.getByRole("dialog", { name: "应用为博客草稿" });
  await expect(confirmDialog).toBeVisible();
  await confirmDialog.getByRole("button", { name: "覆盖草稿" }).click();

  // 内容进入写作台（含来源说明），但绝不自动提交发布
  await expect(page.locator(".vditor-wysiwyg")).toContainText("当网页正文确实显示在屏幕上", { timeout: 15_000 });
  await expect(page.locator(".vditor-wysiwyg")).toContainText("来源：");
  await expect(page.getByRole("button", { name: /发布并加入知识库/ }).first()).toBeVisible();
  // 草稿仍在写作台内，未产生提交动作（没有出现审批/提交成功提示）
  await expect(page.locator(".vditor-wysiwyg")).not.toContainText("旧草稿内容");
});

test("保留插图：裁剪区域上传为私有图片并插入引用", async ({ page }) => {
  test.setTimeout(300_000);
  await serveInstalledVditorAssets(page);
  await installFakeScreenshotExtension(page, singleTileScript());
  await login(page);
  await page.goto(`/blog#shot=${nonce}&ext=fakeextension&kind=screenshot`);
  const dialog = page.getByRole("dialog", { name: /截图识别为 Markdown/ });
  await expect(dialog.locator(".ocr-blocks-pane .ocr-block-card").first()).toBeVisible({ timeout: 180_000 });

  await dialog.getByRole("button", { name: "手动框选页面配图" }).click();
  const cropPane = dialog.locator(".ocr-crop-pane");
  await expect(cropPane).toBeVisible();
  const image = cropPane.locator("img");
  const box = await image.boundingBox();
  expect(box).not.toBeNull();
  // 在图上拖出一个小矩形
  const startX = box!.x + box!.width * 0.1;
  const startY = box!.y + box!.height * 0.1;
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX + box!.width * 0.25, startY + box!.height * 0.2, { steps: 5 });
  await page.mouse.up();
  let uploadAttempts = 0;
  await page.route("**/api/agent/blog/notes/images/", async (route) => {
    if (route.request().method() === "POST" && uploadAttempts++ === 0) {
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "模拟上传暂时失败" }) });
    } else {
      await route.continue();
    }
  });
  const imageResponses: Array<{ url: string; status: number }> = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/agent/blog/notes/images")) {
      imageResponses.push({ url: response.url(), status: response.status() });
    }
  });
  await dialog.getByRole("button", { name: "上传为私有图片" }).click();
  await expect(page.locator(".el-message--error").filter({ hasText: "模拟上传暂时失败" })).toBeVisible();
  await expect(dialog.locator(".ocr-crop-pane")).toBeVisible();
  await expect(dialog.locator(".ocr-crop-rect")).toBeVisible();
  await expect(dialog.getByLabel("当前图片裁剪预览")).toBeVisible();
  expect(uploadAttempts).toBe(1);
  // Failure stays on the same crop; a second click retries the existing verified preview.
  await dialog.getByRole("button", { name: "上传为私有图片" }).click();

  // 上传 + 读回成功后，校对区出现私有图片引用块
  const referenceBlock = dialog.locator(".ocr-block-card").filter({ hasText: "私有图片引用" });
  await expect(referenceBlock).toBeVisible({ timeout: 30_000 });
  expect(imageResponses.some((response) => response.status === 201)).toBe(true);
  expect(imageResponses.some((response) => response.status === 200)).toBe(true);
  await expect(dialog.locator(".ocr-preview-body img")).toBeVisible({ timeout: 15_000 });
  // 预览中的图片必须走私有读回接口，而不是公开 /media 地址
  const reference = await referenceBlock.locator("textarea").inputValue();
  expect(reference).toContain("/api/agent/blog/notes/images/");
  expect(reference.startsWith("![截图插图](")).toBe(true);
});

test("博客草稿插图使用博客媒体；改存私有笔记时自动重存图片", async ({ page }) => {
  test.setTimeout(300_000);
  await serveInstalledVditorAssets(page);
  await installFakeScreenshotExtension(page, singleTileScript({
    tiles: [{ index: 0, mime: "image/png", bytes: tilePng.length, sha256: tileSha256, width: 760, height: 430, scrollX: 0, scrollY: 0,
      imageCandidates: [{ x: 0.1, y: 0.1, width: 0.25, height: 0.2 }] }],
  }));
  await login(page);
  await page.goto(`/blog#shot=${nonce}&ext=fakeextension&kind=screenshot`);
  const dialog = page.getByRole("dialog", { name: /截图识别为 Markdown/ });
  await expect(dialog.locator(".ocr-block-card").first()).toBeVisible({ timeout: 180_000 });
  await dialog.locator(".ocr-target-btn").filter({ hasText: "博客草稿" }).click();
  await expect(dialog).toContainText("发现 1 处可见网页图片候选");
  await dialog.getByRole("button", { name: "保留视口 1 的配图候选 1" }).click();
  await expect(dialog.locator(".ocr-crop-rect")).toBeVisible();
  const imageBox = await dialog.locator(".ocr-crop-pane img").boundingBox();
  const selectedBox = await dialog.locator(".ocr-crop-rect").boundingBox();
  expect(imageBox).not.toBeNull();
  expect(selectedBox).not.toBeNull();
  expect(Math.abs(selectedBox!.x - (imageBox!.x + imageBox!.width * 0.1))).toBeLessThan(5);
  expect(Math.abs(selectedBox!.y - (imageBox!.y + imageBox!.height * 0.1))).toBeLessThan(5);
  await expect(dialog.getByLabel("当前图片裁剪预览")).toBeVisible();
  await expect(dialog.getByText("系统推荐区域的实际裁剪预览")).toBeVisible();
  await dialog.getByRole("button", { name: "重新框选覆盖推荐范围" }).click();
  await expect(dialog.locator(".ocr-crop-rect")).toHaveCount(0);
  await page.mouse.move(imageBox!.x + imageBox!.width * 0.4, imageBox!.y + imageBox!.height * 0.4);
  await page.mouse.down();
  await page.mouse.move(imageBox!.x + imageBox!.width * 0.7, imageBox!.y + imageBox!.height * 0.7, { steps: 5 });
  await page.mouse.up();
  await expect(dialog.getByText("你重新框选的实际裁剪预览")).toBeVisible();
  const uploads: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/agent/blog/")) uploads.push(request.url());
  });
  await dialog.getByRole("button", { name: "上传为博客图片" }).click();
  const referenceBlock = dialog.locator(".ocr-block-card").filter({ hasText: "博客图片引用" });
  await expect(referenceBlock).toBeVisible({ timeout: 30_000 });
  const reference = await referenceBlock.locator("textarea").inputValue();
  expect(reference).toContain("/media/blog/");
  expect(uploads.some((url) => url.endsWith("/api/agent/blog/images/"))).toBe(true);
  expect(uploads.some((url) => url.includes("/api/agent/blog/notes/images/"))).toBe(false);

  await dialog.locator(".ocr-target-btn").filter({ hasText: "私有笔记" }).click();
  await dialog.getByRole("button", { name: "放入私有笔记" }).click();
  const drawer = page.locator(".private-notes-drawer");
  await expect(drawer).toBeVisible();
  expect(uploads.some((url) => url.endsWith("/api/agent/blog/notes/images/"))).toBe(true);
  let savedContent = "";
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/agent/blog/notes/")) {
      savedContent = (request.postDataJSON() as { content?: string }).content ?? "";
    }
  });
  await drawer.getByRole("button", { name: "保存私有笔记" }).click();
  await expect.poll(() => savedContent).toContain("/api/agent/blog/notes/images/");
  expect(savedContent).not.toContain("/media/blog/");
});

test("系统框好的图片区域可直接确认并上传，无需重新框选", async ({ page }) => {
  test.setTimeout(300_000);
  await serveInstalledVditorAssets(page);
  await installFakeScreenshotExtension(page, singleTileScript({
    tiles: [{ index: 0, mime: "image/png", bytes: tilePng.length, sha256: tileSha256,
      width: 760, height: 430, scrollX: 0, scrollY: 0,
      imageCandidates: [{ x: 0.1, y: 0.1, width: 0.25, height: 0.2 }] }],
  }));
  await login(page);
  await page.goto(`/blog#shot=${nonce}&ext=fakeextension&kind=screenshot`);
  const dialog = page.getByRole("dialog", { name: /截图识别为 Markdown/ });
  await expect(dialog.locator(".ocr-block-card").first()).toBeVisible({ timeout: 180_000 });
  await dialog.getByRole("button", { name: "保留视口 1 的配图候选 1" }).click();
  await expect(dialog.getByText("系统推荐区域的实际裁剪预览")).toBeVisible();
  await expect(dialog.locator(".ocr-crop-rect")).toBeVisible();
  await dialog.getByRole("button", { name: "上传为私有图片" }).click();
  await expect(dialog.locator(".ocr-block-card").filter({ hasText: "私有图片引用" })).toBeVisible({ timeout: 30_000 });
});

test("私有插图转博客草稿先确认公开存储；取消不上传，确认后自动替换图片引用", async ({ page }) => {
  test.setTimeout(300_000);
  await serveInstalledVditorAssets(page);
  await installFakeScreenshotExtension(page, singleTileScript());
  await login(page);
  await page.goto(`/blog#shot=${nonce}&ext=fakeextension&kind=screenshot`);
  const dialog = page.getByRole("dialog", { name: /截图识别为 Markdown/ });
  await expect(dialog.locator(".ocr-block-card").first()).toBeVisible({ timeout: 180_000 });
  await dialog.getByRole("button", { name: "手动框选页面配图" }).click();
  const box = await dialog.locator(".ocr-crop-pane img").boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width * 0.1, box!.y + box!.height * 0.1);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width * 0.35, box!.y + box!.height * 0.3, { steps: 5 });
  await page.mouse.up();
  await dialog.getByRole("button", { name: "上传为私有图片" }).click();
  await expect(dialog.locator(".ocr-block-card").filter({ hasText: "私有图片引用" })).toBeVisible({ timeout: 30_000 });

  const publicUploads: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/agent/blog/images/")) publicUploads.push(request.url());
  });
  await dialog.locator(".ocr-target-btn").filter({ hasText: "博客草稿" }).click();
  await dialog.getByRole("button", { name: "应用到博客草稿" }).click();
  const confirm = page.getByRole("dialog", { name: "转换插图存储" });
  await expect(confirm).toContainText("可通过图片地址访问");
  await confirm.getByRole("button", { name: "取消" }).click();
  expect(publicUploads).toHaveLength(0);
  await expect(dialog).toBeVisible();

  const privateImageText = dialog.locator(".ocr-block-card").filter({ hasText: "私有图片引用" }).locator("textarea");
  const originalReference = await privateImageText.inputValue();
  await privateImageText.fill(originalReference.replace(/\/notes\/images\/\d+\//, "/notes/images/999999/"));
  await dialog.getByRole("button", { name: "应用到博客草稿" }).click();
  await expect(page.getByText("正文包含无法自动转换的图片地址，请在当前目标重新插入这些图片")).toBeVisible();
  expect(publicUploads).toHaveLength(0);
  await privateImageText.fill(originalReference);

  let failNextUpload = true;
  await page.route("**/api/agent/blog/images/", async (route) => {
    if (failNextUpload) {
      failNextUpload = false;
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "模拟图片存储不可用" }) });
    } else {
      await route.continue();
    }
  });
  await dialog.getByRole("button", { name: "应用到博客草稿" }).click();
  await confirm.getByRole("button", { name: "转换并继续" }).click();
  await expect(dialog).toBeVisible();
  await expect(dialog.locator(".ocr-block-card").filter({ hasText: "私有图片引用" })).toBeVisible();
  await expect(page.getByText("模拟图片存储不可用")).toBeVisible();

  await dialog.getByRole("button", { name: "应用到博客草稿" }).click();
  await confirm.getByRole("button", { name: "转换并继续" }).click();
  await expect(page.locator(".vditor-wysiwyg")).toBeVisible({ timeout: 20_000 });
  await expect.poll(() => publicUploads.length).toBe(2);
  expect(await page.locator(".vditor-wysiwyg").first().innerHTML()).toContain("/media/blog/");
  expect(await page.locator(".vditor-wysiwyg").first().innerHTML()).not.toContain("/api/agent/blog/notes/images/");
});

test("跨屏图片候选在拼接长图上合并为一个候选框", async ({ page }) => {
  test.setTimeout(300_000);
  await serveInstalledVditorAssets(page);
  // 同一张网页图片（稳定 key "7"）跨两个视口：视口 0 露出下段，视口 1 露出上段。
  const meta = shotMeta({
    tileCount: 2,
    totalBytes: tilePng.length * 2,
    covered: { top: 0, bottom: 860 },
    selection: { left: 0.1, right: 0.9, top: 0, bottom: 860 },
    tiles: [
      { index: 0, mime: "image/png", bytes: tilePng.length, sha256: tileSha256, width: 760, height: 430, scrollX: 0, scrollY: 0,
        imageCandidates: [{ key: "7", x: 0.2, y: 0.6, width: 0.3, height: 0.4 }] },
      { index: 1, mime: "image/png", bytes: tilePng.length, sha256: tileSha256, width: 760, height: 430, scrollX: 0, scrollY: 430,
        imageCandidates: [{ key: "7", x: 0.2, y: 0, width: 0.3, height: 0.3 }] },
    ],
  });
  const script = `(message) => {
    if (message.type === "blog.screenshot.get-meta") return ${JSON.stringify(meta)};
    if (message.type === "blog.screenshot.get-tile-chunk") return { ok: true, tileIndex: message.tileIndex, chunkIndex: 0, chunkCount: 1, chunk: ${JSON.stringify(tileBase64)} };
    if (message.type === "blog.screenshot.ack") return { ok: true };
    return { ok: false, code: "wrong_type" };
  }`;
  await installFakeScreenshotExtension(page, script);
  await login(page);
  await page.goto(`/blog#shot=${nonce}&ext=fakeextension&kind=screenshot`);
  const dialog = page.getByRole("dialog", { name: /截图识别为 Markdown/ });
  await expect(dialog.locator(".ocr-stitched img")).toBeVisible({ timeout: 150_000 });
  // 同 key 跨屏图片只应出现一个合并后的候选框，而不是每个视口各一个
  const stitchedCandidates = dialog.locator(".ocr-stitched .ocr-image-candidate");
  await expect(stitchedCandidates).toHaveCount(1);
  // 合并框应覆盖页面 y 258–559（归一化 0.30–0.65）；裁剪横向选区后只断言纵向比例
  const boxStyle = await stitchedCandidates.first().evaluate((element: HTMLElement) => ({
    top: element.style.top, height: element.style.height,
  }));
  expect(parseFloat(boxStyle.top)).toBeGreaterThan(28);
  expect(parseFloat(boxStyle.top)).toBeLessThan(32);
  expect(parseFloat(boxStyle.height)).toBeGreaterThan(33);
  expect(parseFloat(boxStyle.height)).toBeLessThan(37);
  const sourcePosition = async () => page.evaluate(() => {
    const pane = document.querySelector<HTMLElement>(".ocr-image-pane")!;
    const image = pane.querySelector<HTMLImageElement>(".ocr-stitched img")!;
    const anchor = pane.getBoundingClientRect().top + pane.clientHeight * 0.25;
    const rect = image.getBoundingClientRect();
    return Math.max(0, Math.min(1, (anchor - rect.top) / rect.height)) * image.naturalHeight;
  });
  await stitchedCandidates.first().scrollIntoViewIfNeeded();
  await dialog.locator(".ocr-image-pane").evaluate((pane) => { pane.scrollTop = Math.min(35, pane.scrollHeight - pane.clientHeight); });
  await stitchedCandidates.first().scrollIntoViewIfNeeded();
  const positionBeforeCrop = await sourcePosition();
  await stitchedCandidates.first().click();
  await expect(dialog.locator(".ocr-crop-rect")).toBeVisible();
  await expect(dialog.getByText("系统推荐区域的实际裁剪预览")).toBeVisible();
  await expect(dialog.getByLabel("当前图片裁剪预览")).toBeVisible();
  await dialog.getByRole("button", { name: "返回校对" }).click();
  await expect.poll(async () => Math.abs(await sourcePosition() - positionBeforeCrop), { timeout: 10_000 }).toBeLessThan(35);
  await stitchedCandidates.first().scrollIntoViewIfNeeded();
  await stitchedCandidates.first().click();
  await expect(dialog.getByLabel("当前图片裁剪预览")).toBeVisible();
  const previewBytes = await dialog.getByLabel("当前图片裁剪预览").locator("img").evaluate(async (image: HTMLImageElement) => {
    const response = await fetch(image.src);
    const blob = await response.blob();
    const bytes = new Uint8Array(await blob.arrayBuffer());
    const bitmap = await createImageBitmap(blob);
    const size = [bitmap.width, bitmap.height];
    bitmap.close();
    return { bytes: Array.from(bytes), size };
  });
  expect(previewBytes.size[0]).toBeGreaterThan(8);
  let uploadedFigure: Buffer | null = null;
  await page.route("**/api/agent/blog/notes/images/", async (route) => {
    const request = route.request();
    const body = request.postDataBuffer();
    const contentType = request.headers()["content-type"] ?? "";
    const boundary = contentType.match(/boundary=(?:"([^"]+)"|([^;]+))/)?.slice(1).find(Boolean);
    if (body && boundary) {
      const headerAt = body.indexOf(Buffer.from('name="image"'));
      const dataAt = body.indexOf(Buffer.from("\r\n\r\n"), headerAt) + 4;
      const endAt = body.indexOf(Buffer.from(`\r\n--${boundary}`), dataAt);
      if (headerAt >= 0 && dataAt >= 4 && endAt >= dataAt) uploadedFigure = body.subarray(dataAt, endAt);
    }
    await route.continue();
  });
  await dialog.getByRole("button", { name: "上传为私有图片" }).click();
  await expect(dialog.locator(".ocr-block-card").filter({ hasText: "私有图片引用" })).toBeVisible({ timeout: 30_000 });
  expect(uploadedFigure).not.toBeNull();
  expect(Array.from(uploadedFigure!)).toEqual(previewBytes.bytes);
  const positionAfterUpload = await sourcePosition();
  expect(Math.abs(positionAfterUpload - positionBeforeCrop)).toBeLessThan(30);
  const imageReferenceCard = dialog.locator(".ocr-block-card").filter({ hasText: "私有图片引用" });
  const rightPaneBox = await dialog.locator(".ocr-blocks-pane").boundingBox();
  const referenceBox = await imageReferenceCard.boundingBox();

  expect(rightPaneBox).not.toBeNull(); expect(referenceBox).not.toBeNull();
  expect(Math.abs(referenceBox!.y - rightPaneBox!.y - rightPaneBox!.height * 0.25)).toBeLessThan(36);
  // Upload success returns to review automatically; inspect the same stitched
  // source after confirming preview bytes matched the uploaded multipart file.
  // 提示计数按唯一 key 去重：两张视口各报一次的同一张图只算 1 处
  await expect(dialog).toContainText("发现 1 处可见网页图片候选");
  // 逐屏视图仍保留各自视口内的分片候选，便于单独微调
  const beforeTileView = await sourcePosition();
  await dialog.getByRole("button", { name: "查看逐屏定位" }).click();
  await expect.poll(async () => Math.abs(await dialog.locator(".ocr-image-pane").evaluate((pane) => pane.scrollTop))).toBeGreaterThan(0);
  await expect(dialog.locator(".ocr-tile:not(.ocr-stitched) .ocr-image-candidate")).toHaveCount(2);
  const tilePosition = await dialog.locator(".ocr-image-pane").evaluate((pane) => {
    const anchor = pane.getBoundingClientRect().top + pane.clientHeight * 0.25;
    const figures = [...pane.querySelectorAll<HTMLElement>(".ocr-tile:not(.ocr-stitched)")];
    const figure = figures.find((item) => { const r = item.querySelector("img")!.getBoundingClientRect(); return r.top <= anchor && r.bottom >= anchor; })!;
    const img = figure.querySelector<HTMLImageElement>("img")!; const r = img.getBoundingClientRect();
    return Number(figure.dataset.tileIndex) * 430 + Math.max(0, Math.min(1, (anchor - r.top) / r.height)) * img.naturalHeight;
  });
  expect(Math.abs(tilePosition - beforeTileView)).toBeLessThan(75);
  await dialog.getByRole("button", { name: "收起逐屏定位" }).click();
  expect(Math.abs(await sourcePosition() - beforeTileView)).toBeLessThan(75);
});

test("长页双 tile 先拼图，再仅对最终长图调用一次 OCR", async ({ page }) => {
  test.setTimeout(300_000);
  await serveInstalledVditorAssets(page);
  await page.addInitScript(() => {
    (window as unknown as { __ocrRecognizeCount?: number }).__ocrRecognizeCount = 0;
    const original = Worker.prototype.postMessage;
    Worker.prototype.postMessage = function (message: unknown, options?: StructuredSerializeOptions | Transferable[]) {
      if ((message as { type?: string } | null)?.type === "recognize") {
        (window as unknown as { __ocrRecognizeCount: number }).__ocrRecognizeCount += 1;
      }
      return original.call(this, message, options ?? []);
    };
  });
  const meta = shotMeta({
    tileCount: 2,
    totalBytes: tilePng.length * 2,
    covered: { top: 0, bottom: 860 },
    selection: { left: 0.1, right: 0.9, top: 0, bottom: 860 },
    tiles: [
      { index: 0, mime: "image/png", bytes: tilePng.length, sha256: tileSha256, width: 760, height: 430, scrollX: 0, scrollY: 0 },
      { index: 1, mime: "image/png", bytes: tilePng.length, sha256: tileSha256, width: 760, height: 430, scrollX: 0, scrollY: 430 },
    ],
  });
  const script = `(message) => {
    if (message.type === "blog.screenshot.get-meta") return ${JSON.stringify(meta)};
    if (message.type === "blog.screenshot.get-tile-chunk") return { ok: true, tileIndex: message.tileIndex, chunkIndex: 0, chunkCount: 1, chunk: ${JSON.stringify(tileBase64)} };
    if (message.type === "blog.screenshot.ack") return { ok: true };
    return { ok: false, code: "wrong_type" };
  }`;
  await installFakeScreenshotExtension(page, script);
  await login(page);
  await page.goto(`/blog#shot=${nonce}&ext=fakeextension&kind=screenshot`);
  const dialog = page.getByRole("dialog", { name: /截图识别为 Markdown/ });
  await expect(dialog.locator(".ocr-stitched img")).toBeVisible({ timeout: 150_000 });
  const stitchedHeight = await dialog.locator(".ocr-stitched img").evaluate((image: HTMLImageElement) => image.naturalHeight);
  expect(stitchedHeight).toBe(860);
  await dialog.getByRole("button", { name: "查看逐屏定位" }).click();
  await expect(dialog.locator(".ocr-tile:not(.ocr-stitched)")).toHaveCount(2);
  await expect(dialog).toContainText("对长图进行一次本地 OCR", { timeout: 30_000 });
  // 整图一次 OCR 的 WASM 推理在低配设备上超过默认 8 秒等待
  await expect(dialog.locator(".ocr-block-card").first()).toBeVisible({ timeout: 90_000 });
  expect(await page.evaluate(() => (window as unknown as { __ocrRecognizeCount: number }).__ocrRecognizeCount)).toBe(1);
  await expect(dialog.locator(".ocr-stitched .ocr-block-overlay").first()).toBeVisible();
});

test("长页横向选区交接后显示可下载拼接图，并可从整图框选配图", async ({ page }) => {
  test.setTimeout(300_000);
  await serveInstalledVditorAssets(page);
  await installFakeScreenshotExtension(page, singleTileScript({
    selection: { left: 0.1, right: 0.9, top: 0, bottom: 430 },
  }));
  await login(page);
  await page.goto(`/blog#shot=${nonce}&ext=fakeextension&kind=screenshot`);
  const dialog = page.getByRole("dialog", { name: /截图识别为 Markdown/ });
  const stitched = dialog.locator(".ocr-stitched img");
  await expect(stitched).toBeVisible({ timeout: 180_000 });
  const dimensions = await stitched.evaluate((image: HTMLImageElement) => ({ width: image.naturalWidth, height: image.naturalHeight }));
  expect(dimensions).toEqual({ width: 608, height: 430 });
  await expect(dialog.getByRole("button", { name: "下载拼接长图" })).toBeVisible();
  await dialog.getByRole("button", { name: "手动框选页面配图" }).click();
  const cropImage = dialog.locator(".ocr-crop-long img");
  await expect(cropImage).toBeVisible();
  const imageBox = await cropImage.boundingBox();
  expect(imageBox).not.toBeNull();
  await page.mouse.click(imageBox!.x + 30, imageBox!.y + 30);
  await page.mouse.click(imageBox!.x + 150, imageBox!.y + 120);
  await expect(dialog.locator(".ocr-crop-rect")).toBeVisible();
});

test("校验失败路径：签名不符拒绝且不发 ack", async ({ page }) => {
  test.setTimeout(120_000);
  await serveInstalledVditorAssets(page);
  const fakeBytes = Buffer.from("this is not an image at all........");
  const script = `(message) => {
    if (message.type === "blog.screenshot.get-meta") return ${JSON.stringify(
      shotMeta({ tiles: [{ index: 0, mime: "image/png", bytes: fakeBytes.length, sha256: createHash("sha256").update(fakeBytes).digest("hex"), width: 10, height: 10, scrollX: 0, scrollY: 0 }], totalBytes: fakeBytes.length }),
    )};
    if (message.type === "blog.screenshot.get-tile-chunk") return { ok: true, tileIndex: 0, chunkIndex: 0, chunkCount: 1, chunk: ${JSON.stringify(fakeBytes.toString("base64"))} };
    if (message.type === "blog.screenshot.ack") return { ok: true };
    if (message.type === "blog.screenshot.cancel") return { ok: true };
    return { ok: false, code: "wrong_type" };
  }`;
  await installFakeScreenshotExtension(page, script);
  await login(page);
  await page.goto(`/blog#shot=${nonce}&ext=fakeextension&kind=screenshot`);
  await expect(page.locator(".el-alert__title").getByText("不是声明的 image/png 文件，已拒绝")).toBeVisible({ timeout: 20_000 });
  const calls = (await page.evaluate(() => (window as unknown as { __shotCalls: Array<{ type: string }> }).__shotCalls)) as Array<{ type: string }>;
  expect(calls.filter((call) => call.type === "blog.screenshot.ack")).toHaveLength(0);
  expect(calls.filter((call) => call.type === "blog.screenshot.cancel")).toHaveLength(1);
});

test("畸形长截图选区拒绝交接，不静默识别整屏", async ({ page }) => {
  await installFakeScreenshotExtension(page, singleTileScript({
    selection: { left: -0.1, right: 0.9, top: 0, bottom: 430 },
  }));
  await login(page);
  await page.goto(`/blog#shot=${nonce}&ext=fakeextension&kind=screenshot`);
  await expect(page.locator(".el-alert__title").getByText("长截图选区信息异常，请从扩展重新截取")).toBeVisible();
  const types = await page.evaluate(() => ((window as unknown as { __shotCalls?: Array<{ type: string }> }).__shotCalls ?? []).map((call) => call.type));
  expect(types).toContain("blog.screenshot.cancel");
  expect(types).not.toContain("blog.screenshot.ack");
});

test("过期 nonce 给出明确错误", async ({ page }) => {
  test.setTimeout(120_000);
  await serveInstalledVditorAssets(page);
  const script = `(message) => {
    if (message.type === "blog.screenshot.get-meta") return { ok: false, code: "expired", detail: "截图交接已过期，请从扩展重新发送" };
    return { ok: false, code: "wrong_type" };
  }`;
  await installFakeScreenshotExtension(page, script);
  await login(page);
  await page.goto(`/blog#shot=${nonce}&ext=fakeextension&kind=screenshot`);
  await expect(page.locator(".el-alert__title").getByText("截图交接已过期，请从扩展重新发送")).toBeVisible({ timeout: 20_000 });
  const dialog = page.getByRole("dialog", { name: /截图识别为 Markdown/ });
  await expect(dialog).toHaveCount(0);
});
