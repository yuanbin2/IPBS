import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const pngBytes = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGNUrrjDwMDAxAAGABEFAXsZWVM7AAAAAElFTkSuQmCC",
  "base64",
);

async function serveInstalledVditorAssets(page: Page) {
  const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../node_modules/vditor");
  await page.route(/^https:\/\/unpkg\.com\/vditor@4\.0\.0\/dist\/js\/(?:i18n|icons|lute)\/[\w.-]+\.js(?:\?.*)?$/, async (route) => {
    const path = new URL(route.request().url()).pathname.split("/vditor@4.0.0/")[1];
    await route.fulfill({ path: resolve(packageRoot, path) });
  });
}

async function uploadHtml(page: Page) {
  const html = `<!doctype html><html><head><title>站点标题</title></head><body>
    <nav><a href="/home">网站导航</a></nav>
    <article><h1>网页导入专项</h1><p>第一段真实正文，应该变成可编辑的 Markdown。</p>
    <aside><p>旁边的附注，由用户决定是否保留。</p></aside>
    <h2>代码部分</h2><pre><code class="language-python">print("import works")</code></pre>
    <p>最后一个段落，包含 <strong>加粗</strong> 和 <a href="https://example.org/source">来源</a>。</p>
    <img src="https://assets.example.org/remote.png" alt="远程示意图">
    <img src="./saved_files/chart.png" alt="图表"></article>
    <script>window.__htmlImportExecuted = true</script></body></html>`;
  await page.locator('input[accept=".html,.htm"]').setInputFiles({
    name: "webpage.html",
    mimeType: "text/html",
    buffer: Buffer.from(html),
  });
  const dialog = page.getByRole("dialog", { name: "从 HTML 导入文章" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("导入文章标题")).toHaveValue("网页导入专项");
  return dialog;
}

test("HTML import previews safe blocks, preserves draft, and renders uploaded images for readers", async ({ page, browser }) => {
  test.setTimeout(150_000);
  await serveInstalledVditorAssets(page);
  await page.route("https://assets.example.org/remote.png", (route) => route.fulfill({
    status: 200, contentType: "image/png", body: pngBytes,
  }));
  await page.goto("/login?redirect=%2Fblog");
  await page.getByPlaceholder("用户名").fill("upload-e2e-operator");
  await page.getByPlaceholder("密码，至少 8 位").fill("Upload-e2e-only-2026!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/blog$/);
  await page.getByRole("button", { name: "写博客", exact: true }).click();
  await expect(page.locator(".vditor-wysiwyg")).toBeVisible();
  await page.getByPlaceholder("文章标题", { exact: true }).fill("旧草稿标题");

  let dialog = await uploadHtml(page);
  await expect(dialog).toContainText("HTML 引用了本地图片");
  await expect(dialog.getByLabel("Markdown 排版预览").locator('img[alt="远程示意图"]')).toBeVisible();
  await expect(dialog.getByLabel("Markdown 排版预览")).toContainText("第一段真实正文");
  await expect(dialog.getByLabel("Markdown 排版预览")).not.toContainText("网站导航");
  await expect(dialog.getByLabel("Markdown 排版预览")).not.toContainText("旁边的附注");
  expect(await page.evaluate(() => (window as any).__htmlImportExecuted)).toBeUndefined();
  await dialog.getByRole("button", { name: "取消" }).click();
  await expect(page.getByPlaceholder("文章标题", { exact: true })).toHaveValue("旧草稿标题");

  dialog = await uploadHtml(page);
  await dialog.getByLabel("选择配套图片文件", { exact: true }).setInputFiles([
    { name: "chart.png", mimeType: "image/png", buffer: pngBytes },
    { name: "remote.png", mimeType: "image/png", buffer: pngBytes },
  ]);
  await expect(dialog).toContainText("已匹配 1/1");
  await expect(dialog).toContainText("已选择本地替换 1 张");
  await dialog.locator(".html-import-block").filter({ hasText: "旁边的附注" }).locator(".el-checkbox").click();
  await expect(dialog.getByLabel("Markdown 排版预览")).toContainText("旁边的附注");
  const downloadPromise = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "下载 .md" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("网页导入专项.md");
  const downloadedMarkdown = await readFile(await download.path(), "utf8");
  expect(downloadedMarkdown).toContain("图片：图表（请在编辑器中上传）");
  expect(downloadedMarkdown).not.toContain("HTMLIMPORTLOCALIMAGE");

  await dialog.getByRole("button", { name: "应用到草稿" }).click();
  await page.getByRole("button", { name: "取消", exact: true }).last().click();
  await expect(dialog).toBeVisible();
  await expect(page.getByPlaceholder("文章标题", { exact: true })).toHaveValue("旧草稿标题");
  const imageResponsePromise = page.waitForResponse((response) => response.url().includes("/api/agent/blog/images/"));
  await dialog.getByRole("button", { name: "应用到草稿" }).click();
  await page.getByRole("button", { name: "继续导入" }).click();
  const imageResponse = await imageResponsePromise;
  expect(imageResponse.status()).toBe(201);
  const imageUrl = (await imageResponse.json()).url as string;
  await expect(dialog).toBeHidden();
  await expect(page.getByPlaceholder("文章标题", { exact: true })).toHaveValue("网页导入专项");
  await expect(page.locator(".vditor-wysiwyg")).toContainText("旁边的附注");
  await expect(page.locator(".vditor-wysiwyg")).toContainText("import works");
  await expect(page.locator(`.vditor-wysiwyg img[src="${imageUrl}"]`)).toBeVisible();
  await expect(page.locator('.vditor-wysiwyg img[src^="/media/blog/"]')).toHaveCount(2);
  await expect(page.locator('.vditor-wysiwyg img[src^="https://assets.example.org/"]')).toHaveCount(0);
  await page.reload();
  await expect(page.getByPlaceholder("文章标题", { exact: true })).toHaveValue("网页导入专项");
  await expect(page.locator(".vditor-wysiwyg")).toContainText("第一段真实正文");
  await expect(page.locator(`.vditor-wysiwyg img[src="${imageUrl}"]`)).toBeVisible();
  await expect(page.locator('.vditor-wysiwyg img[src^="/media/blog/"]')).toHaveCount(2);

  const createResponsePromise = page.waitForResponse((response) =>
    response.url().includes("/api/agent/blog/articles/") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "发布并加入知识库" }).first().click();
  const createResponse = await createResponsePromise;
  expect(createResponse.status()).toBe(202);
  const created = await createResponse.json();

  const adminContext = await browser.newContext();
  try {
    const adminPage = await adminContext.newPage();
    await adminPage.goto("/login?redirect=%2Fblog");
    await adminPage.getByPlaceholder("用户名").fill("upload-e2e-admin");
    await adminPage.getByPlaceholder("密码，至少 8 位").fill("Upload-e2e-only-2026!");
    await adminPage.getByRole("button", { name: "登录", exact: true }).click();
    await expect(adminPage).toHaveURL(/\/blog$/);
    const approval = await adminPage.evaluate(async (id) => {
      const response = await fetch(`/api/agent/approvals/${id}/`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision: "approve" }),
      });
      return { status: response.status, payload: await response.json() };
    }, created.approval.id);
    expect(approval.status).toBe(200);
    expect(approval.payload.status).toBe("executed");
  } finally {
    await adminContext.close();
  }

  const readerContext = await browser.newContext();
  try {
    const readerPage = await readerContext.newPage();
    await readerPage.goto("/login?redirect=%2Fblog");
    await readerPage.getByPlaceholder("用户名").fill("upload-e2e-reader");
    await readerPage.getByPlaceholder("密码，至少 8 位").fill("Upload-e2e-only-2026!");
    await readerPage.getByRole("button", { name: "登录", exact: true }).click();
    await expect(readerPage).toHaveURL(/\/blog$/);
    await readerPage.goto(`/blog/${created.article.slug}`);
    const images = readerPage.locator('.article-read-body .md-editor-preview img[src^="/media/blog/"]');
    await expect(images).toHaveCount(2);
    await expect.poll(() => images.first().evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
  } finally {
    await readerContext.close();
  }
});

test("remote image localization fails closed and then rewrites to a verified site image", async ({ page }) => {
  test.setTimeout(120_000);
  await serveInstalledVditorAssets(page);
  await page.route("https://assets.example.org/auto.png", (route) => route.fulfill({
    status: 200, contentType: "image/png", body: pngBytes,
  }));
  await page.goto("/login?redirect=%2Fblog");
  await page.getByPlaceholder("用户名").fill("upload-e2e-operator");
  await page.getByPlaceholder("密码，至少 8 位").fill("Upload-e2e-only-2026!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("button", { name: "写博客", exact: true }).click();

  const hostedUrl = await page.evaluate(async (bytes) => {
    const image = new File([new Uint8Array(bytes)], "auto.png", { type: "image/png" });
    const form = new FormData();
    form.append("image", image);
    const response = await fetch("/api/agent/blog/images/", { method: "POST", body: form });
    if (!response.ok) throw new Error(`preflight image upload: ${response.status}`);
    return (await response.json()).url as string;
  }, [...pngBytes]);

  let shouldFail = true;
  let requestedUrl = "";
  await page.route("**/api/agent/blog/imports/html/images/fetch/", async (route) => {
    requestedUrl = (route.request().postDataJSON() as { url: string }).url;
    await route.fulfill({
      status: shouldFail ? 422 : 201,
      contentType: "application/json",
      body: JSON.stringify(shouldFail ? { detail: "原站拒绝下载" } : { url: hostedUrl }),
    });
  });
  const html = '<article><h1>远程图片导入</h1><p>这是一篇带远程图片的文章。</p><img src="https://assets.example.org/auto.png" alt="自动图片"></article>';
  await page.locator('input[accept=".html,.htm"]').setInputFiles({
    name: "remote.html", mimeType: "text/html", buffer: Buffer.from(html),
  });
  const dialog = page.getByRole("dialog", { name: "从 HTML 导入文章" });
  await expect(dialog).toContainText("将自动下载 1 张");
  await dialog.getByRole("button", { name: "应用到草稿" }).click();
  await expect(page.getByText(/原站拒绝下载.*草稿没有更改/)).toBeVisible();
  await expect(dialog).toBeVisible();
  await expect(page.getByPlaceholder("文章标题", { exact: true })).toHaveValue("");

  shouldFail = false;
  await dialog.getByRole("button", { name: "应用到草稿" }).click();
  await expect(dialog).toBeHidden();
  expect(requestedUrl).toBe("https://assets.example.org/auto.png");
  await expect(page.locator(`.vditor-wysiwyg img[src="${hostedUrl}"]`)).toBeVisible();
  await expect(page.locator('.vditor-wysiwyg img[src^="https://assets.example.org/"]')).toHaveCount(0);
});
