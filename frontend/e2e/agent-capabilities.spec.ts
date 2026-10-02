import { expect, test } from "@playwright/test";

test("agent chat streams workspace statistics and reviews the previous answer", async ({ page }) => {
  await page.goto("/login?redirect=%2Fchat");
  await page.getByPlaceholder("用户名").fill("upload-e2e-operator");
  await page.getByPlaceholder("密码，至少 8 位").fill("Upload-e2e-only-2026!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);

  const composer = page.getByPlaceholder("向 Agent 提问，例如：帮我计算 12 * 8");
  await composer.fill("统计一下文章数量");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator(".message.agent").last()).toContainText("published_articles:");
  await expect(page.locator(".message.agent").last()).toContainText("SQL Analysis Agent");

  await composer.fill("检查刚才回答的引用");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator(".message.agent").last()).toContainText("没有保存可核对的来源");
  await expect(page.locator(".message.agent").last()).toContainText("Review Agent");

  await page.reload();
  await expect(page.locator(".message.agent").last()).toContainText("没有保存可核对的来源");
});
