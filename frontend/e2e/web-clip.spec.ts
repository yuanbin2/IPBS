/**
 * B-043 通用网页剪藏的站内接收路径（mock 扩展）。
 * 真实 Edge 侧载验收见 clip-extension.spec.ts。
 */

import { expect, test, type Page } from "@playwright/test";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const password = "Upload-e2e-only-2026!";
const operator = "upload-e2e-operator";
const nonce = "a".repeat(32);

const clipHtml =
  '<article><h1>两数之和</h1><p>给定一个整数数组和一个目标值，找出和为目标值的两个数。</p><pre><code class="language-python">def two_sum(nums, target): pass</code></pre></article>';

const META_NOTE = {
  ok: true,
  meta: {
    kind: "web",
    version: 2,
    sourceUrl: "https://example.org/post/two-sum",
    canonicalUrl: "https://example.org/post/two-sum",
    titleCandidate: "两数之和",
    siteCandidate: "example.org",
    captureMode: "article",
    captureTarget: "private_note",
    capturedAt: "2026-10-03T10:00:00.000Z",
    extractorVersion: "webclip-extract-1",
    htmlUtf8Bytes: new TextEncoder().encode(clipHtml).length,
    sha256: createHash("sha256").update(clipHtml).digest("hex"),
    ownNote: "",
    chunkCount: 1,
    warnings: [{ code: "IMAGE_REMOTE", count: 1 }],
  },
};

const META_DRAFT = { ...META_NOTE, meta: { ...META_NOTE.meta, captureTarget: "article_draft" } };

async function serveInstalledVditorAssets(page: Page) {
  const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../node_modules/vditor");
  await page.route(/^https:\/\/unpkg\.com\/vditor@4\.0\.0\/dist\/js\/(?:i18n|icons|lute)\/[\w.-]+\.js(?:\?.*)?$/, async (route) => {
    const path = new URL(route.request().url()).pathname.split("/vditor@4.0.0/")[1];
    await route.fulfill({ path: resolve(packageRoot, path) });
  });
}

async function login(page: Page, username = operator) {
  await page.goto("/login?redirect=%2Fblog");
  await page.getByPlaceholder("用户名").fill(username);
  await page.getByPlaceholder("密码，至少 8 位").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/blog$/);
}

/** 注入假扩展（须在首次 goto 前调用，保证登录页也在其作用下）。 */
async function installFakeWebClip(page: Page, bodySource: string) {
  await page.addInitScript(
    ({ source }) => {
      (window as unknown as { __clipCalls?: unknown[] }).__clipCalls = [];
      const calls = (window as unknown as { __clipCalls?: unknown[] }).__clipCalls as unknown[];
      const runtime = {
        sendMessage(extensionId: string, message: unknown, callback: (response: unknown) => void) {
          calls.push({ extensionId, message });
          const configured = new Function(`return (${source});`)();
          const response = typeof configured === "function" ? configured(message) : configured;
          callback(response);
        },
        lastError: undefined as { message?: string } | undefined,
      };
      (globalThis as unknown as { chrome?: unknown }).chrome = { runtime };
    },
    { source: bodySource },
  );
}

/** 成功返回 meta/chunk/ack 的假扩展脚本。 */
function successScript(meta: unknown, html = clipHtml): string {
  return `(message) => {
    if (message.type === "blog.webclip.get-meta") return (${JSON.stringify(meta)});
    if (message.type === "blog.webclip.get-chunk") return { ok: true, index: message.index, chunk: ${JSON.stringify(html)} };
    if (message.type === "blog.webclip.ack") return { ok: true };
    return { ok: false, code: "wrong_type" };
  }`;
}

test("web clip note keeps Markdown structure and stores matched images privately", async ({ page }) => {
  test.setTimeout(180_000);
  const html = '<article><h1>配图笔记</h1><p>这一段正文说明配图中的步骤和背景，确保服务端能识别为正文内容。</p><p>第二段说明将图片下载到私有附件后，刷新也应由本人正常读取。</p><img src="https://example.org/photo.png" alt="步骤图"></article>';
  const meta = {
    ...META_NOTE,
    meta: {
      ...META_NOTE.meta,
      titleCandidate: "配图笔记",
      htmlUtf8Bytes: new TextEncoder().encode(html).length,
      sha256: createHash("sha256").update(html).digest("hex"),
      ownNote: "我自己补充的来源说明",
    },
  };
  await serveInstalledVditorAssets(page);
  await installFakeWebClip(page, successScript(meta, html));
  await login(page, "upload-e2e-other");
  await openWebClipPage(page, `#clip=${nonce}&ext=mockext&kind=web`);

  const review = page.getByRole("dialog", { name: "从网页剪藏创建私有笔记" });
  await expect(review).toBeVisible();
  await expect(review.getByLabel("Markdown 排版预览").getByRole("img", { name: "步骤图" })).toBeVisible();
  const dataUrl = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 2;
    canvas.height = 2;
    canvas.getContext("2d")!.fillRect(0, 0, 2, 2);
    return canvas.toDataURL("image/png");
  });
  await review.getByLabel("选择配套图片文件", { exact: true }).first().setInputFiles({
    name: "photo.png",
    mimeType: "image/png",
    buffer: Buffer.from(dataUrl.split(",")[1], "base64"),
  });
  await review.getByRole("button", { name: "放入私有笔记编辑器" }).click();
  await expect(page.locator(".private-notes-drawer")).toBeVisible();
  await expect(page.locator(".private-notes-drawer .vditor-wysiwyg img")).toHaveAttribute("src", /^blob:/);
  await page.getByRole("button", { name: "保存私有笔记" }).click();
  await expect(page.getByText("笔记已私密保存")).toBeVisible();
  const notes = await page.evaluate(async () => (await (await fetch("/api/agent/blog/notes/?page_size=50")).json()).items);
  expect(notes).toHaveLength(1);
  expect(notes[0].title).toBe("配图笔记");
  expect(notes[0].content).toContain("第二段说明将图片下载到私有附件");
  expect(notes[0].content).toContain("我自己补充的来源说明");
  const match = notes[0].content.match(/\/api\/agent\/blog\/notes\/images\/(\d+)\//);
  expect(match).not.toBeNull();
  const image = await page.evaluate(async (url) => {
    const response = await fetch(url);
    return { status: response.status, type: response.headers.get("content-type") };
  }, match![0]);
  expect(image).toEqual({ status: 200, type: "image/png" });
  await page.reload();
  await page.getByRole("button", { name: "我的笔记" }).click();
  await page.locator(".private-note-row button").filter({ hasText: "配图笔记" }).click();
  await expect(page.locator(".private-notes-drawer .private-notes-markdown img")).toHaveAttribute("src", /^blob:/);
});

test("web clip can keep text when remote images cannot be imported", async ({ page }) => {
  test.setTimeout(180_000);
  const html = '<article><h1>只留文字</h1><p>这是一段可保存的文字，即使来源图片无法下载也不能丢失正文内容。</p><p>下一段解释图片可以明确忽略，之后在编辑器里补上自己的图片。</p><img src="https://example.org/missing.png" alt="暂缺配图"></article>';
  const meta = {
    ...META_NOTE,
    meta: {
      ...META_NOTE.meta,
      titleCandidate: "只留文字",
      htmlUtf8Bytes: new TextEncoder().encode(html).length,
      sha256: createHash("sha256").update(html).digest("hex"),
    },
  };
  const privateFetches: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/agent/blog/notes/images/fetch/")) privateFetches.push(request.url());
  });
  await serveInstalledVditorAssets(page);
  await installFakeWebClip(page, successScript(meta, html));
  await login(page, "upload-e2e-reader");
  await openWebClipPage(page, `#clip=${nonce}&ext=mockext&kind=web`);
  const review = page.getByRole("dialog", { name: "从网页剪藏创建私有笔记" });
  await expect(review.getByText(/外部图片 1 张/)).toBeVisible();
  await review.getByText("忽略远程图片，正文只保留文字提示").click();
  await review.getByRole("button", { name: "放入私有笔记编辑器" }).click();
  await page.getByRole("button", { name: "保存私有笔记" }).click();
  await expect(page.getByText("笔记已私密保存")).toBeVisible();
  const notes = await page.evaluate(async () => (await (await fetch("/api/agent/blog/notes/?page_size=50")).json()).items);
  expect(notes).toHaveLength(1);
  expect(notes[0].content).toContain("下一段解释图片可以明确忽略");
  expect(notes[0].content).not.toContain("https://example.org/missing.png");
  expect(privateFetches).toHaveLength(0);
});

async function openWebClipPage(page: Page, fragment: string) {
  await page.goto("about:blank");
  await page.goto(`/blog${fragment}`);
}

test("web clip defaults to a private note draft that only saves on explicit click", async ({ page }) => {
  test.setTimeout(180_000);
  await serveInstalledVditorAssets(page);
  await installFakeWebClip(page, successScript(META_NOTE));
  await login(page);
  await openWebClipPage(page, `#clip=${nonce}&ext=mockext&kind=web`);

  // 私有笔记先走现有 HTML 安全预览与区块选择，再进入未保存编辑器。
  const review = page.getByRole("dialog", { name: "从网页剪藏创建私有笔记" });
  await expect(review).toBeVisible({ timeout: 30000 });
  await expect(review.getByLabel("Markdown 排版预览")).toContainText("给定一个整数数组和一个目标值");
  await review.getByRole("button", { name: "放入私有笔记编辑器" }).click();
  await expect(page.locator(".private-notes-drawer")).toBeVisible({ timeout: 30000 });
  await expect(page.getByText("来自网页剪藏的未保存笔记")).toBeVisible();
  await expect(page.getByText("给定一个整数数组和一个目标值")).toBeVisible();
  await expect(page.locator(".clip-status-alert")).toContainText("剪藏已进入私有笔记编辑器");

  // fragment 已清，正文不在 URL / 历史里
  expect(page.url()).not.toContain("#clip=");
  expect(page.url()).not.toContain("two-sum");

  // 未点击保存时不产生任何笔记（页面内请求才带登录态）
  const notesBefore = await page.evaluate(async () => {
    const response = await fetch("/api/agent/blog/notes/?page_size=50");
    const payload = await response.json();
    return payload.items ?? [];
  });
  expect(notesBefore).toHaveLength(0);

  // 显式保存后才落库，并带来源
  await page.getByRole("button", { name: "保存私有笔记" }).click();
  await expect(page.getByText("笔记已私密保存")).toBeVisible({ timeout: 15000 });
  const notesAfter = await page.evaluate(async () => {
    const response = await fetch("/api/agent/blog/notes/?page_size=50");
    const payload = await response.json();
    return payload.items ?? [];
  });
  expect(notesAfter).toHaveLength(1);
  expect(notesAfter[0].source_url).toBe("https://example.org/post/two-sum");
  expect(notesAfter[0].source_title).toContain("example.org");

  // 刷新后仍在列表里
  await page.reload();
  await page.getByRole("button", { name: "我的笔记" }).click();
  await expect(page.locator(".private-notes-drawer")).toBeVisible();
  await expect(page.getByText("两数之和").first()).toBeVisible();
});

test("web clip to article draft goes through the HTML import preview", async ({ page }) => {
  test.setTimeout(180_000);
  await serveInstalledVditorAssets(page);
  await installFakeWebClip(page, successScript(META_DRAFT));
  await login(page);
  await openWebClipPage(page, `#clip=${nonce}&ext=mockext&kind=web`);

  await expect(page.getByRole("dialog", { name: "从 HTML 导入文章" })).toBeVisible({ timeout: 30000 });
  const dialog = page.getByRole("dialog", { name: "从 HTML 导入文章" });
  await expect(dialog.getByRole("textbox", { name: /原网页地址/ })).toHaveValue("https://example.org/post/two-sum");
  await expect(dialog.getByLabel("Markdown 排版预览")).toContainText("给定一个整数数组和一个目标值");
});

test("web clip failures are actionable and never touch the draft", async ({ page }) => {
  test.setTimeout(180_000);
  await serveInstalledVditorAssets(page);
  await installFakeWebClip(page, "() => ({ ok: false, code: 'expired', detail: '交接已过期，请从扩展重新发送' })");
  await login(page);
  await openWebClipPage(page, `#clip=${nonce}&ext=mockext&kind=web`);
  await expect(page.locator(".clip-status-alert")).toContainText("交接已过期");

  // 分片缺失
  await installFakeWebClip(
    page,
    `(message) => message.type === "blog.webclip.get-chunk" ? { ok: false, code: "chunk_missing", detail: "请求的分片不存在（共 1 片）" } : (${JSON.stringify(META_NOTE)})`,
  );
  await openWebClipPage(page, `#clip=${nonce}&ext=mockext&kind=web`);
  await expect(page.locator(".clip-status-alert")).toContainText("分片");

  // 字节数不符 → size_limit，且不发 ack
  await installFakeWebClip(
    page,
    `(message) => {
      if (message.type === "blog.webclip.get-meta") return (${JSON.stringify(META_NOTE)});
      if (message.type === "blog.webclip.get-chunk") return { ok: true, index: message.index, chunk: "tiny" };
      return { ok: false, code: "wrong_type" };
    }`,
  );
  await openWebClipPage(page, `#clip=${nonce}&ext=mockext&kind=web`);
  await expect(page.locator(".clip-status-alert")).toContainText("字节数");
  const calls = await page.evaluate(
    () => (window as unknown as { __clipCalls?: Array<{ message: { type: string } }> }).__clipCalls ?? [],
  );
  expect(calls.some((call) => call.message.type === "blog.webclip.ack")).toBe(false);

  // 同字节数但内容被篡改 → 哈希不符，不得 ack。
  await installFakeWebClip(
    page,
    `(message) => {
      if (message.type === "blog.webclip.get-meta") return (${JSON.stringify(META_NOTE)});
      if (message.type === "blog.webclip.get-chunk") return { ok: true, index: message.index, chunk: ${JSON.stringify(clipHtml.replace("两数之和", "三数之和"))} };
      return { ok: true };
    }`,
  );
  await openWebClipPage(page, `#clip=${nonce}&ext=mockext&kind=web`);
  await expect(page.locator(".clip-status-alert")).toContainText("校验失败");
  const tamperCalls = await page.evaluate(
    () => (window as unknown as { __clipCalls?: Array<{ message: { type: string } }> }).__clipCalls ?? [],
  );
  expect(tamperCalls.some((call) => call.message.type === "blog.webclip.ack")).toBe(false);

  // 无扩展运行时
  await installFakeWebClip(page, "handler");
  await page.addInitScript(() => {
    delete (globalThis as unknown as { chrome?: unknown }).chrome;
  });
  await openWebClipPage(page, `#clip=${nonce}&ext=mockext&kind=web`);
  await expect(page.locator(".clip-status-alert")).toContainText("未检测到浏览器扩展");
});

test("malformed web clip fragment is ignored without contacting the extension", async ({ page }) => {
  await serveInstalledVditorAssets(page);
  await installFakeWebClip(page, "handler");
  await login(page);
  await openWebClipPage(page, "#clip=not-a-nonce&ext=x&kind=web");
  await expect(page.locator(".clip-status-alert")).toHaveCount(0);
  const calls = await page.evaluate(() => (window as unknown as { __clipCalls?: unknown[] }).__clipCalls ?? []);
  expect(calls).toEqual([]);
});
