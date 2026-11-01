/**
 * B-045 真实侧载 E2E：用持久化 Edge profile 加载仓库 browser-extension/，
 * 验证 screenshot-v1 的跨扩展交接全链路——真实 service worker、真实
 * IndexedDB 暂存、真实 storage.session 元数据、真实 externally_connectable
 * 消息、真实博客页消费与本地 OCR。
 *
 * 与 B-043/B-044 的先例一致：工具栏图标的 activeTab 授予无法自动化，
 * 真实 captureVisibleTab 像素采集由人工按 browser-extension/README.md 步骤
 * 验收；这里用带真实文字的合成 PNG 代替采集到的 tile 字节，其余环节全部真实。
 */

import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { cpSync, mkdtempSync, readFileSync as readFile, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";

const password = "Upload-e2e-only-2026!";
const operator = "upload-e2e-operator";
const extensionRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../browser-extension");
const fixturesDir = resolve(dirname(fileURLToPath(import.meta.url)), "fixtures");
const frontendPort = process.env.E2E_FRONTEND_PORT || "5173";

const tilePng = readFileSync(resolve(fixturesDir, "ocr-zh-article.png"));
const tileSha256 = createHash("sha256").update(tilePng).digest("hex");
const tileBase64 = tilePng.toString("base64");

interface Harness {
  context: BrowserContext;
  extensionId: string;
  cleanup: () => Promise<void>;
}

async function launchWithExtension(testHostPermission = false): Promise<Harness> {
  const { chromium } = await import("playwright");
  const profileDir = mkdtempSync(resolve(tmpdir(), "blog-shot-e2e-"));
  const testExtensionDir = testHostPermission ? mkdtempSync(resolve(tmpdir(), "blog-shot-extension-")) : extensionRoot;
  if (testHostPermission) {
    cpSync(extensionRoot, testExtensionDir, { recursive: true });
    const manifestPath = resolve(testExtensionDir, "manifest.json");
    const manifest = JSON.parse(readFile(manifestPath, "utf8"));
    // 自动化无法点击浏览器工具栏来授予 activeTab；仅测试副本授予截图权限。
    // 生产扩展仍只有用户点击图标后才生效的 activeTab，无此权限。
    manifest.host_permissions = ["<all_urls>"];
    writeFileSync(manifestPath, JSON.stringify(manifest));
  }
  const context = await chromium.launchPersistentContext(profileDir, {
    headless: true,
    channel: "msedge",
    args: ["--headless=new", `--disable-extensions-except=${testExtensionDir}`, `--load-extension=${testExtensionDir}`],
  });
  let worker = context.serviceWorkers()[0];
  if (!worker) worker = await context.waitForEvent("serviceworker", { timeout: 45_000 });
  const extensionId = new URL(worker.url()).host;
  (context as unknown as { __shotWorker?: unknown }).__shotWorker = worker;
  return {
    context,
    extensionId,
    cleanup: async () => {
      await context.close();
      rmSync(profileDir, { recursive: true, force: true });
      if (testHostPermission) rmSync(testExtensionDir, { recursive: true, force: true });
    },
  };
}

function getWorker(context: BrowserContext) {
  return (context as unknown as { __shotWorker: { evaluate: <T>(fn: (arg: unknown) => T, arg?: unknown) => Promise<T> } }).__shotWorker;
}

test("真实侧载：最小权限 + popup 截图入口 + worker 会话 → 博客消费 → 本地 OCR → ack 清理", async ({ page: _page }) => {
  test.setTimeout(300_000);
  const harness = await launchWithExtension();
  const worker = getWorker(harness.context);
  try {
    // 1) manifest 权限最小化
    const manifestPage = await harness.context.newPage();
    await manifestPage.goto(`chrome-extension://${harness.extensionId}/manifest.json`);
    const manifest = JSON.parse(await manifestPage.locator("body").innerText());
    expect(manifest.manifest_version).toBe(3);
    // offscreen/downloads 只服务“仅保存图片”：前者给拼接长图一个有 DOM 的
    // 私有上下文，后者保存用户明确请求的截图；均不扩大页面侧可达范围。
    expect([...manifest.permissions].sort()).toEqual(
      ["activeTab", "downloads", "offscreen", "scripting", "storage"],
    );
    expect(manifest.host_permissions).toBeUndefined();
    const manifestText = JSON.stringify(manifest);
    expect(manifestText).not.toContain("<all_urls>");
    expect(manifestText).not.toContain("cookies");
    expect(manifestText).not.toContain("webRequest");
    expect(manifestText).not.toContain("debugger");
    await manifestPage.close();

    // 2) popup 以标签页方式打开（自动化等价物）：截图入口可见；
    //    无 activeTab 时“当前屏”必须给出可读错误，不静默失败。
    const popupPage = await harness.context.newPage();
    await popupPage.goto(`chrome-extension://${harness.extensionId}/popup.html`);
    await expect(popupPage.locator(".shot-btn[data-shot-mode=screen]")).toBeVisible();
    await expect(popupPage.locator(".shot-btn[data-shot-mode=region]")).toBeVisible();
    await expect(popupPage.locator(".shot-btn[data-shot-mode=longpage]")).toBeVisible();
    await popupPage.locator(".shot-btn[data-shot-mode=screen]").click();
    await expect(popupPage.locator("#feedback")).toContainText("请在普通网页上使用截图识别", { timeout: 15_000 });
    await popupPage.close();

    // 3) 登录博客（5174/5173 属于 externally_connectable 白名单）
    const blogPage = await harness.context.newPage();
    await blogPage.goto(`http://127.0.0.1:${frontendPort}/login?redirect=%2Fblog`);
    await blogPage.getByPlaceholder("用户名").fill(operator);
    await blogPage.getByPlaceholder("密码，至少 8 位").fill(password);
    await blogPage.getByRole("button", { name: "登录", exact: true }).click();
    await expect(blogPage).toHaveURL(new RegExp(`/blog$`));

    // 4) 从真实博客页向真实 worker 查询未知 nonce：稳定错误码
    const unknown = await blogPage.evaluate(async (extensionId) => {
      return new Promise((resolve) => {
        chrome.runtime.sendMessage(extensionId, { type: "blog.screenshot.get-meta", version: 1, nonce: "0".repeat(32) }, (response) => {
          resolve(chrome.runtime.lastError ? { lastError: chrome.runtime.lastError.message } : response);
        });
      });
    }, harness.extensionId);
    expect(unknown).toMatchObject({ code: "unknown_nonce" });

    // 5) 在真实 worker 内用合成 tile（真实中文截图 fixture）建立会话；
    //    saveScreenshotSession 会打开博客 tab，真实消费由此开始。
    const targetOrigin = `http://127.0.0.1:${frontendPort}`;
    const pagePromise = harness.context.waitForEvent("page");
    await worker.evaluate(
      async (args) => {
        const bytes = Uint8Array.from(atob(args.tileBase64), (c) => c.charCodeAt(0));
        // worker 内不能动态 import()（MV3 限制），走 background.js 的测试钩子
        const debug = (globalThis as unknown as {
          __shotDebug: {
            saveScreenshotSession: (api: unknown, input: unknown) => Promise<unknown>;
          };
          __shotTileStore: unknown;
        }).__shotDebug;
        await debug.saveScreenshotSession(
          {
            extensionId: chrome.runtime.id,
            allowedOrigins: [args.targetOrigin],
            createNonce: (size: number) => Array.from(crypto.getRandomValues(new Uint8Array(size)), (b) => b.toString(16).padStart(2, "0")).join(""),
            storage: chrome.storage.session,
            tileStore: (globalThis as unknown as { __shotTileStore: unknown }).__shotTileStore,
            openTab: async () => chrome.tabs.create({ url: "about:blank", active: false }),
            activateTab: async (tab: { id: number }, url: string) => chrome.tabs.update(tab.id, { url, active: true }),
            closeTab: async (tabId: number) => chrome.tabs.remove(tabId),
            log: () => undefined,
          },
          {
            targetOrigin: args.targetOrigin,
            mode: "longpage",
            sourceUrl: "https://example.org/article/real?utm_source=x",
            titleCandidate: "真实侧载示例",
            dpr: 1,
            viewportWidth: 760,
            viewportHeight: 430,
            coveredTop: 0,
            coveredBottom: 430,
            truncated: false,
            warnings: [],
            tiles: [{ bytes, mime: "image/png", width: 760, height: 430, scrollX: 0, scrollY: 0 }],
          },
        );
      },
      { tileBase64, targetOrigin },
    );
    const consumedPage = await pagePromise;
    await expect(consumedPage).toHaveURL(new RegExp(`/blog$`));

    // 6) 博客页消费 → 本地 OCR（真实模型 + wasm）→ 校对区出现识别内容
    const dialog = consumedPage.getByRole("dialog", { name: /截图识别为 Markdown/ });
    await expect(dialog).toBeVisible({ timeout: 30_000 });
    await expect(dialog.locator(".ocr-blocks-pane .ocr-block-card").first()).toBeVisible({ timeout: 180_000 });
    await expect(dialog.locator(".ocr-preview-body")).toContainText("当网页正文确实显示在屏幕上", { timeout: 60_000 });
    await expect(dialog.locator(".ocr-source-card")).toContainText("真实侧载示例");

    // 7) ack 后真实清理：IndexedDB 无字节，session 里只剩 tombstone
    const state = await worker.evaluate(async (targetOrigin2) => {
      const pending = ((await chrome.storage.session.get("shot:pending")) ?? {})["shot:pending"] as string[];
      const keys = Object.keys(await chrome.storage.session.get(null)).filter((key) => key.startsWith("shot:"));
      const recordKey = keys.find((key) => key !== "shot:pending");
      const record = recordKey ? ((await chrome.storage.session.get(recordKey)) ?? {})[recordKey] : null;
      const tileStore = globalThis.__shotTileStore;
      const nonce = record?.nonce ?? pending?.[0] ?? "";
      const bytes = nonce ? await tileStore.get(nonce, 0) : "no-nonce";
      return {
        pendingCount: pending?.length ?? 0,
        consumed: Boolean(record?.consumed),
        tombstoneHasTiles: Array.isArray(record?.tiles) && record.tiles.every((tile: { bytes: number }) => tile.bytes === 0),
        indexedDbEmpty: bytes === null || bytes === "no-nonce",
        sourceUrlClean: record ? !record.sourceUrl.includes("utm_source") : false,
        origin: record?.targetOrigin,
        expectedOrigin: targetOrigin2,
      };
    }, targetOrigin);
    expect(state.consumed).toBe(true);
    expect(state.tombstoneHasTiles).toBe(true);
    expect(state.indexedDbEmpty).toBe(true);
    expect(state.pendingCount).toBe(0);
    expect(state.sourceUrlClean).toBe(true);
    expect(state.origin).toBe(state.expectedOrigin);
  } finally {
    await harness.cleanup();
  }
});

test("真实侧载：worker 按内部滚动视口裁剪，并生成逐段长图预览", async ({ page: _page }) => {
  const harness = await launchWithExtension();
  try {
    const result = await getWorker(harness.context).evaluate(async () => {
      const debug = (globalThis as unknown as { __shotDebug: {
        cropScrollViewport: (bytes: Uint8Array, plan: unknown) => Promise<{ bytes: Uint8Array; width: number; height: number }>;
        previewNewSlice: (bytes: Uint8Array, selection: unknown, captureY: number, previousBottom: number, viewportHeight: number) => Promise<string>;
      } }).__shotDebug;
      const canvas = new OffscreenCanvas(300, 400);
      const context = canvas.getContext("2d")!;
      context.fillStyle = "#ff0000"; context.fillRect(0, 0, 300, 100);
      context.fillStyle = "#00aa00"; context.fillRect(0, 100, 300, 200);
      context.fillStyle = "#0000ff"; context.fillRect(0, 300, 300, 100);
      const source = new Uint8Array(await (await canvas.convertToBlob({ type: "image/jpeg" })).arrayBuffer());
      const cropped = await debug.cropScrollViewport(source, {
        viewportWidth: 300, viewportHeight: 200, screenHeight: 400, captureTop: 100, dpr: 1,
      });
      const topFrame = await debug.cropScrollViewport(source, {
        viewportWidth: 300, viewportHeight: 200, screenHeight: 400, captureTop: 0, dpr: 1,
      });
      const croppedBitmap = await createImageBitmap(new Blob([cropped.bytes], { type: "image/jpeg" }));
      const sample = new OffscreenCanvas(1, 1);
      sample.getContext("2d")!.drawImage(croppedBitmap, 150, 100, 1, 1, 0, 0, 1, 1);
      const pixel = Array.from(sample.getContext("2d")!.getImageData(0, 0, 1, 1).data);
      croppedBitmap.close();
      const preview = await debug.previewNewSlice(cropped.bytes,
        { left: 0.2, right: 0.8, top: 0, bottom: 200 }, 0, 0, 200);
      return { width: cropped.width, height: cropped.height, topFrameHeight: topFrame.height, pixel, previewPrefix: preview?.slice(0, 23) };
    });
    expect(result.width).toBe(300);
    expect(result.height).toBe(200);
    expect(result.topFrameHeight).toBe(200);
    expect(result.pixel[1]).toBeGreaterThan(result.pixel[0]);
    expect(result.pixel[1]).toBeGreaterThan(result.pixel[2]);
    expect(result.previewPrefix).toBe("data:image/jpeg;base64,");
  } finally {
    await harness.cleanup();
  }
});

test("侧载完整采集：内部滚动框选、实时缩略图、完成后打开博客", async ({ page: _page }) => {
  test.setTimeout(120_000);
  const harness = await launchWithExtension(true);
  try {
    const source = await harness.context.newPage();
    await source.goto(`http://127.0.0.1:${frontendPort}/login`);
    await source.evaluate(() => {
      const root = document.createElement("div");
      root.id = "shot-real-scroll-root";
      root.style.cssText = "position:fixed;top:100px;left:100px;width:700px;height:430px;overflow-y:auto;background:white;z-index:10";
      const body = document.createElement("div");
      body.style.cssText = "height:2500px;background:repeating-linear-gradient(white 0 80px,#d8ecdb 80px 160px)";
      body.textContent = "长截图测试正文";
      root.append(body);
      document.body.append(root);
    });
    await source.bringToFront();
    const result = await getWorker(harness.context).evaluate(async (targetOrigin) => {
      const tab = (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
      return (globalThis as unknown as { __shotDebug: {
        runLongPageCapture: (message: unknown) => Promise<unknown>;
      } }).__shotDebug.runLongPageCapture({
        targetOrigin,
        target: { tabId: tab.id, windowId: tab.windowId, url: tab.url, title: "长截图测试" },
      });
    }, `http://127.0.0.1:${frontendPort}`);
    expect(result).toMatchObject({ ok: true });
    const host = source.locator("#__blog_shot_overlay_host__");
    await host.locator('[data-shot="pick-width"]').click();
    await source.mouse.move(180, 180);
    await source.mouse.down();
    await source.mouse.move(700, 400, { steps: 4 });
    await source.mouse.up();
    const frame = await getWorker(harness.context).evaluate(async () => {
      const tab = (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
      const response = await chrome.tabs.sendMessage(tab.id!, { type: "blog.shot.geometry" });
      return response.geometry as { captureTop: number; viewportHeight: number; scrollY: number };
    });
    expect(frame).toMatchObject({ captureTop: 180, viewportHeight: 220, scrollY: 80 });
    await expect(host.locator('[data-shot="preview"] img').first()).toBeVisible({ timeout: 15_000 });
    await source.evaluate(() => { document.getElementById("shot-real-scroll-root")!.scrollTop = 850; });
    await expect.poll(async () => host.locator('[data-shot="preview"] img').count(), { timeout: 20_000 })
      .toBeGreaterThan(1);
    const blogPagePromise = harness.context.waitForEvent("page", { timeout: 20_000 });
    await host.locator('[data-shot="manual-finish"]').click();
    const blogPage = await blogPagePromise;
    await expect(blogPage).toHaveURL(/\/blog#shot=/, { timeout: 20_000 });
  } finally {
    await harness.cleanup();
  }
});

test("侧载仅保存图片：长图拼接下载且不打开博客", async ({ page: _page }) => {
  test.setTimeout(180_000);
  const harness = await launchWithExtension(true);
  try {
    const source = await harness.context.newPage();
    await source.goto(`http://127.0.0.1:${frontendPort}/login`);
    await source.evaluate(() => {
      const root = document.createElement("div");
      root.id = "shot-local-scroll-root";
      root.style.cssText = "position:fixed;top:100px;left:100px;width:700px;height:430px;overflow-y:auto;background:white;z-index:10";
      const body = document.createElement("div");
      body.style.cssText = "height:2500px;background:repeating-linear-gradient(white 0 80px,#d8ecdb 80px 160px)";
      body.textContent = "仅保存长截图测试正文";
      root.append(body);
      document.body.append(root);
    });
    await source.bringToFront();
    const result = await getWorker(harness.context).evaluate(async (targetOrigin) => {
      const tab = (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
      return (globalThis as unknown as { __shotDebug: {
        runLongPageCapture: (message: unknown) => Promise<unknown>;
      } }).__shotDebug.runLongPageCapture({
        targetOrigin,
        saveMode: true,
        target: { tabId: tab.id, windowId: tab.windowId, url: tab.url, title: "仅保存长截图" },
      });
    }, `http://127.0.0.1:${frontendPort}`);
    expect(result).toMatchObject({ ok: true });
    const host = source.locator("#__blog_shot_overlay_host__");
    await host.locator('[data-shot="pick-width"]').click();
    await source.mouse.move(180, 180);
    await source.mouse.down();
    await source.mouse.move(700, 400, { steps: 4 });
    await source.mouse.up();
    await expect(host.locator('[data-shot="preview"] img').first()).toBeVisible({ timeout: 15_000 });
    await source.evaluate(() => { document.getElementById("shot-local-scroll-root")!.scrollTop = 850; });
    await expect.poll(async () => host.locator('[data-shot="preview"] img').count(), { timeout: 20_000 })
      .toBeGreaterThan(1);

    // 不跳博客；headless 下 offscreen 不执行，兜底为扩展标签页拼接下载
    const openedUrls: string[] = [];
    harness.context.on("page", (page) => openedUrls.push(page.url()));
    await host.locator('[data-shot="manual-finish"]').click();
    // finish 面板只有一段 p，且成功后 4 秒自动关闭：用短轮询窗口抓住它
    await expect(host.locator(".panel p")).toContainText("长图已保存到下载目录", { timeout: 40_000 });
    expect(openedUrls.some((url) => /\/blog#shot=/.test(url))).toBe(false);
    expect(openedUrls.some((url) => url.includes("stitch-page.html"))).toBe(true);

    // 下载确实落盘，且扩展会话已被清理
    const downloads = await getWorker(harness.context).evaluate(async () => {
      const items = await chrome.downloads.search({});
      return items.map((item) => ({ filename: item.filename, state: item.state, mime: item.mime }));
    });
    // 测试环境把下载重定向到 playwright artifacts 目录并强制 UUID 名，
    // 因此只验证“下载完成且是 PNG”；真实 Edge 下 chrome.downloads.download 的
    // filename（long-screenshot-<时间戳>.png）会保留在用户下载目录。
    expect(downloads.length).toBeGreaterThanOrEqual(1);
    expect(downloads.some((item) => item.state === "complete" && item.mime === "image/png")).toBe(true);
    const pending = await getWorker(harness.context).evaluate(async () => {
      const stored = await chrome.storage.session.get("shot:pending");
      return stored["shot:pending"];
    });
    expect(pending ?? []).toEqual([]);
  } finally {
    await harness.cleanup();
  }
});
