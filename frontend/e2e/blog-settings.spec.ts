/**
 * 站点设置页 e2e：管理员可编辑并保存，公开页面读取设置值；
 * 未登录用户看到只读提示。走真实 Django 服务与真实设置单例行。
 */

import { expect, test, type Page } from "@playwright/test";

const password = "Upload-e2e-only-2026!";
const admin = "upload-e2e-admin";

async function login(page: Page, username: string) {
  await page.goto(`/login?redirect=${encodeURIComponent("/blog")}`);
  await page.getByPlaceholder("用户名").fill(username);
  await page.getByPlaceholder("密码，至少 8 位").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/blog$/);
}

test("管理员在设置页修改站点标题后，首页 hero 与设置页回读一致", async ({ page }) => {
  test.setTimeout(180_000);
  await login(page, admin);
  await page.goto("/blog/settings");
  await expect(page.locator(".settings-view")).toBeVisible({ timeout: 20_000 });

  const titleField = page.locator(".settings-field input").first();
  const stamp = `设置页标题 ${Date.now() % 100000}`;
  await titleField.fill(stamp);
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect(page.locator(".settings-error")).toBeHidden();

  // 回读：重新载入设置页，表单值持久化
  await page.reload();
  await expect(page.locator(".settings-view")).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".settings-field input").first()).toHaveValue(stamp, { timeout: 20_000 });

  // 首页 hero 使用设置标题
  await page.goto("/blog");
  await expect(page.locator(".library-hero-copy h1")).toHaveText(stamp, { timeout: 20_000 });
});

test("未登录用户访问设置页被引导登录", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/blog/settings");
  // 设置页不在公开路由表：路由守卫把游客重定向到登录页
  await expect(page).toHaveURL(/\/login/, { timeout: 20_000 });
});
