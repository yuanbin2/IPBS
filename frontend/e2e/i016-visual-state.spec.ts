import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const screenshotDir = resolve(process.cwd(), "../docs/evaluation/I-016");
const capture = process.env.I016_CAPTURE_SCREENSHOTS === "1";

async function screenshot(page: import("@playwright/test").Page, name: string) {
  if (!capture) return;
  mkdirSync(screenshotDir, { recursive: true });
  await page.screenshot({ path: resolve(screenshotDir, name), animations: "disabled" });
}

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("upload-e2e-operator");
  await page.getByPlaceholder("密码，至少 8 位").fill("Upload-e2e-only-2026!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
}

test("catalog error and empty results give a next action at desktop and narrow widths", async ({ page }) => {
  await login(page);
  let failing = true;
  await page.route(/\/api\/agent\/blog\/collections\/\?/, async (route) => {
    if (failing) await route.fulfill({ status: 503, json: { detail: "服务暂时不可用" } });
    else await route.fulfill({ json: { items: [], pages: 1, total: 0 } });
  });
  await page.goto("/blog/collections");
  await expect(page.getByRole("alert")).toContainText("重试加载");
  await screenshot(page, "catalog-error-desktop.png");
  failing = false;
  await page.getByRole("button", { name: "重试加载" }).click();
  await expect(page.getByRole("status")).toContainText("还没有已公开的领域目录");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(350); // wait for the existing mobile navigation transition before capturing
  await screenshot(page, "catalog-empty-mobile.png");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("chat keeps raw traces private and long markdown inside the narrow viewport", async ({ page }) => {
  await login(page);
  const longTitle = "超长标题".repeat(35);
  const columns = Array.from({ length: 18 }, (_, i) => `第${i}列`);
  const markdown = `# ${longTitle}\n\n\`\`\`js\n${"veryLongIdentifier".repeat(35)}\n\`\`\`\n\n|${columns.join("|")}|\n|${columns.map(() => "---").join("|")}|\n|${columns.map(() => "长内容").join("|")}|\n\n![宽图](/i016-wide.svg)`;
  await page.route("**/i016-wide.svg", async (route) => route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="2200" height="240"><rect width="2200" height="240" fill="#174b46"/></svg>' }));
  await page.route(/\/api\/agent\/conversations\/\?/, async (route) => route.fulfill({ json: [{ id: 916, project_id: null, title: "键盘与长内容", created_at: "2026-10-24T00:00:00Z", updated_at: "2026-10-24T00:00:00Z" }] }));
  await page.route(/\/api\/agent\/conversations\/916\/\?/, async (route) => route.fulfill({ json: {
    id: 916, project_id: null, title: "键盘与长内容", created_at: "2026-10-24T00:00:00Z", updated_at: "2026-10-24T00:00:00Z",
    has_more_before: false, has_more_after: false,
    messages: [{ id: 1, role: "agent", content: markdown, tool_calls: [], sources: [], trace: ["internet_query_rewrite -> private secret", "generate -> complete"], token_usage: null }],
  } }));
  await page.goto("/chat");
  const progressToggle = page.getByRole("button", { name: /处理进度/ });
  await expect(progressToggle).toBeVisible();
  await expect(page.locator(".thinking-content")).toContainText("已查找网页资料");
  await expect(page.getByText("private secret")).toHaveCount(0);
  const history = page.getByRole("button", { name: "键盘与长内容" });
  await history.focus();
  await expect(history).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(progressToggle).toBeVisible();
  await page.locator(".conversation").evaluate((element) => { element.scrollTop = 0; });
  await screenshot(page, "chat-long-content-desktop.png");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(350);
  await page.locator(".conversation").evaluate((element) => { element.scrollTop = 0; });
  await screenshot(page, "chat-long-content-mobile.png");
  await page.locator(".agent-md-preview table").scrollIntoViewIfNeeded();
  await screenshot(page, "chat-table-mobile.png");
  await page.locator(".agent-md-preview img").scrollIntoViewIfNeeded();
  await screenshot(page, "chat-wide-image-mobile.png");
  expect(await page.locator(".agent-md-preview table").evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("knowledge search failure offers retry without erasing existing results", async ({ page }) => {
  await login(page);
  let releaseDocuments!: () => void;
  const documentGate = new Promise<void>((resolve) => { releaseDocuments = resolve; });
  await page.route(/\/api\/agent\/documents\/\?/, async (route) => {
    await documentGate;
    await route.continue();
  });
  await page.goto("/knowledge");
  await expect(page.getByRole("status").filter({ hasText: "正在更新文档列表" })).toBeVisible();
  await screenshot(page, "knowledge-loading-desktop.png");
  releaseDocuments();
  await expect(page.getByRole("status").filter({ hasText: "正在更新文档列表" })).toBeHidden();
  await page.unroute(/\/api\/agent\/documents\/\?/);
  let succeed = false;
  await page.route("**/api/agent/knowledge-search/", async (route) => {
    if (succeed) await route.fulfill({ json: [{ document_title: "测试资料", chunk_id: 3, score: 0.9, content: "可继续查看的上次结果" }] });
    else await route.fulfill({ status: 503, json: { detail: "服务暂时不可用" } });
  });
  await page.getByRole("button", { name: "检索", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("重试检索");
  await screenshot(page, "knowledge-search-error-desktop.png");
  succeed = true;
  await page.getByRole("button", { name: "重试检索" }).click();
  await expect(page.getByText("可继续查看的上次结果")).toBeVisible();
  succeed = false;
  await page.getByRole("button", { name: "检索", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("以下仍是上次结果");
  await expect(page.getByText("可继续查看的上次结果")).toBeVisible();
  await screenshot(page, "knowledge-search-partial-desktop.png");
});

test("knowledge creation dialog fits a narrow viewport and restores keyboard focus", async ({ page }) => {
  await login(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/knowledge");
  const trigger = page.getByRole("button", { name: "新建", exact: true });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "新建知识库" });
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  expect(await dialog.evaluate((element) => element.getBoundingClientRect().right <= window.innerWidth)).toBe(true);
  await screenshot(page, "knowledge-dialog-mobile.png");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});
