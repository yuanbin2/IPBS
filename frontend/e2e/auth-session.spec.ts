import { expect, test, type Page } from "@playwright/test";

const username = "upload-e2e-operator";
const password = "Upload-e2e-only-2026!";

async function login(page: Page, account = username) {
  await page.goto("/login?redirect=%2Fblog");
  await page.getByPlaceholder("用户名").fill(account);
  await page.getByPlaceholder("密码，至少 8 位").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(/\/blog$/);
}

test("security dashboard is reachable by admins and hidden from operators", async ({ page }) => {
  await login(page);
  await page.goto("/security");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("link", { name: "安全" })).toHaveCount(0);

  await page.getByRole("button", { name: "退出", exact: true }).click();
  await login(page, "upload-e2e-admin");
  await page.getByRole("link", { name: "安全" }).click();
  await expect(page).toHaveURL(/\/security$/);
  await expect(page.getByRole("heading", { name: "安全审计" })).toBeVisible();
  await expect(page.getByText("upload-e2e-admin", { exact: true }).first()).toBeVisible();
});

test("refresh cookie is HttpOnly, tokens stay out of storage, and reload restores access", async ({ page, context }) => {
  await login(page);
  const cookie = (await context.cookies()).find((item) => item.name === "blog_refresh");
  expect(cookie).toBeTruthy();
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Lax");
  expect(cookie?.path).toBe("/api/agent/auth/cookie/");
  const browserStorage = await page.evaluate(() => ({
    access: localStorage.getItem("agent_auth_token"),
    refresh: localStorage.getItem("agent_refresh_token"),
    readableCookie: document.cookie.includes("blog_refresh"),
  }));
  expect(browserStorage).toEqual({ access: null, refresh: null, readableCookie: false });

  await page.reload();
  await expect(page.getByRole("button", { name: "写博客", exact: true })).toBeVisible();
  const me = await page.evaluate(async () => {
    const response = await fetch("/api/agent/auth/me/");
    return { status: response.status, session: await response.json() };
  });
  expect(me.status).toBe(200);
  expect(me.session.authenticated).toBe(true);
  expect(me.session.actor).toBe(username);
});

test("logout revokes the cookie and closes another active tab", async ({ page, context }) => {
  await login(page);
  const otherTab = await context.newPage();
  await otherTab.goto("/blog");
  await expect(otherTab.getByRole("button", { name: "写博客", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "退出", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(otherTab).toHaveURL(/\/login$/);
  expect((await context.cookies()).some((item) => item.name === "blog_refresh" && item.value)).toBe(false);
  const storage = await otherTab.evaluate(() => ({
    access: localStorage.getItem("agent_auth_token"),
    refresh: localStorage.getItem("agent_refresh_token"),
  }));
  expect(storage).toEqual({ access: null, refresh: null });
});

test("two tabs can reload together without losing the rotated cookie session", async ({ page, context }) => {
  await login(page);
  const otherTab = await context.newPage();
  await otherTab.goto("/blog");
  await expect(otherTab.getByRole("button", { name: "写博客", exact: true })).toBeVisible();
  await Promise.all([page.reload(), otherTab.reload()]);
  await expect(page.getByRole("button", { name: "写博客", exact: true })).toBeVisible();
  await expect(otherTab.getByRole("button", { name: "写博客", exact: true })).toBeVisible();
});

test("one legacy refresh token upgrades into the cookie session and is removed locally", async ({ page, context }) => {
  const legacyLogin = await context.request.post("/api/agent/auth/login/", {
    data: { username, password },
  });
  expect(legacyLogin.status()).toBe(200);
  const legacyRefresh = (await legacyLogin.json()).refresh as string;

  const initialRefresh = page.waitForResponse((response) =>
    response.url().includes("/api/agent/auth/cookie/refresh/") && response.request().method() === "POST",
  );
  await page.goto("/login");
  await initialRefresh;
  await expect(page.getByPlaceholder("用户名")).toBeVisible();
  await page.evaluate((refresh) => localStorage.setItem("agent_refresh_token", refresh), legacyRefresh);
  const upgradeResponse = page.waitForResponse((response) =>
    response.url().includes("/api/agent/auth/cookie/upgrade/") && response.request().method() === "POST",
  );
  await page.reload();
  expect((await upgradeResponse).status()).toBe(200);
  await page.goto("/blog");
  await expect(page.getByRole("button", { name: "写博客", exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("agent_refresh_token"))).toBeNull();
  expect(await page.evaluate(() => localStorage.getItem("agent_auth_token"))).toBeNull();
  expect((await context.cookies()).find((item) => item.name === "blog_refresh")?.httpOnly).toBe(true);
});
