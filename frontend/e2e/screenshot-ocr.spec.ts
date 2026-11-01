/**
 * B-045 阶段A E2E：本地截图 → 浏览器 OCR → 左图右文校对 → Markdown 预览/下载。
 * 用合成 PNG fixture（仓库自制，无版权问题）验证真实浏览器内的完整链路；
 * 模型/wasm 从本站同源 public/ 路径加载，断言零第三方 OCR 请求。
 */
import { expect, test, type Locator, type Page } from "@playwright/test";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const fixturesDir = resolve(dirname(fileURLToPath(import.meta.url)), "fixtures");

async function serveInstalledVditorAssets(page: Page) {
  const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../node_modules/vditor");
  await page.route(/^https:\/\/unpkg\.com\/vditor@4\.0\.0\/dist\/js\/(?:i18n|icons|lute)\/[\w.-]+\.js(?:\?.*)?$/, async (route) => {
    const path = new URL(route.request().url()).pathname.split("/vditor@4.0.0/")[1];
    await route.fulfill({ path: resolve(packageRoot, path) });
  });
}

async function loginAndOpenWriter(page: Page) {
  await page.goto("/login?redirect=%2Fblog");
  await page.getByPlaceholder("用户名").fill("upload-e2e-operator");
  await page.getByPlaceholder("密码，至少 8 位").fill("Upload-e2e-only-2026!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/blog$/);
  await page.getByRole("button", { name: "写博客", exact: true }).click();
  await expect(page.locator(".vditor-wysiwyg")).toBeVisible();
}

async function openScreenshotDialog(page: Page) {
  await page.getByRole("button", { name: "截图识别", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: /截图识别为 Markdown/ });
  await expect(dialog).toBeVisible();
  return dialog;
}

test("真实文件上传会逐段显示 OCR 草稿且后续分段不覆盖用户编辑", async ({ page }) => {
  test.setTimeout(360_000);
  await serveInstalledVditorAssets(page);
  await loginAndOpenWriter(page);
  const dialog = await openScreenshotDialog(page);
  const base = await readFile(resolve(fixturesDir, "ocr-zh-article.png"));
  const longPng = await page.evaluate(async (base64) => {
    const binary = atob(base64); const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    const image = new Image(); image.src = URL.createObjectURL(new Blob([bytes], { type: "image/png" })); await image.decode();
    const canvas = document.createElement("canvas"); canvas.width = image.naturalWidth; canvas.height = 5_200;
    const context = canvas.getContext("2d")!; context.fillStyle = "#fff"; context.fillRect(0, 0, canvas.width, canvas.height);
    for (let y = 0; y < canvas.height; y += image.naturalHeight) context.drawImage(image, 0, y);
    URL.revokeObjectURL(image.src);
    return canvas.toDataURL("image/png").split(",")[1]!;
  }, base.toString("base64"));
  await dialog.locator('input[type="file"]').setInputFiles({
    name: "progressive-ocr-long.png", mimeType: "image/png", buffer: Buffer.from(longPng, "base64"),
  });
  const uploadedAt = Date.now();
  const blocksPane = dialog.locator(".ocr-blocks-pane");
  await expect(blocksPane.locator(".ocr-block-card").first()).toBeVisible({ timeout: 90_000 });
  await expect(blocksPane.locator(".ocr-progress-inline")).toBeVisible();
  const firstDisplayMs = Date.now() - uploadedAt;
  const firstInput = blocksPane.locator(".ocr-block-card").first().locator("textarea");
  const firstText = await firstInput.inputValue();
  await firstInput.fill(`${firstText} manual-check`);
  await expect(blocksPane.locator(".ocr-progress-inline")).toBeVisible();
  await expect(blocksPane.locator(".ocr-progress-inline")).toBeHidden({ timeout: 240_000 });
  await expect(firstInput).toHaveValue(`${firstText} manual-check`);
  console.log(`OCR_PROGRESSIVE_SYNTHETIC firstDisplayMs=${firstDisplayMs} fullUiMs=${Date.now() - uploadedAt} blocks=${await blocksPane.locator(".ocr-block-card").count()}`);
  page.on("dialog", (confirm) => void confirm.accept());
  await dialog.locator(".el-dialog__headerbtn").click();
  await expect(dialog).toBeHidden();

  // Closing while a second long-image OCR is active terminates its worker. A new
  // upload must receive only its own result, never late rows from the canceled run.
  await page.getByRole("button", { name: "截图识别", exact: true }).click();
  await expect(dialog).toBeVisible();
  await dialog.locator('input[type="file"]').setInputFiles({
    name: "cancelled-long.png", mimeType: "image/png", buffer: Buffer.from(longPng, "base64"),
  });
  await expect(dialog.locator(".ocr-blocks-pane .ocr-block-card").first()).toBeVisible({ timeout: 90_000 });
  await expect(dialog.locator(".ocr-blocks-pane .ocr-progress-inline")).toBeVisible();
  await dialog.locator(".el-dialog__headerbtn").click();
  await expect(dialog).toBeHidden();
  await page.getByRole("button", { name: "截图识别", exact: true }).click();
  await expect(dialog).toBeVisible();
  await dialog.locator('input[type="file"]').setInputFiles({ name: "ocr-zh-article.png", mimeType: "image/png", buffer: base });
  await expect(dialog.locator(".ocr-preview-body")).toContainText("当网页正文确实显示在屏幕上", { timeout: 150_000 });
  await expect(dialog.locator(".ocr-blocks-pane .ocr-progress-inline")).toBeHidden({ timeout: 150_000 });
  await dialog.locator(".el-dialog__headerbtn").click();
});

test("本地截图经 OCR 校对后可预览与下载，伪装图片被拒绝，零第三方 OCR 请求", async ({ page }) => {
  test.setTimeout(300_000);
  const thirdPartyRequests: string[] = [];
  page.on("request", (request) => {
    // 与当前页面同源（本站 dev server）之外的一切 http(s) 资源都记录下来；
    // about:blank 阶段的初始导航跳过。
    if (!/^https?:/.test(page.url())) return;
    const url = new URL(request.url());
    if (/^https?:/.test(request.url()) && url.origin !== new URL(page.url()).origin) {
      thirdPartyRequests.push(request.url());
    }
  });

  await serveInstalledVditorAssets(page);
  await loginAndOpenWriter(page);
  const dialog = await openScreenshotDialog(page);

  // 1) SVG/HTML 冒充 PNG 必须被签名校验拒绝
  const fakePng = Buffer.from("<html><body>not an image</body></html>", "utf8");
  await dialog.locator('input[type="file"]').setInputFiles({ name: "fake.png", mimeType: "image/png", buffer: fakePng });
  await expect(dialog.getByText("只支持 PNG/JPEG/WebP 截图")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "重新识别刚才的截图" })).toBeVisible();
  const sourceDownloadPromise = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "下载源图 1" }).click();
  const sourceDownload = await sourceDownloadPromise;
  expect(sourceDownload.suggestedFilename()).toBe("fake.png");
  expect(await readFile(await sourceDownload.path())).toEqual(fakePng);
  await dialog.getByRole("button", { name: "重新识别刚才的截图" }).click();
  await expect(dialog.getByText("只支持 PNG/JPEG/WebP 截图")).toBeVisible();

  // 2) 真实合成截图 → OCR → 校对区出现识别块（el-input 的值不在 innerText 里，
  //    文本断言一律走渲染后的预览区或 inputValue）
  const zhBytes = await readFile(resolve(fixturesDir, "ocr-zh-article.png"));
  await dialog.locator('input[type="file"]').setInputFiles({ name: "ocr-zh-article.png", mimeType: "image/png", buffer: zhBytes });
  const blocksPane = dialog.locator(".ocr-blocks-pane");
  await expect(blocksPane.locator(".ocr-block-card").first()).toBeVisible({ timeout: 150_000 });
  const preview = dialog.locator(".ocr-preview-body");
  await expect(preview).toContainText("当网页正文确实显示在屏幕上", { timeout: 30_000 });
  // 左侧源图与块覆盖层可见
  await expect(dialog.locator(".ocr-image-wrap img")).toBeVisible();
  await expect(dialog.locator(".ocr-block-overlay").first()).toBeVisible();

  // 3) 编辑：改文字后预览同步；删除块生效
  const firstCard = blocksPane.locator(".ocr-block-card").first();
  const firstTextarea = firstCard.locator("textarea");
  const originalText = await firstTextarea.inputValue();
  await firstTextarea.fill(`${originalText}（校对补充）`);
  await expect(preview).toContainText("（校对补充）");
  const cardCount = await blocksPane.locator(".ocr-block-card").count();
  await blocksPane.locator(".ocr-block-card").last().getByRole("button", { name: "删除" }).click();
  await expect(blocksPane.locator(".ocr-block-card")).toHaveCount(cardCount - 1);

  // 站内导航走 Vue 路由守卫；弹窗遮挡导航栏时模拟用户快捷导航的点击事件。
  const reviewUrl = page.url();
  let routePrompt = false;
  page.once("dialog", async (confirm) => {
    routePrompt = true;
    expect(confirm.type()).toBe("confirm");
    await confirm.dismiss();
  });
  await page.locator('a[href="/chat"]').first().evaluate((link: HTMLAnchorElement) => link.click());
  await expect.poll(() => routePrompt).toBe(true);
  expect(page.url()).toBe(reviewUrl);
  await expect(preview).toContainText("（校对补充）");

  // 4) 下载 .md
  const downloadPromise = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "下载 .md" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("ocr-zh-article.md");
  const markdown = await readFile(await download.path(), "utf8");
  expect(markdown).toContain("（校对补充）");
  expect(markdown).not.toContain("<script");

  // 5) 关闭（有编辑时确认丢弃）
  page.on("dialog", (confirm) => void confirm.accept());
  await dialog.locator(".el-dialog__headerbtn").click();

  // 断言没有从第三方 CDN 加载 OCR 模型/wasm/引擎。md-editor-v3 预览器自带的
  // highlight/katex/mermaid unpkg 资源是整个应用（文章阅读页、HTML 导入）的既有
  // 行为，不属于本功能引入的依赖，这里只把 OCR 相关域名与资源列入黑名单。
  const OCR_CDN_BLOCKLIST = /jsdelivr|huggingface|cdnjs|paddleocr|onnxruntime|\.ort\b|\.wasm\b/i;
  const ocrRelated = thirdPartyRequests.filter((url) => OCR_CDN_BLOCKLIST.test(url));
  expect(ocrRelated).toEqual([]);
});

test("截图校对应用到私有笔记后须主动保存，刷新可读回", async ({ page }) => {
  test.setTimeout(180_000);
  await serveInstalledVditorAssets(page);
  await loginAndOpenWriter(page);
  const dialog = await openScreenshotDialog(page);
  const image = await readFile(resolve(fixturesDir, "ocr-zh-article.png"));
  await dialog.locator('input[type="file"]').setInputFiles({ name: "ocr-zh-article.png", mimeType: "image/png", buffer: image });
  await expect(dialog.locator(".ocr-preview-body")).toContainText("当网页正文确实显示在屏幕上", { timeout: 150_000 });
  await dialog.getByRole("button", { name: "放入私有笔记" }).click();
  await expect(dialog).toBeHidden();
  const notes = page.getByRole("dialog", { name: "我的私有笔记" });
  await expect(notes).toBeVisible();
  const title = await notes.getByRole("textbox", { name: "笔记标题" }).inputValue();
  expect(title.trim()).not.toBe("");
  await expect(notes.getByText("尚未保存", { exact: true })).toBeVisible();
  let leavePrompt = false;
  page.once("dialog", async (confirm) => {
    leavePrompt = true;
    expect(confirm.type()).toBe("confirm");
    await confirm.dismiss();
  });
  await page.locator('a[href="/chat"]').first().evaluate((link: HTMLAnchorElement) => link.click());
  await expect.poll(() => leavePrompt).toBe(true);
  await expect(notes.getByRole("textbox", { name: "笔记标题" })).toHaveValue(title);
  const saved = page.waitForResponse((response) => response.url().includes("/api/agent/blog/notes/") && response.request().method() === "POST");
  await notes.getByRole("button", { name: "保存私有笔记" }).click();
  expect((await saved).status()).toBe(201);
  await expect(notes.getByRole("heading", { name: title, level: 1 })).toBeVisible();
  await notes.locator(".el-drawer__close-btn").click();
  await page.reload();
  await page.getByRole("button", { name: "关闭", exact: true }).first().click();
  await page.getByRole("button", { name: "我的笔记" }).click();
  await expect(page.getByRole("dialog", { name: "我的私有笔记" }).getByText(title, { exact: true })).toBeVisible();
});

test("代码截图标记为代码候选且提示需校对", async ({ page }) => {
  test.setTimeout(300_000);
  await serveInstalledVditorAssets(page);
  await loginAndOpenWriter(page);
  const dialog = await openScreenshotDialog(page);

  const codeBytes = await readFile(resolve(fixturesDir, "ocr-code.png"));
  await dialog.locator('input[type="file"]').setInputFiles({ name: "ocr-code.png", mimeType: "image/png", buffer: codeBytes });
  const blocksPane = dialog.locator(".ocr-blocks-pane");
  await expect(blocksPane.locator(".ocr-block-card").first()).toBeVisible({ timeout: 150_000 });
  // 代码块候选应带“需校对”提示；渲染出的代码块不带语言标注（OCR 无法确定语言）
  await expect(blocksPane.getByText("代码块候选", { exact: false }).first()).toBeVisible();
  const previewBody = dialog.locator(".ocr-preview-body");
  await expect(previewBody.locator("pre").first()).toBeVisible();
  // 渲染出的代码块不带语言标注（OCR 无法确定语言，不自动编造）
  expect(await previewBody.locator("[class*='language-']").count()).toBe(0);
  page.on("dialog", (confirm) => void confirm.accept());
  await dialog.locator(".el-dialog__headerbtn").click();
});

test("长图分段像素候选覆盖白底图表、浅色/含字插图和下半部跨段多图，并可裁出完整图", async ({ page }) => {
  test.setTimeout(300_000);
  await serveInstalledVditorAssets(page);
  await loginAndOpenWriter(page);
  const dialog = await openScreenshotDialog(page);
  const textBytes = await readFile(resolve(fixturesDir, "ocr-zh-article.png"));
  const synthetic = await page.evaluate(async (sourceBase64) => {
    const source = new Image(); source.src = `data:image/png;base64,${sourceBase64}`; await source.decode();
    const canvas = document.createElement("canvas"); canvas.width = 760; canvas.height = 4200;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#fff"; context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(source, 0, 0, 760, 430);
    // 合成的真实比例诊断样本：白底线图、浅色有字插图、跨扫描分段大图及下半部多图。
    const frame = (x: number, y: number, width: number, height: number, color = "#d4dbe2") => {
      context.strokeStyle = color; context.lineWidth = 2; context.strokeRect(x, y, width, height);
    };
    context.fillStyle = "#fff"; context.fillRect(80, 1050, 600, 390); frame(80, 1050, 600, 390, "#cbd4dc");
    context.strokeStyle = "#e1e6eb"; context.lineWidth = 1;
    for (let y = 1100; y < 1400; y += 55) { context.beginPath(); context.moveTo(130, y); context.lineTo(640, y); context.stroke(); }
    for (let x = 160; x < 640; x += 80) { context.beginPath(); context.moveTo(x, 1090); context.lineTo(x, 1390); context.stroke(); }
    context.strokeStyle = "#aac9df"; context.lineWidth = 5; context.beginPath();
    context.moveTo(145, 1320); context.lineTo(245, 1260); context.lineTo(340, 1295); context.lineTo(445, 1170); context.lineTo(545, 1200); context.lineTo(620, 1125); context.stroke();
    context.fillStyle = "#b9c4cf"; context.font = "18px sans-serif"; context.fillText("销量趋势", 105, 1085); frame(80, 1050, 600, 390, "#cbd4dc");
    context.fillStyle = "#faf8f2"; context.fillRect(110, 1810, 540, 330); frame(110, 1810, 540, 330, "#e8e1d4");
    context.fillStyle = "#e8eee8"; context.beginPath(); context.arc(245, 1940, 72, 0, Math.PI * 2); context.fill();
    context.fillStyle = "#f0ddcc"; context.fillRect(355, 1870, 220, 145);
    context.strokeStyle = "#c8d5ca"; context.lineWidth = 8; context.beginPath(); context.moveTo(145, 2070); context.lineTo(600, 2070); context.stroke();
    context.fillStyle = "#736f68"; context.font = "20px sans-serif"; context.fillText("图 2 结构示意", 250, 2110);
    context.fillStyle = "#f4f6f8"; context.fillRect(90, 2460, 580, 900); frame(90, 2460, 580, 900, "#ccd4dc");
    const palette = ["#d9e6ed", "#dfe9dc", "#f0e1ce", "#d6e1ee"];
    for (let row = 0; row < 860; row += 28) for (let column = 0; column < 540; column += 30) {
      context.fillStyle = palette[(Math.floor(row / 28) + Math.floor(column / 30)) % palette.length]!;
      context.fillRect(110 + column, 2480 + row, 23, 20);
    }
    context.fillStyle = "#3d5264"; context.font = "26px sans-serif"; context.fillText("图中说明文字", 270, 2910);
    context.fillStyle = "#fbfbf8"; context.fillRect(90, 3660, 250, 260); frame(90, 3660, 250, 260, "#d9ded8");
    context.fillStyle = "#e4eee7"; context.fillRect(115, 3690, 200, 180);
    context.fillStyle = "#b9c8bd"; context.beginPath(); context.arc(215, 3780, 58, 0, Math.PI * 2); context.fill();
    context.fillStyle = "#faf9f4"; context.fillRect(420, 3660, 250, 260); frame(420, 3660, 250, 260, "#ddd6ce");
    context.fillStyle = "#f0dfcf"; context.fillRect(445, 3690, 200, 180); context.fillStyle = "#d7c4b2"; context.fillRect(485, 3730, 120, 100);
    const bounds = [
      { x: 80 / 760, y: 1050 / 4200, width: 600 / 760, height: 390 / 4200 },
      { x: 110 / 760, y: 1810 / 4200, width: 540 / 760, height: 330 / 4200 },
      { x: 90 / 760, y: 2460 / 4200, width: 580 / 760, height: 900 / 4200 },
      { x: 90 / 760, y: 3660 / 4200, width: 250 / 760, height: 260 / 4200 },
      { x: 420 / 760, y: 3660 / 4200, width: 250 / 760, height: 260 / 4200 },
    ];
    return { data: canvas.toDataURL("image/png").split(",")[1]!, bounds };
  }, textBytes.toString("base64"));

  // 纯文字不应被大量误报，且手动入口始终可见。
  await dialog.locator('input[type="file"]').setInputFiles({ name: "text-only.png", mimeType: "image/png", buffer: textBytes });
  await expect(dialog.locator(".ocr-blocks-pane .ocr-block-card").first()).toBeVisible({ timeout: 150_000 });
  await dialog.locator(".el-alert__title").filter({ hasText: "正在按原始分辨率分段检查" }).waitFor({ state: "hidden", timeout: 150_000 });
  await expect(dialog.locator(".el-alert__title").filter({ hasText: "没有自动候选" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "手动框选页面配图" })).toBeVisible();

  await dialog.getByRole("button", { name: "换一张截图" }).click();
  await dialog.locator('input[type="file"]').setInputFiles({
    name: "long-mixed-figures.png", mimeType: "image/png", buffer: Buffer.from(synthetic.data, "base64"),
  });
  await expect(dialog.locator(".ocr-blocks-pane .ocr-block-card").first()).toBeVisible({ timeout: 150_000 });
  await dialog.locator(".el-alert__title").filter({ hasText: "正在按原始分辨率分段检查" }).waitFor({ state: "hidden", timeout: 150_000 });
  const pixelButtons = dialog.locator('.ocr-tile .ocr-image-candidate.pixels[aria-label^="建议区域"]');
  await expect.poll(() => pixelButtons.count(), { timeout: 45_000 }).toBeGreaterThanOrEqual(4);
  const found = await pixelButtons.evaluateAll((buttons) => buttons.map((button) => {
    const style = (button as HTMLElement).style;
    return { x: parseFloat(style.left) / 100, y: parseFloat(style.top) / 100,
      width: parseFloat(style.width) / 100, height: parseFloat(style.height) / 100 };
  }));
  const matched = synthetic.bounds.map((expected) => found.some((actual) => {
    const iw = Math.max(0, Math.min(expected.x + expected.width, actual.x + actual.width) - Math.max(expected.x, actual.x));
    const ih = Math.max(0, Math.min(expected.y + expected.height, actual.y + actual.height) - Math.max(expected.y, actual.y));
    const intersection = iw * ih; const union = expected.width * expected.height + actual.width * actual.height - intersection;
    return intersection / Math.max(1e-9, union) >= 0.3;
  }));
  const candidateStages = await dialog.locator(".ocr-review").evaluate((review) => ({
    pixelRaw: Number(review.getAttribute("data-pixel-raw-candidates")),
    pixelAfterDomDedupe: Number(review.getAttribute("data-pixel-deduped-candidates")),
  }));
  const renderedCount = await pixelButtons.count();
  console.log(`B048 candidates: source=5, extension=0, protocol=0, pixel=${candidateStages.pixelRaw}, afterDomDedupe=${candidateStages.pixelAfterDomDedupe}, rendered=${renderedCount}; expected=${matched.join(",")}; bounds=${JSON.stringify(found)}`);
  expect(candidateStages.pixelRaw).toBe(found.length);
  expect(candidateStages.pixelAfterDomDedupe).toBe(found.length);
  expect(renderedCount).toBe(found.length);
  expect(matched.filter(Boolean).length).toBeGreaterThanOrEqual(4);
  expect(found.length).toBeLessThanOrEqual(10);
  const lowerExpected = synthetic.bounds.slice(3);
  const lowerMatches = lowerExpected.map((expected) => found.findIndex((actual) => {
    const iw = Math.max(0, Math.min(expected.x + expected.width, actual.x + actual.width) - Math.max(expected.x, actual.x));
    const ih = Math.max(0, Math.min(expected.y + expected.height, actual.y + actual.height) - Math.max(expected.y, actual.y));
    const intersection = iw * ih; const union = expected.width * expected.height + actual.width * actual.height - intersection;
    return intersection / Math.max(1e-9, union) >= 0.45;
  }));
  expect(lowerMatches[0]).toBeGreaterThanOrEqual(0);
  expect(lowerMatches[1]).toBeGreaterThanOrEqual(0);
  expect(lowerMatches[0]).not.toBe(lowerMatches[1]);
  const longFigureIndex = found.findIndex((box) => box.y < 0.6 && box.y + box.height > 0.7 && box.width > 0.6);
  expect(longFigureIndex).toBeGreaterThanOrEqual(0);
  await pixelButtons.nth(longFigureIndex).click({ position: { x: 10, y: 10 } });
  console.log("B048 crop: candidate clicked; waiting for crop preview");
  const cropPreview = dialog.getByLabel("当前图片裁剪预览").locator("img");
  await expect(cropPreview).toBeVisible();
  console.log("B048 crop: preview image visible");
  const preview = await cropPreview.evaluate(async (img: HTMLImageElement, input: { sourceBase64: string; box: typeof found[number] }) => {
    await img.decode();
    const source = new Image(); source.src = `data:image/png;base64,${input.sourceBase64}`; await source.decode();
    const canvas = document.createElement("canvas"); canvas.width = 32; canvas.height = 32;
    const context = canvas.getContext("2d", { willReadFrequently: true })!;
    context.drawImage(img, 0, 0, canvas.width, canvas.height);
    const actual = context.getImageData(0, 0, canvas.width, canvas.height).data;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(source, input.box.x * source.naturalWidth, input.box.y * source.naturalHeight,
      input.box.width * source.naturalWidth, input.box.height * source.naturalHeight, 0, 0, canvas.width, canvas.height);
    const expected = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let totalDiff = 0;
    for (let i = 0; i < actual.length; i += 4) totalDiff += Math.abs(actual[i]! - expected[i]!) +
      Math.abs(actual[i + 1]! - expected[i + 1]!) + Math.abs(actual[i + 2]! - expected[i + 2]!);
    return { width: img.naturalWidth, height: img.naturalHeight, averageRgbDiff: totalDiff / (canvas.width * canvas.height * 3) };
  }, { sourceBase64: synthetic.data, box: found[longFigureIndex]! });
  expect(preview.width).toBeGreaterThanOrEqual(500);
  expect(preview.height).toBeGreaterThanOrEqual(750);
  expect(preview.averageRgbDiff).toBeLessThan(5);
  await dialog.getByRole("button", { name: "返回校对" }).click();
  await expect(dialog.getByRole("button", { name: "手动框选页面配图" })).toBeVisible();
  page.on("dialog", (confirm) => void confirm.accept());
  await dialog.locator(".el-dialog__headerbtn").click();
});

test("长图校对导航在候选/手动裁剪返回、双向文字定位与逐屏切换后保持逻辑位置", async ({ page }) => {
  test.setTimeout(600_000);
  await serveInstalledVditorAssets(page);
  await loginAndOpenWriter(page);
  const dialog = await openScreenshotDialog(page);
  const source = await readFile(resolve(fixturesDir, "ocr-zh-article.png"));
  const longImage = await page.evaluate(async (base64) => {
    const fixture = new Image(); fixture.src = `data:image/png;base64,${base64}`; await fixture.decode();
    const canvas = document.createElement("canvas"); canvas.width = 760; canvas.height = 4600;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#fff"; context.fillRect(0, 0, canvas.width, canvas.height);
    for (const y of [80, 1700, 3550]) context.drawImage(fixture, 0, y, 760, 430);
    // Synthetic long-page navigation fixture: a pale picture panel in the lower half.
    context.fillStyle = "#faf8f2"; context.fillRect(90, 2660, 570, 620);
    context.strokeStyle = "#e4ded2"; context.lineWidth = 4; context.strokeRect(90, 2660, 570, 620);
    context.fillStyle = "#e3ece6"; context.fillRect(130, 2710, 490, 500);
    for (let y = 2730; y < 3190; y += 34) {
      context.strokeStyle = "#c8d8cd"; context.lineWidth = 2;
      context.beginPath(); context.moveTo(150, y); context.lineTo(600, y + (y % 3) * 5); context.stroke();
    }
    context.fillStyle = "#3c5148"; context.font = "24px Arial"; context.fillText("FIGURE LABEL", 230, 2940);
    return canvas.toDataURL("image/png");
  }, source.toString("base64"));
  const sourceBytes = Buffer.from(longImage.split(",")[1]!, "base64");
  await dialog.locator('input[type="file"]').setInputFiles({ name: "scroll-navigation-long.png", mimeType: "image/png", buffer: sourceBytes });
  await expect(dialog.locator(".ocr-blocks-pane .ocr-block-card").first()).toBeVisible({ timeout: 240_000 });
  await expect(dialog.locator(".ocr-image-pane img").first()).toBeVisible();
  await dialog.locator(".el-alert__title").filter({ hasText: "正在按原始分辨率分段检查" }).waitFor({ state: "hidden", timeout: 180_000 });
  // Pixel candidate detection is independent of progressive OCR completion. Wait for
  // the OCR worker too before asserting the fixture's complete block count.
  await expect(dialog.locator(".ocr-blocks-pane .ocr-progress-inline")).toBeHidden({ timeout: 240_000 });

  const imagePane = dialog.locator(".ocr-image-pane");
  const blocksPane = dialog.locator(".ocr-blocks-pane");
  const previewPane = dialog.locator(".ocr-preview-body");
  const metrics = async () => page.evaluate(() => {
    const pane = document.querySelector<HTMLElement>(".ocr-image-pane")!;
    const img = pane.querySelector<HTMLImageElement>(".ocr-image-wrap img")!;
    const paneRect = pane.getBoundingClientRect(); const imageRect = img.getBoundingClientRect();
    const anchor = paneRect.top + pane.clientHeight * 0.25;
    return { pageY: Math.max(0, Math.min(1, (anchor - imageRect.top) / imageRect.height)) * img.naturalHeight,
      imageTop: imageRect.top, imageHeight: imageRect.height, imageNaturalHeight: img.naturalHeight, paneTop: paneRect.top,
      paneHeight: pane.clientHeight, imageScrollHeight: pane.scrollHeight, imageScroll: pane.scrollTop, textScroll: document.querySelector<HTMLElement>(".ocr-blocks-pane")!.scrollTop,
      outerScroll: window.scrollY, dialogScroll: document.querySelector<HTMLElement>(".el-dialog__body")!.scrollTop };
  });
  const targetAtQuarter = async (paneSelector: string, target: Locator) => {
    const pane = dialog.locator(paneSelector); const paneRect = await pane.boundingBox(); const targetRect = await target.boundingBox();
    expect(paneRect).not.toBeNull(); expect(targetRect).not.toBeNull();
    expect(Math.abs(targetRect!.y - paneRect!.y - paneRect!.height * 0.25)).toBeLessThan(36);
  };

  // Right-card -> image overlay and left-overlay -> matching right card. Actual boxes
  // and outer scroll positions are checked, not only selected styling.
  const textCards = dialog.locator(".ocr-block-card");
  expect(await textCards.count()).toBeGreaterThanOrEqual(4);
  await blocksPane.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  const lastCard = textCards.last();
  await lastCard.click();
  const blockId = await lastCard.getAttribute("data-block-id");
  expect(blockId).toBeTruthy();
  const targetCard = dialog.locator(`.ocr-block-card[data-block-id="${blockId}"]`);
  const targetOverlay = imagePane.locator(`.ocr-block-overlay[data-block-id="${blockId}"]`);
  await expect(targetOverlay).toBeVisible();
  await targetAtQuarter(".ocr-image-pane", targetOverlay);
  await targetAtQuarter(".ocr-blocks-pane", targetCard);
  const outerAfterRightClick = await page.evaluate(() => ({ windowY: window.scrollY, dialogY: document.querySelector<HTMLElement>(".el-dialog__body")!.scrollTop }));
  const beforeLeftClick = await metrics();
  await targetOverlay.click();
  await targetAtQuarter(".ocr-blocks-pane", targetCard);
  expect(await page.evaluate(() => ({ windowY: window.scrollY, dialogY: document.querySelector<HTMLElement>(".el-dialog__body")!.scrollTop }))).toEqual(outerAfterRightClick);
  const editor = targetCard.locator("textarea");
  await editor.focus();
  const afterFocus = await metrics();
  await editor.fill("manual edit remains in the selected OCR block");
  expect(Math.abs((await metrics()).imageScroll - afterFocus.imageScroll)).toBeLessThan(4);
  expect(beforeLeftClick.outerScroll).toBe(outerAfterRightClick.windowY);
  await targetCard.getByRole("button", { name: /上移第/ }).click();
  await targetAtQuarter(".ocr-blocks-pane", targetCard);
  await targetAtQuarter(".ocr-image-pane", targetOverlay);
  await targetCard.getByRole("button", { name: /删除第/ }).click();
  await expect(targetCard).toHaveCount(0);
  const selectedAfterDelete = dialog.locator(".ocr-block-card.selected").first();
  await expect(selectedAfterDelete).toBeVisible();
  await targetAtQuarter(".ocr-blocks-pane", selectedAfterDelete);

  // Put both independent panes away from their origins, open a real pixel suggestion,
  // then return. The source-image logical y and visible text card/offset must survive.
  const pixelCandidate = dialog.locator(".ocr-image-pane .ocr-image-candidate.pixels").first();
  await expect(pixelCandidate).toBeVisible({ timeout: 30_000 });
  await pixelCandidate.scrollIntoViewIfNeeded();
  await blocksPane.evaluate((element) => { element.scrollTop = Math.min(90, element.scrollHeight - element.clientHeight); });
  await previewPane.evaluate((element) => { element.scrollTop = Math.min(24, element.scrollHeight - element.clientHeight); });
  const beforeCrop = await metrics();
  const visibleTextId = await selectedAfterDelete.getAttribute("data-block-id");
  await pixelCandidate.click();
  await expect(dialog.getByLabel("当前图片裁剪预览")).toBeVisible();
  await dialog.getByRole("button", { name: "返回校对" }).click();
  await expect(dialog.locator(".ocr-review")).toBeVisible();
  await expect.poll(async () => Math.abs((await metrics()).pageY - beforeCrop.pageY), { timeout: 10_000 }).toBeLessThan(55);
  const afterCrop = await metrics();
  expect(Math.abs(afterCrop.textScroll - beforeCrop.textScroll)).toBeLessThan(35);
  expect(await dialog.locator(`.ocr-block-card[data-block-id="${visibleTextId}"]`).count()).toBe(1);

  // Manually opened crop follows the same snapshot/restore path even when the user
  // cancels without making a crop selection. Repeated entry must not drift to top.
  await imagePane.evaluate((element) => { element.scrollTop = Math.max(0, element.scrollHeight - element.clientHeight - 110); });
  const beforeManualCrop = await metrics();
  await dialog.getByRole("button", { name: "手动框选页面配图" }).click();
  await dialog.getByRole("button", { name: "返回校对" }).click();
  await expect.poll(async () => Math.abs((await metrics()).pageY - beforeManualCrop.pageY), { timeout: 10_000 }).toBeLessThan(55);

  page.on("dialog", (confirm) => void confirm.accept());
  await dialog.locator(".el-dialog__headerbtn").click();
});

test("长截图顶部、中部和底部的清晰文字都能识别", async ({ page }) => {
  test.setTimeout(600_000);
  await serveInstalledVditorAssets(page);
  await loginAndOpenWriter(page);
  const dialog = await openScreenshotDialog(page);
  const dataUrl = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 980;
    canvas.height = 3800;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#111";
    context.font = "bold 30px Arial";
    for (const [label, y] of [["TOP SECTION", 120], ["MIDDLE SECTION", 1900], ["BOTTOM SECTION", 3650]] as const) {
      context.fillText(label, 60, y);
      context.font = "26px Arial";
      context.fillText("Clear readable words on this page", 60, y + 42);
      context.font = "bold 30px Arial";
    }
    return canvas.toDataURL("image/png");
  });
  await dialog.locator('input[type="file"]').setInputFiles({
    name: "long-readable.png", mimeType: "image/png", buffer: Buffer.from(dataUrl.split(",")[1]!, "base64"),
  });
  const preview = dialog.locator(".ocr-preview-body");
  await expect(preview).toContainText("BOTTOM SECTION", { timeout: 300_000 });
  const recognized = await preview.innerText();
  expect(recognized.match(/Clear readable words on this page/g)).toHaveLength(3);
  const positions = await dialog.locator(".ocr-block-overlay").evaluateAll((elements) =>
    elements.map((element) => parseFloat((element as HTMLElement).style.top)));
  expect(positions.some((position) => position < 10)).toBe(true);
  expect(positions.some((position) => position > 40 && position < 60)).toBe(true);
  expect(positions.some((position) => position > 85)).toBe(true);
});

const rpcSamplePath = process.env.OCR_REAL_SAMPLE_PATH;
test("B-051 指定 RPC.png 通过产品本地上传校对并保存本地诊断", async ({ page }) => {
  test.skip(!rpcSamplePath, "需显式设置 OCR_REAL_SAMPLE_PATH 才会本机运行私有 RPC.png 验收");
  test.setTimeout(900_000);
  if (!rpcSamplePath) return;
  const buildDiagnosticRecognition = (strategy: string | undefined, batch: string | undefined) => ({
    ...(strategy === "per-line" || strategy === "per-box" ? { strategy } : {}),
    ...(batch === "1" ? { recBatchSize: 1 as const } : batch === "4" ? { recBatchSize: 4 as const } : {}),
    ...(process.env.OCR_DIAGNOSTIC_PADDING && Number.isFinite(Number(process.env.OCR_DIAGNOSTIC_PADDING))
      ? { paddingVertical: Math.max(0, Math.min(1, Number(process.env.OCR_DIAGNOSTIC_PADDING))) } : {}),
    ...(process.env.OCR_DIAGNOSTIC_SKIP_RETRY === "1" ? { skipRetry: true } : {}),
  });
  const configuredVariants = (process.env.OCR_DIAGNOSTIC_VARIANTS ?? "").split(",").filter(Boolean).slice(0, 4).map((variant) => {
    const [strategy, batch] = variant.split(":");
    return buildDiagnosticRecognition(strategy, batch);
  });
  const diagnosticRecognitionByRun = configuredVariants.length ? configuredVariants : [buildDiagnosticRecognition(
    process.env.OCR_DIAGNOSTIC_STRATEGY,
    process.env.OCR_DIAGNOSTIC_BATCH,
  )];
  const diagnosticModelDirectory = process.env.OCR_DIAGNOSTIC_MODEL_DIR;
  const diagnosticModel = diagnosticModelDirectory ? await Promise.all([
    readFile(resolve(diagnosticModelDirectory, "PP-OCRv6_tiny_det.ort")),
    readFile(resolve(diagnosticModelDirectory, "PP-OCRv6_tiny_rec.ort")),
    readFile(resolve(diagnosticModelDirectory, "ppocrv6_dict.txt")),
  ]).then(([detection, recognition, charactersDictionary]) => ({
    name: "PP-OCRv6 tiny" as const,
    detection: detection.toString("base64"), recognition: recognition.toString("base64"), charactersDictionary: charactersDictionary.toString("base64"),
    sha256: {
      detection: createHash("sha256").update(detection).digest("hex"),
      recognition: createHash("sha256").update(recognition).digest("hex"),
      charactersDictionary: createHash("sha256").update(charactersDictionary).digest("hex"),
    },
  })) : null;
  await page.addInitScript(({ forceWasm, recognitionOptionsByRun, model }: { forceWasm: boolean; recognitionOptionsByRun: Array<Record<string, unknown>>; model: null | { name: "PP-OCRv6 tiny"; detection: string; recognition: string; charactersDictionary: string; sha256: { detection: string; recognition: string; charactersDictionary: string } } }) => {
    const host = window as typeof window & { __b051WorkerMessages?: unknown[]; __b051InitTimings?: number[]; __b051DiagnosticEnabled?: boolean; __b051ForceWasm?: boolean };
    host.__b051WorkerMessages = [];
    host.__b051InitTimings = [];
    host.__b051DiagnosticEnabled = true;
    host.__b051ForceWasm = forceWasm;
    (host as typeof host & { __b051RunIndex?: number }).__b051RunIndex = 0;
    const NativeWorker = window.Worker;
    window.Worker = new Proxy(NativeWorker, {
      construct(target, args, newTarget) {
        const worker = Reflect.construct(target, args, newTarget);
        let initSentAt: number | null = null;
        worker.addEventListener("message", (event: MessageEvent) => {
          const data = event.data;
          if (data?.type === "ready" && initSentAt !== null) host.__b051InitTimings?.push(Math.round(performance.now() - initSentAt));
          if (data && (data.type === "partial" || data.type === "result" || data.type === "error" || data.type === "ready" || data.type === "progress")) {
            host.__b051WorkerMessages?.push(data);
          }
        });
        const originalPostMessage = worker.postMessage.bind(worker);
        worker.postMessage = ((message: unknown, transfer?: Transferable[]) => {
          if (message && typeof message === "object" && (message as { type?: string }).type === "init") {
            initSentAt = performance.now();
            if (host.__b051ForceWasm === true) (message as { providerOverride?: "wasm" }).providerOverride = "wasm";
            if (model) {
              const asBuffer = (base64: string) => {
                const binary = atob(base64); const bytes = new Uint8Array(binary.length);
                for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
                return bytes.buffer;
              };
              (message as { diagnosticModelAssets?: unknown }).diagnosticModelAssets = {
                name: model.name, detection: asBuffer(model.detection), recognition: asBuffer(model.recognition),
                charactersDictionary: asBuffer(model.charactersDictionary), sha256: model.sha256,
              };
            }
          }
          if (message && typeof message === "object" && (message as { type?: string }).type === "recognize") {
            (message as { diagnostics?: boolean }).diagnostics = host.__b051DiagnosticEnabled === true;
            const runIndex = (host as typeof host & { __b051RunIndex?: number }).__b051RunIndex ?? 0;
            const recognitionOptions = recognitionOptionsByRun[runIndex] ?? {};
            if (host.__b051DiagnosticEnabled === true && Object.keys(recognitionOptions).length > 0) {
              (message as { diagnosticRecognition?: unknown }).diagnosticRecognition = recognitionOptions;
            }
          }
          return originalPostMessage(message, transfer);
        }) as typeof worker.postMessage;
        return worker;
      },
    });
  }, { forceWasm: process.env.OCR_FORCE_PROVIDER === "wasm", recognitionOptionsByRun: diagnosticRecognitionByRun, model: diagnosticModel });
  await serveInstalledVditorAssets(page);
  await loginAndOpenWriter(page);
  const dialog = await openScreenshotDialog(page);
  const diagnosticDirectory = resolve(process.env.TEMP || process.cwd(), "b051-rpc-local");
  await mkdir(diagnosticDirectory, { recursive: true });
  const sourceFileBytes = await readFile(rpcSamplePath);
  const sampleDimensions = sourceFileBytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
    ? { width: sourceFileBytes.readUInt32BE(16), height: sourceFileBytes.readUInt32BE(20) }
    : { width: 0, height: 0 };
  const runs: Array<Record<string, unknown>> = [];
  const repeatCount = configuredVariants.length || Math.max(1, Math.min(4, Number(process.env.OCR_REAL_SAMPLE_RUNS) || 3));
  let latestMarkdown = "";
  let latestBlocks: Array<{ id: string; text: string; kind: string; bbox: string }> = [];
  let latestMessages: unknown[] = [];
  for (let index = 0; index < repeatCount; index += 1) {
    if (index > 0) await dialog.getByRole("button", { name: "换一张截图" }).click();
    await page.evaluate((runIndex) => {
      (window as typeof window & { __b051RunIndex?: number }).__b051RunIndex = runIndex;
    }, index);
    await page.evaluate(() => { (window as typeof window & { __b051WorkerMessages?: unknown[] }).__b051WorkerMessages = []; });
    const uploadedAt = Date.now();
    const heapReadings: number[] = [];
    const heapSampler = setInterval(() => {
      void page.evaluate(() => {
        const memory = (performance as Performance & { memory?: { usedJSHeapSize?: number } }).memory;
        return memory?.usedJSHeapSize ?? null;
      }).then((usedBytes) => { if (typeof usedBytes === "number" && Number.isFinite(usedBytes)) heapReadings.push(usedBytes); }).catch(() => undefined);
    }, 500);
    let firstDisplayMs = 0;
    let fullUiMs = 0;
    try {
      await dialog.locator('input[type="file"]').setInputFiles(rpcSamplePath);
      await expect(dialog.locator(".ocr-blocks-pane .ocr-block-card").first()).toBeVisible({ timeout: 90_000 });
      firstDisplayMs = Date.now() - uploadedAt;
      await expect(dialog.locator(".ocr-blocks-pane .ocr-progress-inline")).toBeHidden({ timeout: 300_000 });
      fullUiMs = Date.now() - uploadedAt;
    } catch (error) {
      const failedMessages = await page.evaluate(() => (window as typeof window & { __b051WorkerMessages?: unknown[] }).__b051WorkerMessages ?? []);
      await writeFile(resolve(diagnosticDirectory, `rpc-product-run-${index + 1}-failure-worker-messages.json`), JSON.stringify(failedMessages), "utf8");
      throw error;
    } finally {
      clearInterval(heapSampler);
    }
    latestMarkdown = await dialog.locator(".ocr-preview-body").innerText();
    latestBlocks = await dialog.locator(".ocr-block-card").evaluateAll((cards) => cards.map((card) => ({
      id: (card as HTMLElement).dataset.blockId ?? "",
      kind: card.querySelector("select")?.getAttribute("aria-label") ?? "",
      text: card.querySelector("textarea")?.value ?? "",
      bbox: "",
    })));
    latestMessages = await page.evaluate(() => (window as typeof window & { __b051WorkerMessages?: unknown[] }).__b051WorkerMessages ?? []);
    const runMessages = latestMessages as Array<{ type?: string; lines?: Array<{ text?: string }>; metrics?: Record<string, unknown>; diagnostic?: { rawBandLines?: Array<{ text?: string }>; rawDetectionBoxes?: unknown[]; paddedDetectionBoxes?: unknown[]; recognitionBoxes?: unknown[]; recognitionTensorShapes?: number[][] } }>;
    const initTimings = await page.evaluate(() => (window as typeof window & { __b051InitTimings?: number[] }).__b051InitTimings ?? []);
    const final = [...runMessages].reverse().find((message) => message.type === "result");
    if (!configuredVariants.length && !process.env.OCR_DIAGNOSTIC_BATCH) {
      const bandTimings = (final?.metrics?.bandTimings ?? []) as Array<{ retryRows?: number; retryBatchSize?: number }>;
      expect(bandTimings.every((band) => !band.retryRows || band.retryBatchSize === 1), "targeted retry must use batch size 1").toBe(true);
    }
    const lineCount = final?.lines?.length ?? 0;
    const blockCount = latestBlocks.length;
    const characterCount = latestBlocks.reduce((sum, block) => sum + [...block.text].length, 0);
    runs.push({ run: index + 1, firstDisplayMs, fullUiMs, peakJsHeapBytes: heapReadings.length ? Math.max(...heapReadings) : null,
      lineCount, blockCount, characterCount, ...(index === 0 ? { modelInitMs: initTimings[0] ?? null } : {}), metrics: final?.metrics ?? null });
    const runPrefix = `rpc-product-run-${index + 1}`;
    await writeFile(resolve(diagnosticDirectory, `${runPrefix}-markdown.md`), latestMarkdown, "utf8");
    await writeFile(resolve(diagnosticDirectory, `${runPrefix}-blocks.json`), JSON.stringify(latestBlocks, null, 2), "utf8");
    await writeFile(resolve(diagnosticDirectory, `${runPrefix}-worker-messages.json`), JSON.stringify(latestMessages), "utf8");
    if (index === 0 && configuredVariants.length <= 1) {
      await page.evaluate(() => { (window as typeof window & { __b051DiagnosticEnabled?: boolean }).__b051DiagnosticEnabled = false; });
    }
  }
  await writeFile(resolve(diagnosticDirectory, "rpc-product-benchmark.json"), JSON.stringify({ ...sampleDimensions, runs }, null, 2), "utf8");
  // The console contains only aggregate timing/counts. OCR text stays in local
  // temp diagnostics and is never attached to the test report or repository.
  console.log(`OCR_RPC_PRODUCT_LOCAL ${JSON.stringify(runs.map(({ run, modelInitMs, firstDisplayMs, fullUiMs, peakJsHeapBytes, lineCount, blockCount, characterCount }) => ({ run, modelInitMs, firstDisplayMs, fullUiMs, peakJsHeapBytes, lineCount, blockCount, characterCount })))}`);
  page.on("dialog", (confirm) => void confirm.accept());
  await dialog.locator(".el-dialog__headerbtn").click();
});
