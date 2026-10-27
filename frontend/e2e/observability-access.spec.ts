import { expect, test, type Page } from "@playwright/test";

async function mockSession(page: Page, role: "visitor" | "operator" | "admin" | null) {
  const observationRequests: string[] = [];
  await page.route("**/api/agent/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = [];
    let status = 200;
    if (path === "/api/agent/auth/csrf/") {
      body = { csrfToken: "test-csrf" };
    } else if (path === "/api/agent/auth/cookie/refresh/") {
      status = role ? 200 : 401;
      body = role ? { access: "test-access" } : { detail: "No session" };
    } else if (path === "/api/agent/auth/me/") {
      body = { actor: "access-test", role, workspace_key: "test", authenticated: true, security_enforced: true };
    } else if (path === "/api/agent/observability/") {
      observationRequests.push(path);
      body = {
        summary: { total_runs: 7, average_latency_ms: 120, success_rate: 1 },
        observations: [{ id: 1, selected_agent: "rag_agent", status: "success", input_message: "private run", created_at: "2026-10-27T00:00:00Z" }],
        total: 1,
        has_more: false,
      };
    }
    await route.fulfill({ status, json: body });
  });
  return observationRequests;
}

test("visitor cannot see observation entrances, metrics, recent runs or request their data", async ({ page }) => {
  const requests = await mockSession(page, "visitor");
  await page.goto("/");
  await expect(page.getByText("博客文章", { exact: true })).toBeVisible();
  await expect(page.locator('a[href="/observability"]')).toHaveCount(0);
  await expect(page.getByText("Agent 调用", { exact: true })).toHaveCount(0);
  await expect(page.getByText("平均延迟", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "最近 Agent 运行" })).toHaveCount(0);
  await expect(page.getByText("private run", { exact: true })).toHaveCount(0);
  expect(requests).toHaveLength(0);
});

test("visitor direct links and reloads redirect to the overview without loading observation data", async ({ page }) => {
  const requests = await mockSession(page, "visitor");
  await page.goto("/observability?limit=10#evaluation");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator('a[href="/observability"]')).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("博客文章", { exact: true })).toBeVisible();
  expect(requests).toHaveLength(0);
});

test("anonymous users must log in before opening observations", async ({ page }) => {
  const requests = await mockSession(page, null);
  await page.goto("/observability");
  await expect(page).toHaveURL(/\/login\?redirect=/);
  await expect(page.locator('a[href="/observability"]')).toHaveCount(0);
  expect(requests).toHaveLength(0);
});

for (const role of ["operator", "admin"] as const) {
  test(`${role} retains observation navigation, dashboard metrics and page access`, async ({ page }) => {
    const requests = await mockSession(page, role);
    await page.goto("/");
    await expect(page.getByText("Agent 调用", { exact: true })).toBeVisible();
    await expect(page.getByText("平均延迟", { exact: true })).toBeVisible();
    await expect(page.locator('a[href="/observability"]')).toHaveCount(2);
    await expect.poll(() => requests.length).toBe(1);
    await page.locator('nav a[href="/observability"]').click();
    await expect(page).toHaveURL(/\/observability$/);
    await expect(page.getByRole("heading", { name: "观测评估", exact: true })).toBeVisible();
    await expect.poll(() => requests.length).toBe(2);
  });
}
