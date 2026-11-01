/** 验证真正注入到网页的截图控制脚本不会把自己的浮层截进正文。 */
import { expect, test } from "@playwright/test";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const contentScript = resolve(dirname(fileURLToPath(import.meta.url)), "../../browser-extension/shared/shot-content.js");

test("采集前隐藏扩展浮层，采集后恢复进度；取消范围选择恢复滚动", async ({ page }) => {
  await page.goto("/login");
  await page.evaluate(async () => {
    document.body.style.minHeight = "2500px";
    const image = document.createElement("img");
    image.src = `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="240" height="140"><rect width="240" height="140" fill="orange"/></svg>')}`;
    image.style.cssText = "position:absolute;left:20px;top:280px;width:240px;height:140px";
    document.body.append(image);
    await image.decode();
    const nav = document.createElement("nav");
    nav.style.cssText = "position:fixed;left:0;top:0;width:240px;height:140px";
    const navImage = image.cloneNode(true) as HTMLImageElement;
    navImage.style.cssText = "width:240px;height:140px";
    nav.append(navImage);
    document.body.append(nav);
    await navImage.decode();
    const browser = (window as unknown as { chrome?: Record<string, unknown> }).chrome ?? {};
    browser.runtime = {
      onMessage: { addListener: () => undefined },
      sendMessage: async () => ({ ok: true }),
    };
    (window as unknown as { chrome: Record<string, unknown> }).chrome = browser;
    window.scrollTo(0, 200);
  });
  await page.addScriptTag({ path: contentScript });
  const result = await page.evaluate(async () => {
    const api = (window as unknown as { __BLOG_SHOT_CONTENT__: {
      showPlanner: (info: unknown) => void;
      prepareCapture: () => Promise<{ scrollY: number; imageCandidates: Array<{ x: number; y: number; width: number; height: number }> }>;
      showProgress: (info: unknown) => void;
    } }).__BLOG_SHOT_CONTENT__;
    api.showPlanner({ pageHeight: 2500, viewportHeight: window.innerHeight, originScrollX: 0, originScrollY: 200 });
    const host = document.getElementById("__blog_shot_overlay_host__")!;
    const plannedVisible = getComputedStyle(host).visibility;
    const prepared = await api.prepareCapture();
    const hiddenDuringCapture = getComputedStyle(host).visibility;
    api.showProgress({ current: 1, total: 2, note: "正在截取" });
    const visibleAfterCapture = getComputedStyle(host).visibility;
    api.showPlanner({ pageHeight: 2500, viewportHeight: window.innerHeight, originScrollX: 0, originScrollY: 200 });
    window.scrollTo(0, 500);
    document.getElementById("__blog_shot_overlay_host__")!.shadowRoot!
      .querySelector<HTMLButtonElement>('[data-shot="cancel"]')!.click();
    return { plannedVisible, hiddenDuringCapture, visibleAfterCapture, preparedY: prepared.scrollY, restoredY: window.scrollY, imageCandidates: prepared.imageCandidates, viewportWidth: window.innerWidth, viewportHeight: window.innerHeight };
  });
  expect(result.imageCandidates).toHaveLength(1);
  expect(result.imageCandidates[0]).toMatchObject({
    x: 20 / result.viewportWidth,
    y: 80 / result.viewportHeight,
    width: 240 / result.viewportWidth,
    height: 140 / result.viewportHeight,
  });
  const { imageCandidates: _, viewportWidth: _width, viewportHeight: _height, ...state } = result;
  expect(state).toEqual({
    plannedVisible: "visible",
    hiddenDuringCapture: "hidden",
    visibleAfterCapture: "visible",
    preparedY: 200,
    restoredY: 200,
  });
});

test("一次拖框选定完整截图区域，进入手动滚动采集", async ({ page }) => {
  await page.goto("/login");
  await page.evaluate(() => {
    document.body.style.minHeight = "2800px";
    const browser = (window as unknown as { chrome?: Record<string, unknown> }).chrome ?? {};
    browser.runtime = {
      onMessage: { addListener: () => undefined },
      sendMessage: async (message: unknown) => { (window as unknown as { __planMessage?: unknown }).__planMessage = message; return { ok: true }; },
    };
    (window as unknown as { chrome: Record<string, unknown> }).chrome = browser;
  });
  await page.addScriptTag({ path: contentScript });
  await page.evaluate(() => (window as unknown as { __BLOG_SHOT_CONTENT__: { showPlanner: (info: unknown) => void } }).__BLOG_SHOT_CONTENT__
    .showPlanner({ pageHeight: 2800, viewportHeight: window.innerHeight, originScrollX: 0, originScrollY: 0 }));
  const host = page.locator("#__blog_shot_overlay_host__");
  await host.locator('[data-shot="pick-width"]').click();
  // 四条边都生效：上边缘 260 即起点，框高 240px。
  await page.mouse.move(180, 260);
  await page.mouse.down();
  await page.mouse.move(920, 500, { steps: 5 });
  await page.mouse.up();
  // 松开鼠标后直接开始；无需再找一个“开始”按钮。
  const result = await page.evaluate(() => ({
    message: (window as unknown as { __planMessage?: { selection?: { left: number; right: number; top: number; bottom: number }; endY?: number; captureTop?: number; viewportHeight?: number } }).__planMessage,
    width: window.innerWidth,
  }));
  // PixPin 式：终点由后续滚动决定，plan-ready 只带起点与页面总高
  expect(result.message?.selection).toMatchObject({
    left: 180 / result.width,
    right: 920 / result.width,
    top: 260,
    bottom: 2800,
  });
  expect(result.message?.endY).toBe(2800);
  expect(result.message).toMatchObject({ captureTop: 260, viewportHeight: 240 });
  // 迷你 HUD 已显示（右下角，可拖动），等待 worker 截第一屏
  await expect(host.locator('[data-shot="manual-finish"]')).toBeVisible();
  await expect(host.locator('[data-shot="hud-status"]')).toContainText("第一屏");
});

test("在已滚动的页面框选后，第一屏保留当前视口和框上边缘", async ({ page }) => {
  await page.goto("/login");
  await page.evaluate(() => {
    document.body.style.minHeight = "2800px";
    const browser = (window as unknown as { chrome?: Record<string, unknown> }).chrome ?? {};
    browser.runtime = {
      onMessage: { addListener: () => undefined },
      sendMessage: async (message: unknown) => { (window as unknown as { __planMessage?: unknown }).__planMessage = message; return { ok: true }; },
    };
    (window as unknown as { chrome: Record<string, unknown> }).chrome = browser;
    window.scrollTo(0, 600);
  });
  await page.addScriptTag({ path: contentScript });
  await page.evaluate(() => (window as unknown as { __BLOG_SHOT_CONTENT__: { showPlanner: (info: unknown) => void } }).__BLOG_SHOT_CONTENT__
    .showPlanner({ pageHeight: 2800, viewportHeight: window.innerHeight, originScrollX: 0, originScrollY: 600 }));
  const host = page.locator("#__blog_shot_overlay_host__");
  await host.locator('[data-shot="pick-width"]').click();
  // 在滚动位置 600 拖框：上边缘 260 → 起点 860
  await page.mouse.move(180, 260);
  await page.mouse.down();
  await page.mouse.move(920, 500, { steps: 3 });
  await page.mouse.up();
  const result = await page.evaluate(() => ({
    message: (window as unknown as { __planMessage?: { initialScrollY?: number; selection?: { left: number; right: number; top: number; bottom: number } } }).__planMessage,
  }));
  expect(result.message).toMatchObject({ initialScrollY: 860, captureTop: 260, viewportHeight: 240, selection: { top: 860, bottom: 2800 } });
});

test("手动滚动模式：滚动停顿上报 scroll-idle，Esc 触发完成收尾", async ({ page }) => {
  await page.goto("/login");
  await page.evaluate(() => {
    document.body.style.minHeight = "2800px";
    const browser = (window as unknown as { chrome?: Record<string, unknown> }).chrome ?? {};
    browser.runtime = {
      onMessage: { addListener: () => undefined },
      sendMessage: async (message: unknown) => {
        (window as unknown as { __planMessages?: unknown[] }).__planMessages = [...((window as unknown as { __planMessages?: unknown[] }).__planMessages ?? []), message];
        return { ok: true };
      },
    };
    (window as unknown as { chrome: Record<string, unknown> }).chrome = browser;
    window.scrollTo(0, 600);
  });
  await page.addScriptTag({ path: contentScript });
  await page.evaluate(() => (window as unknown as { __BLOG_SHOT_CONTENT__: { showPlanner: (info: unknown) => void } }).__BLOG_SHOT_CONTENT__
    .showPlanner({ pageHeight: 2800, viewportHeight: window.innerHeight, originScrollX: 0, originScrollY: 600 }));
  const host = page.locator("#__blog_shot_overlay_host__");
  await host.locator('[data-shot="pick-width"]').click();
  await page.mouse.move(180, 260);
  await page.mouse.down();
  await page.mouse.move(920, 500, { steps: 3 });
  await page.mouse.up();
  await expect(host.locator('[data-shot="manual-finish"]')).toBeVisible();
  // 滚到 1400 停顿：应上报 scroll-idle 且坐标为真实滚动位置
  await page.evaluate(() => window.scrollTo(0, 1400));
  await expect.poll(async () => {
    const messages = await page.evaluate(() => (window as unknown as { __planMessages?: Array<{ type: string; scrollY?: number }> }).__planMessages ?? []);
    return messages.find((message) => message.type === "blog.shot.scroll-idle")?.scrollY;
  }, { timeout: 8_000 }).toBe(1660);
  // 懒加载把页面加长后，仍能持续上报新的滚动位置；初始测高不能当终点。
  await page.evaluate(() => {
    document.body.style.minHeight = "5400px";
    window.scrollTo(0, 3200);
  });
  await expect.poll(async () => {
    const messages = await page.evaluate(() => (window as unknown as { __planMessages?: Array<{ type: string; scrollY?: number }> }).__planMessages ?? []);
    return messages.filter((message) => message.type === "blog.shot.scroll-idle").at(-1)?.scrollY;
  }, { timeout: 8_000 }).toBe(3460);
  await page.evaluate(() => (window as unknown as { __BLOG_SHOT_CONTENT__: { showManualStatus: (info: unknown) => void } }).__BLOG_SHOT_CONTENT__
    .showManualStatus({ status: "已截 1 屏" }));
  // Esc 相当于点“完成”：通知 worker 收尾
  await page.keyboard.press("Escape");
  await expect.poll(async () => {
    const messages = await page.evaluate(() => (window as unknown as { __planMessages?: Array<{ type: string }> }).__planMessages ?? []);
    return messages.some((message) => message.type === "blog.shot.manual-finish");
  }, { timeout: 8_000 }).toBe(true);
});

test("框选内部滚动正文时持续采集，并在小窗拼接显示缩略图", async ({ page }) => {
  await page.goto("/login");
  await page.evaluate(() => {
    const root = document.createElement("div");
    root.id = "article-scroll-root";
    root.style.cssText = "position:fixed;top:120px;left:100px;width:700px;height:500px;overflow-y:auto;background:white";
    const content = document.createElement("div");
    content.style.cssText = "height:3200px;background:linear-gradient(white,lightblue)";
    root.append(content);
    document.body.append(root);
    const browser = (window as unknown as { chrome?: Record<string, unknown> }).chrome ?? {};
    browser.runtime = {
      onMessage: { addListener: () => undefined },
      sendMessage: async (message: unknown) => {
        (window as unknown as { __nestedMessages?: unknown[] }).__nestedMessages =
          [...((window as unknown as { __nestedMessages?: unknown[] }).__nestedMessages ?? []), message];
        return { ok: true, active: true };
      },
    };
    (window as unknown as { chrome: Record<string, unknown> }).chrome = browser;
  });
  await page.addScriptTag({ path: contentScript });
  await page.evaluate(() => (window as unknown as { __BLOG_SHOT_CONTENT__: { showPlanner: (info: unknown) => void } }).__BLOG_SHOT_CONTENT__
    .showPlanner({ pageHeight: 3200, viewportHeight: window.innerHeight, originScrollX: 0, originScrollY: 0 }));
  const host = page.locator("#__blog_shot_overlay_host__");
  await host.locator('[data-shot="pick-width"]').click();
  await page.mouse.move(180, 200);
  await page.mouse.down();
  await page.mouse.move(700, 500, { steps: 4 });
  await page.mouse.up();
  await expect(host.locator('[data-shot="manual-finish"]')).toBeVisible();
  const initial = await page.evaluate(() => ({
    plan: (window as unknown as { __nestedMessages?: Array<{ type: string; viewportHeight?: number; captureTop?: number; initialScrollY?: number; selection?: { top: number } }> }).__nestedMessages?.find((item) => item.type === "blog.shot.plan-ready"),
  }));
  expect(initial.plan).toMatchObject({ viewportHeight: 300, captureTop: 200, initialScrollY: 80, selection: { top: 80 } });
  await page.evaluate(() => { document.getElementById("article-scroll-root")!.scrollTop = 1000; });
  await expect.poll(async () => page.evaluate(() =>
    (window as unknown as { __nestedMessages?: Array<{ type: string; scrollY?: number }> }).__nestedMessages
      ?.filter((item) => item.type === "blog.shot.scroll-idle").at(-1)?.scrollY), { timeout: 8000 }).toBe(1080);
  const result = await page.evaluate(async () => {
    const api = (window as unknown as { __BLOG_SHOT_CONTENT__: {
      geometry: () => { scrollY: number; viewportHeight: number; captureTop: number };
      showManualStatus: (info: unknown) => void;
      scrollTo: (y: number) => Promise<number>;
    } }).__BLOG_SHOT_CONTENT__;
    const before = api.geometry();
    const canvas = document.createElement("canvas");
    canvas.width = 40; canvas.height = 80;
    canvas.getContext("2d")!.fillRect(0, 0, 40, 80);
    const previewDataUrl = canvas.toDataURL("image/jpeg");
    api.showManualStatus({ status: "已截 1 屏", previewDataUrl });
    api.showManualStatus({ status: "已截 2 屏", previewDataUrl });
    const images = document.getElementById("__blog_shot_overlay_host__")!.shadowRoot!
      .querySelectorAll('[data-shot="preview"] img').length;
    const moved = await api.scrollTo(1300);
    return { before, images, moved, physical: document.getElementById("article-scroll-root")!.scrollTop };
  });
  expect(result).toMatchObject({ before: { scrollY: 1080, viewportHeight: 300, captureTop: 200 }, images: 2, moved: 1300, physical: 1220 });
});

test("手动截屏在重复帧或跳过帧后恢复 HUD，程序滚动不伪装成人工滚动", async ({ page }) => {
  await page.goto("/login");
  await page.evaluate(() => {
    document.body.style.minHeight = "3200px";
    const browser = (window as unknown as { chrome?: Record<string, unknown> }).chrome ?? {};
    browser.runtime = {
      onMessage: { addListener: () => undefined },
      sendMessage: async (message: unknown) => {
        (window as unknown as { __shotMessages?: unknown[] }).__shotMessages = [...((window as unknown as { __shotMessages?: unknown[] }).__shotMessages ?? []), message];
        return { ok: true, active: true };
      },
    };
    (window as unknown as { chrome: Record<string, unknown> }).chrome = browser;
  });
  await page.addScriptTag({ path: contentScript });
  const result = await page.evaluate(async () => {
    const api = (window as unknown as { __BLOG_SHOT_CONTENT__: {
      beginManualHud: (info: unknown) => void;
      prepareCapture: () => Promise<unknown>;
      showManualStatus: (info: unknown) => void;
      scrollTo: (y: number) => Promise<number>;
    } }).__BLOG_SHOT_CONTENT__;
    api.beginManualHud({ startY: 0 });
    await api.prepareCapture();
    const host = document.getElementById("__blog_shot_overlay_host__")!;
    const during = getComputedStyle(host).visibility;
    api.showManualStatus({ status: "已截 1 屏" });
    const after = getComputedStyle(host).visibility;
    await api.scrollTo(900);
    await new Promise((resolve) => window.setTimeout(resolve, 650));
    const idleCount = ((window as unknown as { __shotMessages?: Array<{ type: string }> }).__shotMessages ?? [])
      .filter((message) => message.type === "blog.shot.scroll-idle").length;
    return { during, after, idleCount, finishEnabled: !(host.shadowRoot!.querySelector<HTMLButtonElement>('[data-shot="manual-finish"]')!.disabled) };
  });
  expect(result).toEqual({ during: "hidden", after: "visible", idleCount: 0, finishEnabled: true });
  await page.evaluate(() => (window as unknown as { __BLOG_SHOT_CONTENT__: { showPlanner: (info: unknown) => void } }).__BLOG_SHOT_CONTENT__
    .showPlanner({ pageHeight: 3200, viewportHeight: window.innerHeight, originScrollX: 0, originScrollY: window.scrollY }));
  await expect(page.locator("#__blog_shot_overlay_host__").locator('[data-shot="pick-width"]')).toBeVisible();
  await expect(page.locator("#__blog_shot_overlay_host__").locator('[data-shot="manual-finish"]')).toHaveCount(0);
});

test("选定宽度后按滚动坐标拼成一张无空隙长图", async ({ page }) => {
  await page.goto("/login");
  const result = await page.evaluate(async () => {
    const { cropLongShotTiles, stitchLongShotTiles } = await import("/src/features/blog/utils/longScreenshot.ts");
    async function tile(color: string, scrollY: number) {
      const canvas = document.createElement("canvas");
      canvas.width = 200;
      canvas.height = 100;
      const context = canvas.getContext("2d")!;
      context.fillStyle = color;
      context.fillRect(0, 0, 200, 100);
      const blob = await new Promise<Blob>((resolve) => canvas.toBlob((value) => resolve(value!), "image/png"));
      return { file: new File([blob], `${scrollY}.png`, { type: "image/png" }), width: 200, height: 100, scrollX: 0, scrollY };
    }
    const selection = { left: 0.2, right: 0.8, top: 20, bottom: 180 };
    const cropped = await cropLongShotTiles([await tile("#ff0000", 0), await tile("#0000ff", 80)], selection, 100);
    const stitched = await stitchLongShotTiles(cropped, selection, 100);
    const bitmap = await createImageBitmap(stitched);
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext("2d")!;
    context.drawImage(bitmap, 0, 0);
    const sample = (y: number) => Array.from(context.getImageData(30, y, 1, 1).data).slice(0, 3);
    const output = { width: bitmap.width, height: bitmap.height, top: sample(10), bottom: sample(140), croppedCount: cropped.length };
    bitmap.close();
    return output;
  });
  expect(result).toMatchObject({ width: 120, height: 160, croppedCount: 2 });
  expect(result.top[0]).toBeGreaterThan(200);
  expect(result.bottom[2]).toBeGreaterThan(200);
});
