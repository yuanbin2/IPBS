import { expect, test } from "@playwright/test";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login?redirect=%2F");
  await page.getByPlaceholder("用户名").fill("upload-e2e-operator");
  await page.getByPlaceholder("密码，至少 8 位").fill("Upload-e2e-only-2026!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
}

test("task entrances, deep link, refresh and back keep the writing path usable", async ({ page }) => {
  const blogSettingsFailures: string[] = [];
  page.on("response", (response) => {
    if (/\/api\/agent\/blog\/(about|settings)\//.test(response.url()) && response.status() >= 500) {
      blogSettingsFailures.push(`${response.status()} ${response.url()}`);
    }
  });
  await login(page);
  await page.getByRole("link", { name: /组织资料并阅读/ }).click();
  await expect(page).toHaveURL(/\/blog\/collections\/mine$/);
  await expect(page.getByRole("heading", { name: "我的领域" })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: /早上好|下午好|晚上好|夜深了/ })).toBeVisible();

  await page.getByRole("link", { name: /获取资料并校对/ }).click();
  await expect(page).toHaveURL(/\/blog\?write=1$/);
  await expect(page.getByRole("heading", { name: "写新博客" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "写新博客" })).toBeVisible();
  await page.getByRole("button", { name: "关闭", exact: true }).first().click();
  await page.goto("/blog?write=1");
  await expect(page.getByRole("heading", { name: "写新博客" })).toBeVisible();
  expect(blogSettingsFailures).toEqual([]);
});

test("unsaved private note warns on back and refresh; cancelling keeps the draft", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: /获取资料并校对/ }).click();
  await page.getByRole("button", { name: "关闭", exact: true }).first().click();
  await page.getByRole("button", { name: "我的笔记" }).click();
  await page.getByRole("textbox", { name: "笔记标题" }).fill("I-015 未保存笔记");
  await expect(page.getByText("尚未保存", { exact: true })).toBeVisible();

  let backPrompt = false;
  page.once("dialog", async (dialog) => {
    backPrompt = true;
    expect(dialog.type()).toBe("confirm");
    await dialog.dismiss();
  });
  await page.goBack();
  expect(backPrompt).toBe(true);
  await expect(page).toHaveURL(/\/blog\?write=1$/);
  await expect(page.getByRole("textbox", { name: "笔记标题" })).toHaveValue("I-015 未保存笔记");

  let refreshPrompt = false;
  page.once("dialog", async (dialog) => {
    refreshPrompt = true;
    expect(dialog.type()).toBe("beforeunload");
    await dialog.accept();
  });
  await page.reload();
  expect(refreshPrompt).toBe(true);
  await expect(page.getByRole("textbox", { name: "笔记标题" })).toHaveCount(0);
});

test("a cited answer offers a writing handoff without auto publishing the answer", async ({ page }) => {
  await login(page);
  await page.route(/\/api\/agent\/conversations\/\?/, async (route) => {
    await route.fulfill({ json: [{ id: 915, project_id: null, title: "引用写作", created_at: "2026-10-24T00:00:00Z", updated_at: "2026-10-24T00:00:00Z" }] });
  });
  await page.route(/\/api\/agent\/conversations\/915\/\?/, async (route) => {
    await route.fulfill({ json: {
      id: 915, project_id: null, title: "引用写作", created_at: "2026-10-24T00:00:00Z", updated_at: "2026-10-24T00:00:00Z",
      has_more_before: false, has_more_after: false,
      messages: [{ id: 1, role: "user", content: "这个方案的依据？", tool_calls: [], sources: [], trace: [], token_usage: null },
        { id: 2, role: "agent", content: "需要核对来源后写作。", tool_calls: [], trace: [], token_usage: null,
          sources: [{ document_id: 7, document_title: "内部说明", chunk_id: 11, chunk_index: 0, score: 0.9, content: "样本证据" }] }],
    } });
  });
  await page.getByRole("link", { name: /提问并写作/ }).click();
  await expect(page.getByText("引用来源", { exact: true })).toBeVisible();
  await expect(page.getByText("内部说明")).toBeVisible();
  await page.getByRole("link", { name: "去写博客" }).click();
  await expect(page.getByRole("heading", { name: "写新博客" })).toBeVisible();
  await expect(page.getByPlaceholder("文章标题")).toHaveValue("");
});

test("a newly streamed answer offers the same writing handoff before refresh", async ({ page }) => {
  await login(page);
  await page.route("**/api/agent/chat/stream/", async (route) => {
    const response = { type: "response", answer: "即时回答需要核对。", sources: [], tool_calls: [], trace: [], token_usage: { prompt_tokens: 1, completion_tokens: 2, total_tokens: 3 } };
    const done = { type: "done", status: "succeeded", conversation_id: null };
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify(response)}\n\ndata: ${JSON.stringify(done)}\n\n` });
  });
  await page.getByRole("link", { name: /提问并写作/ }).click();
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("即时回答需要核对。")).toBeVisible();
  await expect(page.getByRole("link", { name: "去写博客" })).toBeVisible();
});
