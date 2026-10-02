import { expect, test, type Page } from "@playwright/test";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const password = "Upload-e2e-only-2026!";
const operatorA = "upload-e2e-operator";
const operatorB = "upload-e2e-other";
const reader = "upload-e2e-reader";
const admin = "upload-e2e-admin";

async function serveInstalledVditorAssets(page: Page) {
  const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../node_modules/vditor");
  await page.route(/^https:\/\/unpkg\.com\/vditor@4\.0\.0\/dist\/js\/(?:i18n|icons|lute)\/[\w.-]+\.js(?:\?.*)?$/, async (route) => {
    const requestedPath = new URL(route.request().url()).pathname.split("/vditor@4.0.0/")[1];
    await route.fulfill({ path: resolve(packageRoot, requestedPath) });
  });
}

async function login(page: Page, username: string, destination = "/blog") {
  await page.goto(`/login?redirect=${encodeURIComponent(destination)}`);
  await page.getByPlaceholder("用户名").fill(username);
  await page.getByPlaceholder("密码，至少 8 位").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${destination.replaceAll("/", "\\/")}$`));
}

async function openWriter(page: Page) {
  await page.getByRole("button", { name: "写博客", exact: true }).click();
  await expect(page.getByRole("heading", { name: "写新博客" })).toBeVisible();
  await expect(page.locator(".vditor-wysiwyg")).toBeVisible();
}

async function importMarkdown(page: Page, title: string, content: string) {
  const markdown = `---\ntitle: "${title}"\nsummary: "B-010 browser draft test"\n---\n${content}`;
  await page.locator('input[accept=".md,.markdown,.txt"]').setInputFiles({
    name: `${title.replace(/[^a-z0-9]+/gi, "-")}.md`,
    mimeType: "text/markdown",
    buffer: Buffer.from(markdown),
  });
  const confirmImport = page.getByRole("button", { name: "继续导入" });
  if (await confirmImport.isVisible().catch(() => false)) await confirmImport.click();
  await expect(page.getByPlaceholder("文章标题")).toHaveValue(title);
  const firstHeading = content.match(/^#{1,6}\s+(.+)$/m)?.[1];
  if (firstHeading) await expect(page.locator(".vditor-wysiwyg")).toContainText(firstHeading);
  await expect(page.getByRole("status")).toContainText(/已自动保存在本机浏览器；尚未提交到服务器。|已从本机恢复|网络已断开/);
}

const markdownSamples = [
  "## 01 中文段落\n\n这是中文博客正文，包含标点、全角字符和表情 😀。",
  "## 02 多级标题\n\n### 子标题\n\n#### 更深标题\n\n层级必须保留。",
  "## 03 无序与嵌套列表\n\n- 一级\n  - 二级\n    - 三级",
  "## 04 有序列表\n\n1. 第一步\n2. 第二步\n3. 第三步",
  "## 05 任务列表\n\n- [x] 已完成\n- [ ] 待完成",
  "## 06 JavaScript 代码围栏\n\n```js\nconst answer = 42;\nconsole.log(answer);\n```",
  "## 07 Python 代码围栏\n\n```python\ndef greet(name):\n    return f'你好，{name}'\n```",
  "## 08 行内代码\n\n使用 `transaction.atomic()` 保证提交边界。",
  "## 09 表格\n\n| 字段 | 类型 |\n| --- | --- |\n| 标题 | text |\n| 状态 | ready |",
  "## 10 引用\n\n> 可靠草稿应能在刷新后恢复。\n>\n> — 测试记录",
  "## 11 外部链接\n\n[项目主页](https://example.test/project)",
  "## 12 图片\n\n![测试图片](https://example.test/image.png \"图片说明\")",
  "## 13 强调格式\n\n**加粗**、*斜体*、~~删除线~~与 `code`。",
  "## 14 分隔线\n\n上方内容\n\n---\n\n下方内容",
  "## 15 行内数学\n\n欧拉恒等式：$e^{i\\pi}+1=0$。",
  "## 16 块数学\n\n$$\n\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}\n$$",
  "## 17 Mermaid 流程图\n\n```mermaid\ngraph TD\n  A[开始] --> B[保存]\n  B --> C[恢复]\n```",
  "## 18 原始 HTML\n\n<span data-safe-example=\"yes\">允许的文本片段</span>",
  "## 19 脚本安全样本\n\n<script>window.__blogDraftXss = true</script>",
  "## 20 HTML 事件安全样本\n\n<img src=x onerror=\"window.__blogDraftXss = true\">",
];

test("twenty Markdown samples survive editor save, refresh, recovery, approval, and article display", async ({ page, browser }) => {
  test.setTimeout(180_000);
  await serveInstalledVditorAssets(page);
  await login(page, operatorA);
  await openWriter(page);

  const sampleContent = markdownSamples.join("\n\n");
  const expectedContent = sampleContent.trim();
  const title = `Markdown往返${Date.now()}`;
  await importMarkdown(page, title, sampleContent);
  await page.reload();
  await expect(page.getByRole("heading", { name: "写新博客" })).toBeVisible();
  await expect(page.getByPlaceholder("文章标题")).toHaveValue(title);
  await expect(page.locator(".vditor-wysiwyg")).toContainText("01 中文段落");

  const createResponsePromise = page.waitForResponse((response) =>
    response.url().includes("/api/agent/blog/articles/") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "发布并加入知识库" }).first().click();
  const createResponse = await createResponsePromise;
  expect(createResponse.status()).toBe(202);
  const createPayload = await createResponse.json();
  expect(createPayload.article.content).toBe(expectedContent);

  const adminContext = await browser.newContext();
  try {
    const adminPage = await adminContext.newPage();
    await login(adminPage, admin);
    const approvalResponse = await adminPage.evaluate(async ({ approvalId }) => {
      const response = await fetch(`/api/agent/approvals/${approvalId}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approve", reviewer: "browser-e2e-admin" }),
      });
      return { status: response.status, payload: await response.json() };
    }, { approvalId: createPayload.approval.id });
    expect(approvalResponse.status).toBe(200);
    expect(approvalResponse.payload.status).toBe("executed");
  } finally {
    await adminContext.close();
  }

  await page.goto(`/blog/${createPayload.article.slug}`);
  await expect(page.locator(".md-editor-preview")).toHaveCount(0);
  await expect(page.locator(".vditor-wysiwyg")).toContainText("01 中文段落");
  await expect(page.getByRole("button", { name: "编辑文章" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "阅读模式" })).toHaveCount(0);
  await page.locator('.vditor-wysiwyg p').filter({ hasText: "这是中文博客正文" }).click();
  await expect.poll(() => page.evaluate(() => window.getSelection()?.anchorNode?.parentElement?.closest("p")?.textContent ?? ""))
    .toContain("这是中文博客正文");
  await expect(page.locator(".article-content-wrapper.is-editing > .article-outline")).toBeVisible();
  await expect(page.locator(".inline-article-editor .vditor-outline")).toBeHidden();
  const editorLayout = await page.locator(".article-content-wrapper.is-editing").evaluate((element) => {
    const outline = element.querySelector(":scope > .article-outline");
    const body = element.querySelector(".vditor-wysiwyg");
    return {
      outlineWidth: outline?.getBoundingClientRect().width ?? 0,
      bodyWidth: body?.getBoundingClientRect().width ?? 0,
      combinedShare: ((outline?.getBoundingClientRect().width ?? 0) + (body?.getBoundingClientRect().width ?? 0)) / window.innerWidth,
    };
  });
  expect(editorLayout.outlineWidth).toBeGreaterThan(150);
  expect(editorLayout.bodyWidth).toBeGreaterThan(0);
  expect(editorLayout.combinedShare).toBeGreaterThanOrEqual(0.7);
  const h3 = page.locator(".inline-article-editor .vditor-wysiwyg h3").first();
  const headingMarker = () => h3.evaluate((element) => getComputedStyle(element, "::before").content);
  await expect.poll(headingMarker).toBe("none");
  await page.getByRole("button", { name: "显示标题层级" }).click();
  await expect.poll(headingMarker).toContain("H3");
  await page.getByRole("button", { name: "隐藏标题层级" }).click();
  await expect.poll(headingMarker).toBe("none");
  const outlineTop = await page.locator(".article-outline").evaluate((element) => element.getBoundingClientRect().top);
  await page.locator(".article-main").evaluate((element) => { element.scrollTop = 1400; });
  await expect.poll(() => page.locator(".article-main").evaluate((element) => element.scrollTop)).toBeGreaterThan(500);
  await expect.poll(() => page.locator(".article-outline").evaluate((element) => element.getBoundingClientRect().top)).toBe(outlineTop);
  await expect.poll(() => page.locator(".inline-article-editor .vditor-toolbar").evaluate((element) => {
    const toolbar = element.getBoundingClientRect();
    const main = element.closest(".article-main")!.getBoundingClientRect();
    return toolbar.top >= main.top && toolbar.top <= main.top + 120 && toolbar.bottom <= main.bottom && toolbar.height > 0;
  })).toBe(true);
  const mainScroll = await page.locator(".article-main").evaluate((element) => element.scrollTop);
  await page.locator(".article-outline").evaluate((element) => { element.scrollTop = 150; });
  expect(await page.locator(".article-outline").evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  expect(await page.locator(".article-main").evaluate((element) => element.scrollTop)).toBe(mainScroll);
  await page.locator(".article-outline .outline-item").filter({ hasText: "09 表格" }).click();
  await expect.poll(() => page.locator(".inline-article-editor .vditor-wysiwyg h2").filter({ hasText: "09 表格" }).evaluate((element) => {
    const main = element.closest(".article-main")!;
    return Math.round(element.getBoundingClientRect().top - main.getBoundingClientRect().top);
  })).toBeLessThan(60);
  await page.setViewportSize({ width: 390, height: 720 });
  const narrowLayout = await page.locator(".article-content-wrapper.is-editing").evaluate((element) => {
    const outline = element.querySelector(":scope > .article-outline")!.getBoundingClientRect();
    const main = element.querySelector(":scope > .article-main")!.getBoundingClientRect();
    return { outlineBottom: outline.bottom, mainTop: main.top, mainWidth: main.width };
  });
  expect(narrowLayout.outlineBottom).toBeLessThanOrEqual(narrowLayout.mainTop + 1);
  expect(narrowLayout.mainWidth).toBeGreaterThan(300);
  await page.setViewportSize({ width: 1280, height: 720 });
  const editorColors = await page.locator('.inline-article-editor .vditor-wysiwyg').evaluate((element) => {
    const styles = getComputedStyle(element);
    return { background: styles.backgroundColor, foreground: styles.color };
  });
  expect(editorColors.background).not.toBe(editorColors.foreground);
  expect(editorColors.background).not.toBe("rgb(23, 36, 32)");
  const readContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const readPage = await readContext.newPage();
  await login(readPage, reader);
  await readPage.goto(`/blog/${createPayload.article.slug}`);
  const preview = readPage.locator(".md-editor-preview");
  await expect(readPage.locator('.vditor-wysiwyg')).toHaveCount(0);
  await expect(readPage.locator('.article-main [contenteditable="true"]')).toHaveCount(0);
  await expect(preview).toBeVisible();
  await expect(preview.locator("h2").first()).toHaveAttribute("id", "heading-1");
  await expect(preview.locator("table tr")).toHaveCount(3);
  await expect(preview.locator("blockquote")).toContainText("刷新后恢复");
  await expect(preview.locator("pre code").filter({ hasText: "console.log(answer)" })).toBeVisible();
  const readingLayout = await preview.evaluate((root) => {
    const code = Array.from(root.querySelectorAll("pre")).find((item) => item.textContent?.includes("console.log(answer)"));
    const details = code?.closest("details");
    const table = root.querySelector("table");
    const row = table?.querySelector("tr");
    return {
      rootWhiteSpace: getComputedStyle(root).whiteSpace,
      codeWhiteSpace: code ? getComputedStyle(code).whiteSpace : null,
      codeDisplay: code?.firstElementChild ? getComputedStyle(code.firstElementChild).display : null,
      codeColor: code?.firstElementChild ? getComputedStyle(code.firstElementChild).color : null,
      codeBackground: code?.firstElementChild ? getComputedStyle(code.firstElementChild).backgroundColor : null,
      detailsClass: details?.className ?? "",
      summaryClass: details?.querySelector("summary")?.className ?? "",
      summaryHeight: details?.querySelector("summary")?.getBoundingClientRect().height ?? 0,
      detailsHeight: details?.getBoundingClientRect().height ?? 0,
      tableRowHeight: row?.getBoundingClientRect().height ?? 0,
    };
  });
  expect(readingLayout.rootWhiteSpace).toBe("normal");
  expect(readingLayout.codeWhiteSpace).toBe("pre");
  expect(readingLayout.codeDisplay).toBe("block");
  expect(readingLayout.codeColor).not.toBe(readingLayout.codeBackground);
  expect(readingLayout.detailsClass).toContain("md-editor-code");
  expect(readingLayout.summaryClass).toContain("md-editor-code-head");
  expect(readingLayout.summaryHeight).toBeLessThan(45);
  expect(readingLayout.detailsHeight).toBeLessThan(190);
  expect(readingLayout.tableRowHeight).toBeLessThan(80);
  const codeHeading = preview.locator("h2").filter({ hasText: "06 JavaScript" });
  const codeBlock = preview.locator("pre code").filter({ hasText: "console.log(answer)" });
  const codeSection = codeHeading.locator("xpath=following-sibling::*[1]");
  await expect(codeSection).toHaveClass(/collapsible-section-wrapper/);
  expect(await codeSection.evaluate((element) => getComputedStyle(element).maxHeight)).toBe("none");
  await codeHeading.locator(".section-toggle-btn").click();
  await expect(codeBlock).toBeHidden();
  await codeHeading.locator(".section-toggle-btn").click();
  await expect(codeBlock).toBeVisible();
  const tableHeading = preview.locator("h2").filter({ hasText: "09 表格" });
  await readPage.locator(".article-outline .outline-item").filter({ hasText: "09 表格" }).click();
  await expect.poll(() => tableHeading.evaluate((element) => {
    const main = element.closest(".article-main")!;
    return Math.round(element.getBoundingClientRect().top - main.getBoundingClientRect().top);
  })).toBeLessThan(45);
  expect(await tableHeading.evaluate((element) => {
    const main = element.closest(".article-main")!;
    return element.getBoundingClientRect().top - main.getBoundingClientRect().top;
  })).toBeLessThan(45);
  const nestedHeading = preview.locator("h3").filter({ hasText: "子标题" });
  await preview.locator("h2").filter({ hasText: "02 多级标题" }).locator(".section-toggle-btn").click();
  await expect(nestedHeading).toBeHidden();
  await readPage.locator(".article-outline .outline-item").filter({ hasText: "子标题" }).click();
  await expect(nestedHeading).toBeVisible();
  await expect.poll(() => nestedHeading.evaluate((element) => {
    const main = element.closest(".article-main")!;
    return Math.round(element.getBoundingClientRect().top - main.getBoundingClientRect().top);
  })).toBeLessThan(45);
  await readPage.setViewportSize({ width: 1280, height: 720 });
  await expect(readPage.locator(".article-content-wrapper.has-outline > .article-outline")).toBeVisible();
  await readPage.locator(".article-outline .outline-item").filter({ hasText: "09 表格" }).click();
  await expect.poll(() => tableHeading.evaluate((element) => {
    const main = element.closest(".article-main")!;
    return Math.round(element.getBoundingClientRect().top - main.getBoundingClientRect().top);
  })).toBeLessThan(45);
  await readPage.setViewportSize({ width: 390, height: 720 });
  await expect(readPage.locator(".article-content-wrapper.has-outline > .article-outline")).toBeVisible();
  const readerNarrowLayout = await readPage.locator(".article-content-wrapper.has-outline").evaluate((element) => {
    const outline = element.querySelector(":scope > .article-outline")!.getBoundingClientRect();
    const main = element.querySelector(":scope > .article-main")!.getBoundingClientRect();
    return { outlineBottom: outline.bottom, mainTop: main.top, mainWidth: main.width };
  });
  expect(readerNarrowLayout.outlineBottom).toBeLessThanOrEqual(readerNarrowLayout.mainTop + 1);
  expect(readerNarrowLayout.mainWidth).toBeGreaterThan(300);
  await expect(preview.locator("h2")).toHaveCount(20);
  await expect(preview.locator("script")).toHaveCount(0);
  const unsafeImageHandlers = await preview.locator("img").evaluateAll((images) =>
    images.filter((image) => image.hasAttribute("onerror")).length,
  );
  expect(unsafeImageHandlers).toBe(0);
  expect(await readPage.evaluate(() => (window as Window & { __blogDraftXss?: boolean }).__blogDraftXss)).toBeUndefined();

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.locator('.vditor-wysiwyg p').filter({ hasText: "使用 transaction.atomic()" }).locator("code").click();
  await expect.poll(() => page.evaluate(() => window.getSelection()?.anchorNode?.textContent?.replace(/[\u200b-\u200d\ufeff]/g, "") ?? ""))
    .toContain("transaction.atomic()");
  await expect.poll(() => page.evaluate(() => {
    const anchor = window.getSelection()?.anchorNode?.parentElement;
    const main = anchor?.closest('.article-main');
    if (!anchor || !main) return false;
    const caret = anchor.getBoundingClientRect();
    const viewport = main.getBoundingClientRect();
    const toolbar = main.querySelector('.inline-article-editor .vditor-toolbar')?.getBoundingClientRect();
    return caret.top >= Math.max(viewport.top + 20, (toolbar?.bottom ?? viewport.top) + 8) && caret.bottom <= viewport.bottom - 20;
  })).toBe(true);
  await page.keyboard.type("Verified");
  await expect(page.locator('.vditor-wysiwyg')).toContainText("Verified");
  const inlineSaveResponse = page.waitForResponse((response) =>
    response.url().includes("/api/agent/blog/articles/") && response.request().method() === "PUT"
  );
  await page.getByRole("button", { name: "保存并提交审核" }).click();
  const inlineSave = await inlineSaveResponse;
  expect(inlineSave.status()).toBe(202);
  await expect(page.locator(".inline-article-editor .vditor-wysiwyg")).toBeVisible();
  await expect(page.locator(".md-editor-preview")).toHaveCount(0);
  const inlinePayload = await inlineSave.json();
  const verifyContext = await browser.newContext();
  try {
    const adminPage = await verifyContext.newPage();
    await login(adminPage, admin);
    const approval = await adminPage.evaluate(async (id) => {
      const response = await fetch(`/api/agent/approvals/${id}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approve" }),
      });
      return (await response.json()).status;
    }, inlinePayload.approval.id);
    expect(approval).toBe("executed");
  } finally {
    await verifyContext.close();
  }
  await readPage.reload();
  const revisedPreview = readPage.locator(".md-editor-preview");
  await expect(revisedPreview.locator("h2")).toHaveCount(20);
  await expect(revisedPreview.locator("table tr")).toHaveCount(3);
  await expect(revisedPreview.locator("blockquote")).toContainText("刷新后恢复");
  await expect(revisedPreview.locator("pre code").filter({ hasText: "console.log(answer)" })).toBeVisible();
  await expect(revisedPreview.locator("script")).toHaveCount(0);
  await expect(revisedPreview).toContainText("Verified");
  await readContext.close();

});

test("guest can read a published default-workspace article by direct link", async ({ page }) => {
  await page.goto("/blog");
  await expect(page.getByRole("heading", { name: "技术笔记与项目实践" })).toBeVisible();
  await expect(page.getByRole("button", { name: "写博客", exact: true })).toHaveCount(0);
  const firstArticle = page.locator(".article-card").first();
  await expect(firstArticle).toBeVisible();
  const title = await firstArticle.locator("h2").innerText();
  await firstArticle.click();
  await expect(page).toHaveURL(/\/blog\/[^/]+$/);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByRole("link", { name: "登录后参与评论" })).toBeVisible();
  await expect(page.getByRole("button", { name: "删除", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "同步到知识库" })).toHaveCount(0);
  await page.getByRole("button", { name: "让 Agent 总结" }).click();
  await expect(page.getByPlaceholder("问公开博客内容，例如：这个项目架构是什么？")).toHaveValue(/原文依据/);
  await page.reload();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
});

test("public comment sidebar and article footer render one page at a time", async ({ page }) => {
  const comments = Array.from({ length: 120 }, (_, index) => ({
    id: index + 1,
    author_name: `reader-${index + 1}`,
    content: `discussion-${index + 1}`,
    quote: index % 2 ? `quoted passage ${index + 1}` : "",
    anchor_offset: null,
    created_at: "2026-10-02T00:00:00Z",
  }));
  await page.route(/\/api\/agent\/blog\/articles\/[^/]+\/comments\/\?/, async (route) => {
    const url = new URL(route.request().url());
    const kind = url.searchParams.get("kind");
    const before = Number(url.searchParams.get("before_id") || Infinity);
    const items = comments.filter((item) => Boolean(item.quote) === (kind === "quote") && item.id < before)
      .sort((a, b) => b.id - a.id).slice(0, 21);
    await route.fulfill({ json: {
      items: items.slice(0, 20),
      total: 60,
      next_before_id: items.length > 20 ? items[19].id : null,
    } });
  });
  await page.goto("/blog");
  await page.locator(".article-card").first().click();
  await expect(page.locator(".public-annotation-card")).toHaveCount(20);
  await expect(page.getByRole("navigation", { name: "划线评论翻页" })).toContainText("共 60");
  await page.getByRole("navigation", { name: "划线评论翻页" }).getByRole("button", { name: "更早评论" }).click();
  await expect(page.locator(".public-annotation-card").first()).toContainText("discussion-80");
  await expect(page.locator(".public-annotation-card")).toHaveCount(20);
  await page.locator(".comment-section").scrollIntoViewIfNeeded();
  await expect(page.locator(".comment-item")).toHaveCount(20);
  await page.getByRole("navigation", { name: "普通评论翻页" }).getByRole("button", { name: "更早评论" }).click();
  await expect(page.locator(".comment-item").first()).toContainText("discussion-79");
  await expect(page.locator(".comment-item")).toHaveCount(20);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  const sidebarToggle = page.getByRole("button", { name: /高亮与评论/ });
  await expect(sidebarToggle).toBeVisible();
  await expect(sidebarToggle).toHaveAttribute("aria-expanded", "false");
  await sidebarToggle.click();
  await expect(page.locator(".public-annotation-card")).toHaveCount(20);
});

test("private reading note survives refresh, stays account-private, and restores after deletion", async ({ page, browser }) => {
  test.setTimeout(120_000);
  await serveInstalledVditorAssets(page);
  await login(page, operatorA);
  const created = await page.evaluate(async () => {
    const response = await fetch("/api/agent/blog/articles/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: `Private note source ${Date.now()}`, content: "## Reading point\n\nA useful paragraph to quote." })
    });
    return response.json();
  });
  const adminContext = await browser.newContext();
  try {
    const adminPage = await adminContext.newPage();
    await login(adminPage, admin);
    const approval = await adminPage.evaluate(async (id: number) => {
      const response = await fetch(`/api/agent/approvals/${id}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approve" })
      });
      return response.status;
    }, created.approval.id);
    expect(approval).toBe(200);
  } finally {
    await adminContext.close();
  }
  await page.goto(`/blog/${created.article.slug}`);
  await expect(page.getByRole("button", { name: "笔记本" })).toBeVisible();
  await page.locator(".inline-article-editor .vditor-wysiwyg p").first().evaluate((paragraph) => {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(paragraph);
    selection?.removeAllRanges();
    selection?.addRange(range);
    paragraph.closest(".article-main")?.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  });
  await expect(page.getByRole("region", { name: "当前选中的文字" })).toContainText("A useful paragraph to quote.");
  await page.getByRole("button", { name: "高亮", exact: true }).click();
  await expect(page.locator(".annotation-card")).toHaveCount(1);
  await expect.poll(() => page.evaluate(() => CSS.highlights?.get("blog-private-annotations")?.size ?? 0)).toBeGreaterThan(0);
  await page.locator(".inline-article-editor .vditor-wysiwyg p").first().evaluate((paragraph) => {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(paragraph);
    selection?.removeAllRanges();
    selection?.addRange(range);
    paragraph.closest(".article-main")?.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  });
  await page.getByRole("textbox", { name: "旁注内容" }).fill("这段文字值得回看。");
  await page.getByRole("button", { name: "保存旁注" }).click();
  await expect(page.locator(".annotation-card")).toHaveCount(2);
  await expect(page.locator(".annotation-card").filter({ hasText: "这段文字值得回看。" })).toBeVisible();
  await page.locator(".inline-article-editor .vditor-wysiwyg p").first().evaluate((paragraph) => {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(paragraph);
    selection?.removeAllRanges();
    selection?.addRange(range);
    paragraph.closest(".article-main")?.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  });
  await page.getByRole("textbox", { name: "公开划线评论" }).fill("公开讨论这一段。");
  const publicCommentResponse = page.waitForResponse((response) => response.request().method() === "POST" && response.url().includes("/comments/"));
  await page.getByRole("button", { name: "提交公开评论" }).click();
  expect((await publicCommentResponse).status()).toBe(201);
  await expect(page.locator(".public-annotation-card")).toContainText("公开讨论这一段。");
  await page.getByRole("button", { name: /高亮与评论/ }).click();
  await expect(page.getByRole("complementary", { name: "高亮与侧边评论" })).toHaveAttribute("class", /collapsed/);
  await page.getByRole("button", { name: /高亮与评论/ }).click();
  const readerContext = await browser.newContext();
  try {
    const readerPage = await readerContext.newPage();
    await login(readerPage, reader);
    await readerPage.goto(`/blog/${created.article.slug}`);
    await expect(readerPage.locator(".public-annotation-card")).toContainText("公开讨论这一段。");
    await expect(readerPage.locator(".annotation-card")).toHaveCount(1);
  } finally {
    await readerContext.close();
  }
  await expect(page.locator('.vditor-wysiwyg [contenteditable="true"]')).toContainText("A useful paragraph to quote.");
  await expect.poll(() => page.evaluate(() => CSS.highlights?.get("blog-private-annotations")?.size ?? 0)).toBeGreaterThan(0);
  await page.locator(".inline-article-editor .vditor-wysiwyg p").first().evaluate((paragraph) => {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(paragraph);
    selection?.removeAllRanges();
    selection?.addRange(range);
  });
  await page.getByRole("button", { name: "笔记本" }).click();
  await expect(page.getByText("我的私有笔记")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "摘录" })).toBeVisible();
  const title = `私人阅读记录${Date.now()}`;
  await page.getByRole("textbox", { name: "笔记标题" }).fill(title);
  await page.locator('.private-notes-editor .vditor-wysiwyg [contenteditable="true"]').fill("仅本人可见的记录");
  await page.getByRole("button", { name: "保存笔记" }).click();
  await expect(page.getByText("笔记已私密保存")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "笔记本" }).click();
  await page.getByRole("textbox", { name: "搜索私有笔记" }).fill(title);
  await page.getByRole("button", { name: "查找" }).click();
  await expect(page.getByRole("button", { name: new RegExp(title) })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(title) }).click();
  await expect(page.locator(".private-notes-editor .vditor-wysiwyg")).toContainText("仅本人可见的记录");

  const otherContext = await browser.newContext();
  try {
    const otherPage = await otherContext.newPage();
    await login(otherPage, operatorB);
    await otherPage.getByRole("button", { name: "我的笔记" }).click();
    await otherPage.getByRole("textbox", { name: "搜索私有笔记" }).fill(title);
    await otherPage.getByRole("button", { name: "查找" }).click();
    await expect(otherPage.getByText("回收站为空")).toHaveCount(0);
    await expect(otherPage.getByRole("button", { name: new RegExp(title) })).toHaveCount(0);
  } finally {
    await otherContext.close();
  }

  await page.locator(".private-note-row").getByRole("button", { name: "删除" }).click();
  await page.getByRole("dialog", { name: "删除笔记" }).getByRole("button", { name: "删除" }).click();
  await expect(page.getByRole("button", { name: new RegExp(title) })).toHaveCount(0);
  await page.getByText("查看回收站").click();
  await expect(page.getByRole("button", { name: "恢复" })).toBeVisible();
  await page.getByRole("button", { name: "恢复" }).click();
  await page.getByText("查看回收站").click();
  await expect(page.getByRole("button", { name: new RegExp(title) })).toBeVisible();
});

test("note summary uses the writing endpoint only on request and stays editable and private", async ({ page }) => {
  await serveInstalledVditorAssets(page);
  await login(page, operatorA);
  const titles = [`Summary source A ${Date.now()}`, `Summary source B ${Date.now()}`];
  const noteIds = await page.evaluate(async (names) => {
    const ids: number[] = [];
    for (const [index, title] of names.entries()) {
      const response = await fetch("/api/agent/blog/notes/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, content: `Evidence ${index + 1}` })
      });
      if (response.status !== 201) throw new Error(`note setup failed: ${response.status}`);
      ids.push((await response.json()).id);
    }
    return ids;
  }, titles);
  let modelRequests = 0;
  await page.route("**/api/agent/blog/writing-agent/generate/", async (route) => {
    const body = route.request().postDataJSON();
    expect(body.mode).toBe("note_summary");
    expect(body.note_ids).toEqual(noteIds);
    expect(body.draft).toBeUndefined();
    modelRequests++;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        markdown: `## 汇总\n\nEvidence 1 [笔记#${noteIds[0]}]；Evidence 2 [笔记#${noteIds[1]}]。`,
        mode: "note_summary",
        model: "browser-mock-writer",
        api_key_source: "shared",
        generated_at: new Date().toISOString(),
        truncated: false,
        sources: noteIds.map((noteId, index) => ({ note_id: noteId, title: titles[index], included_chars: 10, truncated: false }))
      })
    });
  });
  await page.getByRole("button", { name: "我的笔记" }).click();
  for (const title of titles) {
    await page.locator(".private-note-row").filter({ hasText: title }).locator(".el-checkbox").click();
  }
  await expect(page.getByText("已选 2 条", { exact: false })).toBeVisible();
  expect(modelRequests).toBe(0);
  await page.getByRole("button", { name: "汇总已选笔记" }).click();
  await expect(page.getByText("browser-mock-writer", { exact: false })).toBeVisible();
  await expect(page.locator(".private-notes-summary .vditor-wysiwyg")).toContainText("Evidence 1");
  expect(modelRequests).toBe(1);
  await page.getByRole("button", { name: "存为私有笔记" }).click();
  await expect(page.getByText("汇总已保存为私有笔记，可继续修改")).toBeVisible();
  await expect(page.locator(".private-note-row").filter({ hasText: "笔记汇总" })).toBeVisible();
});

test("article search survives detail navigation and offers a clear empty state", async ({ page }) => {
  await page.goto("/blog?q=LangGraph");
  await expect(page.getByPlaceholder("输入算法、框架或项目关键词")).toHaveValue("LangGraph");
  const results = page.locator(".article-card");
  await expect(results.first()).toBeVisible();
  const matchingTitle = await results.first().locator("h2").innerText();
  await results.first().click();
  await expect(page).toHaveURL(/\/blog\/[^?]+\?q=LangGraph/);
  await expect(page.getByRole("heading", { name: matchingTitle })).toBeVisible();
  await page.getByRole("button", { name: "返回文章列表" }).click();
  await expect(page).toHaveURL(/\/blog\?q=LangGraph/);
  await expect(page.getByPlaceholder("输入算法、框架或项目关键词")).toHaveValue("LangGraph");

  await page.getByPlaceholder("输入算法、框架或项目关键词").fill("no-such-article-2026");
  await page.getByRole("button", { name: "搜索" }).click();
  await expect(page.getByText("没有找到符合条件的文章")).toBeVisible();
  await page.getByRole("button", { name: "清除筛选" }).click();
  await expect(page.locator(".article-card").first()).toBeVisible();
  await expect(page).toHaveURL(/\/blog$/);
});

test("published article revision keeps the reader page stable until approval", async ({ page, browser }) => {
  await serveInstalledVditorAssets(page);
  await login(page, operatorA);
  const oldTitle = `Public old version ${Date.now()}`;
  const created = await page.evaluate(async (title) => {
    const response = await fetch("/api/agent/blog/articles/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, content: "旧版公开正文" }),
    });
    return { status: response.status, payload: await response.json() };
  }, oldTitle);
  expect(created.status).toBe(202);

  const adminContext = await browser.newContext();
  const readerContext = await browser.newContext();
  try {
    const adminPage = await adminContext.newPage();
    const readerPage = await readerContext.newPage();
    await login(adminPage, admin);
    await login(readerPage, reader);
    const approve = async (approvalId: number) => adminPage.evaluate(async (id) => {
      const response = await fetch(`/api/agent/approvals/${id}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approve" }),
      });
      return { status: response.status, payload: await response.json() };
    }, approvalId);
    expect((await approve(created.payload.approval.id)).payload.status).toBe("executed");

    const slug = created.payload.article.slug;
    await readerPage.goto(`/blog/${slug}`);
    await expect(readerPage.getByRole("heading", { name: oldTitle })).toBeVisible();
    await expect(readerPage.getByRole("button", { name: "编辑文章" })).toHaveCount(0);
    await page.goto(`/blog/${slug}`);
    await expect(page.locator(".md-editor-preview")).toHaveCount(0);
    await expect(page.locator(".vditor-wysiwyg")).toBeVisible();
    await expect(page.locator(".vditor-wysiwyg")).toContainText("旧版公开正文");
    await expect(page.locator('.vditor-toolbar [data-type="edit-mode"]')).toHaveCount(0);
    await page.getByRole("textbox", { name: "编辑文章标题" }).fill("审核后的新版");
    const visualBody = page.locator('.vditor-wysiwyg [contenteditable="true"]');
    await visualBody.locator("p").first().click();
    await visualBody.press("End");
    await visualBody.pressSequentially(" 新版待审正文");
    await expect(page.locator(".vditor-wysiwyg")).toContainText("新版待审正文");
    await expect(page.getByRole("status")).toContainText("修改已自动保存在本机");
    await expect.poll(() => page.evaluate(() => {
      const key = Object.keys(localStorage).find((item) => item.startsWith("blogWriterDraft:v2:") && item.includes("article"));
      return key ? JSON.parse(localStorage.getItem(key) || "{}").draft?.content || "" : "";
    })).toContain("新版待审正文");
    page.once("dialog", (dialog) => dialog.accept());
    await page.reload();
    await expect(page.locator(".md-editor-preview")).toHaveCount(0);
    await expect(page.getByText("已从本机恢复未提交的修改。")).toBeVisible();
    await expect(page.getByRole("textbox", { name: "编辑文章标题" })).toHaveValue("审核后的新版");
    await expect(page.locator(".vditor-wysiwyg")).toContainText("新版待审正文");
    const revisionResponse = page.waitForResponse((response) =>
      response.url().includes(`/api/agent/blog/articles/${slug}/`) && response.request().method() === "PUT"
    );
    await page.getByRole("button", { name: "保存并提交审核" }).click();
    const revisionHttp = await revisionResponse;
    const revision = { status: revisionHttp.status(), payload: await revisionHttp.json() };
    expect(revision.status).toBe(202);
    const pending = await page.evaluate(async (articleSlug) => {
      const response = await fetch(`/api/agent/blog/articles/${articleSlug}/`);
      return response.json();
    }, slug);
    expect(pending.pending_revision.content).toContain("新版待审正文");
    await readerPage.reload();
    await expect(readerPage.getByRole("heading", { name: oldTitle })).toBeVisible();
    await expect(readerPage.locator(".md-editor-preview")).toContainText("旧版公开正文");
    await expect(readerPage.locator(".md-editor-preview")).not.toContainText("新版待审正文");

    expect((await approve(revision.payload.approval.id)).payload.status).toBe("executed");
    await readerPage.reload();
    await expect(readerPage.getByRole("heading", { name: "审核后的新版" })).toBeVisible();
    await expect(readerPage.locator(".md-editor-preview")).toContainText("新版待审正文");
  } finally {
    await adminContext.close();
    await readerContext.close();
  }
});

test("reader comment publishes immediately, then report and admin hide stay consistent", async ({ page, browser }) => {
  await login(page, operatorA);
  const title = `评论发布浏览器测试${Date.now()}`;
  const commentText = `这条评论直接公开 ${Date.now()}`;
  const create = await page.evaluate(async (articleTitle) => {
    const response = await fetch("/api/agent/blog/articles/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: articleTitle, content: "评论发布测试文章" }),
    });
    return { status: response.status, payload: await response.json() };
  }, title);
  expect(create.status).toBe(202);

  const adminContext = await browser.newContext();
  try {
    const adminPage = await adminContext.newPage();
    await login(adminPage, admin);
    const approval = await adminPage.evaluate(async (approvalId) => {
      const response = await fetch(`/api/agent/approvals/${approvalId}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approve", reviewer: "browser-e2e-admin" }),
      });
      return response.status;
    }, create.payload.approval.id);
    expect(approval).toBe(200);

    await page.goto(`/blog/${create.payload.article.slug}`);
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
    await page.getByPlaceholder("写下你的想法").fill(commentText);
    const submittedComment = page.waitForResponse((response) => response.request().method() === "POST" && response.url().includes("/comments/"));
    await page.getByRole("button", { name: "发表评论" }).click();
    expect((await submittedComment).status()).toBe(201);
    await expect(page.locator(".comment-item")).toContainText(commentText);

    await adminPage.goto("/blog");
    await adminPage.getByRole("button", { name: "评论管理" }).click();
    const dialog = adminPage.getByRole("dialog", { name: "评论管理" });
    await expect(dialog.getByText(commentText)).toBeVisible();
    await page.getByRole("button", { name: "举报评论" }).click();
    const reportDialog = page.getByRole("dialog", { name: "举报评论" });
    await reportDialog.getByPlaceholder("补充说明（可选）").fill("浏览器举报测试");
    await reportDialog.getByRole("button", { name: "提交举报" }).click();
    await expect(page.getByText("举报已提交，管理员会处理。")).toBeVisible();

    await adminPage.getByRole("button", { name: "举报待处理" }).click();
    await expect(dialog.getByText(commentText)).toBeVisible();
    await expect(dialog.getByText("浏览器举报测试")).toBeVisible();
    await dialog.getByRole("button", { name: "隐藏评论" }).click();
    await expect(dialog.getByText(commentText)).toHaveCount(0);
    await page.reload();
    await expect(page.locator(".comment-item")).toHaveCount(0);
  } finally {
    await adminContext.close();
  }
});

test("drafts isolate two tabs and accounts, recover after refresh/offline, and survive server save failure", async ({ page }) => {
  await serveInstalledVditorAssets(page);
  await login(page, operatorA);
  await openWriter(page);
  await importMarkdown(page, "Account A private title", "## OWNER-A-CONTENT\n\n这是账号 A 的私有草稿。\n");

  const secondTab = await page.context().newPage();
  await serveInstalledVditorAssets(secondTab);
  await secondTab.goto("/blog");
  await openWriter(secondTab);
  await importMarkdown(secondTab, "Account A second tab", "## OWNER-A-TAB-B\n\n第二个标签页的内容。\n");
  const cacheKeys = await page.evaluate(() => Object.keys(localStorage).filter((key) => key.startsWith("blogWriterDraft:v2:")));
  expect(new Set(cacheKeys).size).toBeGreaterThanOrEqual(2);
  await expect(page.locator(".draft-conflict-alert")).toHaveCount(0);
  await expect(secondTab.locator(".draft-conflict-alert")).toHaveCount(0);

  await page.reload();
  await expect(page.getByPlaceholder("文章标题")).toHaveValue("Account A private title");
  await expect(page.locator(".vditor-wysiwyg")).toContainText("OWNER-A-CONTENT");

  await page.context().setOffline(true);
  await expect(page.getByRole("status")).toContainText("网络已断开");
  await page.context().setOffline(false);
  await expect(page.getByRole("status")).toContainText("网络已恢复");

  await page.route("**/api/agent/blog/articles/", async (route) => {
    if (route.request().method() === "POST") await route.abort("failed");
    else await route.continue();
  });
  await page.getByRole("button", { name: "发布并加入知识库" }).first().click();
  await expect(page.locator(".editor-error")).toContainText(/Failed|fetch|网络|连接/i);
  await expect(page.getByRole("status")).toContainText(/本机草稿仍在|本机浏览器/);
  await page.unrouteAll();

  await page.getByRole("button", { name: "关闭", exact: true }).click();
  const seededArticles = await page.evaluate(async () => {
    const created = [];
    for (const title of ["B-010 article A", "B-010 article B"]) {
      const response = await fetch("/api/agent/blog/articles/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, summary: "Isolation fixture", content: `## ${title}\n\nServer source.` }),
      });
      if (!response.ok) throw new Error(`Could not create editor fixture (${response.status}).`);
      const payload = await response.json();
      created.push(payload.article);
    }
    return created;
  });
  await page.reload();
  await expect(page.getByRole("button", { name: "我的文章", exact: true })).toBeVisible();
  const articlePages: Page[] = [];
  for (let index = 0; index < seededArticles.length; index += 1) {
    const articleTitle = seededArticles[index].title as string;
    const articlePage = await page.context().newPage();
    articlePages.push(articlePage);
    await serveInstalledVditorAssets(articlePage);
    await articlePage.goto("/blog");
    await articlePage.getByRole("button", { name: "我的文章", exact: true }).click();
    await articlePage.locator(".my-note-item").filter({ has: articlePage.getByText(articleTitle, { exact: true }) }).getByRole("button", { name: "编辑" }).first().click();
    await importMarkdown(articlePage, `${articleTitle} local edit`, `## ARTICLE-${index + 1}-UNSAVED\n\nThis edit must remain attached to its article.`);
  }
  const articleCacheState = await page.evaluate(() => Object.entries(localStorage)
    .filter(([key]) => key.startsWith("blogWriterDraft:v2:") && key.includes("article%3A"))
    .map(([key, value]) => ({ key, content: JSON.parse(value).draft.content })));
  expect(articleCacheState.length).toBeGreaterThanOrEqual(2);
  expect(new Set(articleCacheState.map((entry) => entry.key)).size).toBe(articleCacheState.length);
  await page.keyboard.press("Escape");
  await Promise.all(articlePages.map((articlePage) => articlePage.close()));

  await secondTab.close();
  await page.getByRole("button", { name: "退出", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  const accountSwitchPage = await page.context().newPage();
  await serveInstalledVditorAssets(accountSwitchPage);
  await login(accountSwitchPage, operatorB);
  await openWriter(accountSwitchPage);
  await expect(accountSwitchPage.getByPlaceholder("文章标题")).toHaveValue("");
  await expect(accountSwitchPage.locator(".vditor-wysiwyg")).not.toContainText("OWNER-A-CONTENT");
  await accountSwitchPage.close();
});

test("same-article tabs pause conflicting saves and can recover the newer version", async ({ page, context }) => {
  await serveInstalledVditorAssets(page);
  await login(page, operatorA);
  const article = await page.evaluate(async () => {
    const response = await fetch("/api/agent/blog/articles/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "B-010 shared article", summary: "Conflict fixture", content: "## Server version" }),
    });
    if (!response.ok) throw new Error(`Could not create conflict fixture (${response.status}).`);
    return (await response.json()).article;
  });

  async function editSeededArticle(target: Page, content: string) {
    await target.goto("/blog");
    await target.getByRole("button", { name: "我的文章", exact: true }).click();
    await target.locator(".my-note-item")
      .filter({ has: target.getByText(article.title, { exact: true }) })
      .getByRole("button", { name: "编辑" }).first().click();
    await importMarkdown(target, "B-010 shared article edit", content);
  }

  await editSeededArticle(page, "## TAB-ONE-VERSION\n\n第一标签页内容。\n");
  const secondTab = await context.newPage();
  await serveInstalledVditorAssets(secondTab);
  await editSeededArticle(secondTab, "## TAB-TWO-VERSION\n\n第二标签页内容。\n");

  const conflict = page.locator(".draft-conflict-alert");
  await expect(page.getByRole("status")).toContainText("另一标签页修改了这篇草稿");
  await expect(conflict).toBeVisible();
  await expect(conflict).toContainText("自动保存已暂停");
  await conflict.getByRole("button", { name: "载入另一标签页版本" }).click();
  await expect(page.getByPlaceholder("文章标题")).toHaveValue("B-010 shared article edit");
  await expect(page.locator(".vditor-wysiwyg")).toContainText("TAB-TWO-VERSION");
  await expect(page.locator(".draft-conflict-alert")).toHaveCount(0);
  await secondTab.close();
});

test("admin comment restriction, user appeal, and lift work in the browser", async ({ page, browser }) => {
  const adminContext = await browser.newContext();
  const readerContext = await browser.newContext();
  try {
    const adminPage = await adminContext.newPage();
    const readerPage = await readerContext.newPage();
    await login(adminPage, admin);
    await login(readerPage, reader);
    await adminPage.getByRole("button", { name: "评论管理" }).click();
    const moderation = adminPage.getByRole("dialog", { name: "评论管理" });
    await moderation.getByRole("button", { name: "账号限制" }).click();
    await moderation.getByLabel("限制账号用户名").fill(reader);
    await moderation.getByLabel("限制原因").fill("Repeated spam after a clear warning");
    await moderation.getByRole("button", { name: "限制评论与举报" }).click();
    await expect(moderation.getByText(`${reader} · 限制中`)).toBeVisible();

    await readerPage.reload();
    await readerPage.getByRole("button", { name: "评论限制与申诉" }).click();
    const appeal = readerPage.getByRole("dialog", { name: "评论与举报状态" });
    await expect(appeal).toContainText("Repeated spam after a clear warning");
    await appeal.getByLabel("申诉说明").fill("I understand the rules and request another review.");
    await appeal.getByRole("button", { name: "提交申诉" }).click();
    await expect(appeal).toContainText("申诉已提交，等待管理员处理");

    await moderation.getByRole("button", { name: "账号限制" }).click();
    await expect(moderation).toContainText("I understand the rules and request another review.");
    await moderation.getByRole("button", { name: "接受申诉" }).click();
    await expect(moderation.getByText(`${reader} · 已结束`)).toBeVisible();
    await appeal.getByRole("button", { name: "刷新状态" }).click();
    await expect(appeal).toContainText("当前没有评论或举报限制");
  } finally {
    await adminContext.close();
    await readerContext.close();
  }
});
