import { expect, test } from "@playwright/test";

test("article navigation updates and clears browser metadata", async ({ page }) => {
  const article = {
    id: 8017, title: "SEO 测试文章", slug: "seo-fixture", author_name: "tester",
    summary: "可分享的公开摘要", cover_image: "", content: "# 公开正文",
    status: "published", view_count: 0, category: null, tags: [],
    published_at: "2026-10-24T00:00:00Z", publication_version: 1,
    created_at: "2026-10-24T00:00:00Z", updated_at: "2026-10-24T00:00:00Z",
    knowledge_document_id: null, comment_count: 0, comments: [],
  };
  await page.route(/\/api\/agent\/blog\/articles\/discover\/\?/, (route) => route.fulfill({
    json: { items: [article], total: 1, pages: 1, page: 1, page_size: 12 },
  }));
  await page.route("**/api/agent/blog/articles/seo-fixture/?include_comments=0", (route) => route.fulfill({ json: article }));
  await page.goto("/blog");
  await expect(page.locator(".article-card")).toHaveCount(1);
  await page.locator(".article-card").click();
  await expect(page).toHaveURL(/\/blog\/seo-fixture/);
  await expect(page).toHaveTitle("SEO 测试文章");
  await expect(page.locator('head meta[property="og:title"]')).toHaveAttribute("content", "SEO 测试文章");
  await expect(page.locator('head link[rel="canonical"]')).toHaveAttribute("href", /\/blog\/seo-fixture\/$/);
  await page.reload();
  await expect(page).toHaveTitle("SEO 测试文章");

  await page.getByRole("button", { name: "返回文章列表" }).click();
  await expect(page).toHaveURL(/\/blog$/);
  await expect(page).toHaveTitle("智能个人博客系统");
  await expect(page.locator("head meta[property='og:title']")).toHaveCount(0);
});
