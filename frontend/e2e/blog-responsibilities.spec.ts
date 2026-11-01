import { expect, test } from "@playwright/test";

test("blog agent widget restores history and sends one chat request", async ({ page }) => {
  let historyRequests = 0;
  let chatRequests = 0;
  await page.addInitScript(() => localStorage.setItem("blogAgentSessionKey", "i014-session"));
  await page.route("**/api/agent/blog/agent/chat/**", async (route) => {
    if (route.request().method() === "GET") {
      historyRequests += 1;
      await route.fulfill({ json: {
        messages: [{ id: 1, role: "user", content: "历史提问" }], has_more_before: false,
      } });
    } else {
      chatRequests += 1;
      expect(route.request().postDataJSON()).toEqual({
        message: "新问题", session_key: "i014-session", rag_source: "legacy",
      });
      await route.fulfill({ json: { session_key: "i014-session", answer: "测试回答", sources: [] } });
    }
  });
  await page.goto("/blog");
  await page.getByRole("button", { name: "问博客智能体" }).click();
  await expect(page.locator(".blog-agent-messages")).toContainText("历史提问");
  await page.getByPlaceholder("问公开博客内容，例如：这个项目架构是什么？").fill("新问题");
  await page.locator(".blog-agent-composer").getByRole("button", { name: "发送" }).click();
  await expect(page.locator(".blog-agent-messages")).toContainText("测试回答");
  expect(historyRequests).toBe(1);
  expect(chatRequests).toBe(1);
});

test("collection manager exports and previews/applies one archive request per action", async ({ page }) => {
  await page.goto("/login?redirect=%2Fblog%2Fcollections%2Fmine");
  await page.getByPlaceholder("用户名").fill("upload-e2e-operator");
  await page.getByPlaceholder("密码，至少 8 位").fill("Upload-e2e-only-2026!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/blog\/collections\/mine$/);
  await page.getByLabel("新领域标题").fill("归档职责回归");
  await page.getByRole("button", { name: "创建领域" }).click();
  await expect(page.getByRole("table", { name: "我的领域列表" })).toContainText("归档职责回归");

  let exportRequests = 0;
  let previewRequests = 0;
  let applyRequests = 0;
  await page.route("**/api/agent/blog/collections/export/**", async (route) => {
    exportRequests += 1;
    await route.fulfill({ body: "zip", headers: {
      "content-type": "application/zip", "content-disposition": 'attachment; filename="i014.zip"',
    } });
  });
  await page.route("**/api/agent/blog/collections/import/", async (route) => {
    const body = route.request().postData() || "";
    if (body.includes('name="mode"\r\n\r\npreview')) {
      previewRequests += 1;
      await route.fulfill({ json: { collections: [], totals: { collections: 0, articles: 0, images: 0, nodes: 0, entries: 0 }, warnings: [] } });
    } else {
      applyRequests += 1;
      expect(body).toContain('name="conflict"\r\n\r\nreplace');
      await route.fulfill({ json: { collections: [], totals: { articles: 0, images: 0 } } });
    }
  });

  await page.getByRole("row", { name: /归档职责回归/ }).locator("label.el-checkbox").click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: /导出所选/ }).click();
  expect((await downloadPromise).suggestedFilename()).toBe("i014.zip");
  await page.getByRole("button", { name: "导入压缩包" }).click();
  await page.getByLabel("选择领域压缩包").setInputFiles({ name: "i014.zip", mimeType: "application/zip", buffer: Buffer.from("zip") });
  await expect(page.getByRole("dialog", { name: "导入领域压缩包" })).toContainText("共 0 个领域");
  await page.getByText("覆盖已有", { exact: true }).click();
  await page.getByRole("button", { name: "确认导入" }).click();
  await expect(page.getByRole("dialog", { name: "导入领域压缩包" })).toBeHidden();
  expect({ exportRequests, previewRequests, applyRequests }).toEqual({ exportRequests: 1, previewRequests: 1, applyRequests: 1 });
});
