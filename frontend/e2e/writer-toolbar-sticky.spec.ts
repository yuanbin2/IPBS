/**
 * 写作台工具栏吸附回归：编辑器顶部滚出视口后，工具栏应吸附在可视区顶部。
 * 根因背景：.vditor 根元素若保持 Vditor 自带的 overflow:hidden，sticky 的
 * 约束盒是不滚动的编辑器盒子，pin 永远不会生效（VditorEditor.vue 已放开）。
 */
import { expect, test, type Page } from "@playwright/test";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const password = "Upload-e2e-only-2026!";
const operatorA = "upload-e2e-operator";

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

test("写作台编辑器顶部滚出视口后工具栏仍吸附在顶部", async ({ page }) => {
  test.setTimeout(120_000);
  await serveInstalledVditorAssets(page);
  await login(page, operatorA);
  await page.getByRole("button", { name: "写博客", exact: true }).click();
  await page.waitForSelector(".writer-overlay .vditor", { timeout: 60_000 });

  // 在编辑器下方注入页脚占位内容，使编辑器顶部能够滚出视口
  await page.evaluate(() => {
    const overlay = document.querySelector(".writer-overlay");
    const editor = document.querySelector(".writer-overlay .vditor");
    if (!overlay || !editor) throw new Error("缺少写作台元素");
    const spacer = document.createElement("div");
    spacer.style.height = "1200px";
    editor.after(spacer);
  });

  // 滚动到编辑器顶部已经越过可视区顶部的位置
  await page.evaluate(() => {
    const overlay = document.querySelector(".writer-overlay")!;
    const editor = document.querySelector(".writer-overlay .vditor")!;
    const target = (editor as HTMLElement).getBoundingClientRect().top + overlay.scrollTop + 80;
    overlay.scrollTop = Math.max(0, target);
  });
  await page.waitForTimeout(300);

  const result = await page.evaluate(() => {
    const toolbar = document.querySelector(".writer-overlay .vditor-toolbar") as HTMLElement;
    const editor = document.querySelector(".writer-overlay .vditor") as HTMLElement;
    return {
      position: getComputedStyle(toolbar).position,
      toolbarTop: toolbar.getBoundingClientRect().top,
      editorTop: editor.getBoundingClientRect().top,
      editorBottom: editor.getBoundingClientRect().bottom,
    };
  });

  expect(result.position).toBe("sticky");
  expect(result.editorTop).toBeLessThan(0);
  expect(Math.abs(result.toolbarTop)).toBeLessThanOrEqual(2);
  expect(result.toolbarTop).toBeLessThan(result.editorBottom);
});
