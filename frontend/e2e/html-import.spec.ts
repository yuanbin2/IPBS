import { expect, test, type Page } from "@playwright/test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

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

test("HTML import previews safe blocks, preserves draft on cancel, and saves editable Markdown", async ({ page }) => {
  test.setTimeout(120_000);
  await serveInstalledVditorAssets(page);
  await page.goto("/login?redirect=%2Fblog");
  await page.getByPlaceholder("用户名").fill("upload-e2e-operator");
  await page.getByPlaceholder("密码，至少 8 位").fill("Upload-e2e-only-2026!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/blog$/);
  await page.getByRole("button", { name: "写博客", exact: true }).click();
  await expect(page.locator(".vditor-wysiwyg")).toBeVisible();
  await page.getByPlaceholder("文章标题", { exact: true }).fill("旧草稿标题");

  let dialog = await uploadHtml(page);
  await expect(dialog).toContainText("本地图片未包含在 HTML 中");
  await expect(dialog.getByLabel("Markdown 排版预览")).toContainText("第一段真实正文");
  await expect(dialog.getByLabel("Markdown 排版预览")).not.toContainText("网站导航");
  await expect(dialog.getByLabel("Markdown 排版预览")).not.toContainText("旁边的附注");
  expect(await page.evaluate(() => (window as any).__htmlImportExecuted)).toBeUndefined();
  await dialog.getByRole("button", { name: "取消" }).click();
  await expect(page.getByPlaceholder("文章标题", { exact: true })).toHaveValue("旧草稿标题");

  dialog = await uploadHtml(page);
  await dialog.locator(".html-import-block").filter({ hasText: "旁边的附注" }).locator(".el-checkbox").click();
  await expect(dialog.getByLabel("Markdown 排版预览")).toContainText("旁边的附注");
  const downloadPromise = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "下载 .md" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("网页导入专项.md");

  await dialog.getByRole("button", { name: "应用到草稿" }).click();
  await page.getByRole("button", { name: "取消", exact: true }).last().click();
  await expect(dialog).toBeVisible();
  await expect(page.getByPlaceholder("文章标题", { exact: true })).toHaveValue("旧草稿标题");
  await dialog.getByRole("button", { name: "应用到草稿" }).click();
  await page.getByRole("button", { name: "继续导入" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByPlaceholder("文章标题", { exact: true })).toHaveValue("网页导入专项");
  await expect(page.locator(".vditor-wysiwyg")).toContainText("旁边的附注");
  await expect(page.locator(".vditor-wysiwyg")).toContainText("import works");
  await page.reload();
  await expect(page.getByPlaceholder("文章标题", { exact: true })).toHaveValue("网页导入专项");
  await expect(page.locator(".vditor-wysiwyg")).toContainText("第一段真实正文");
});
