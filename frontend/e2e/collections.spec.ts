import { expect, test, type Page } from "@playwright/test";

const password = "Upload-e2e-only-2026!";
const operator = "upload-e2e-operator";
const reader = "upload-e2e-reader";
const admin = "upload-e2e-admin";

async function login(page: Page, username: string, destination = "/blog") {
  await page.goto(`/login?redirect=${encodeURIComponent(destination)}`);
  await page.getByPlaceholder("用户名").fill(username);
  await page.getByPlaceholder("密码，至少 8 位").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${destination.replaceAll("/", "\\/")}$`));
}

async function createArticleDraft(page: Page, title: string): Promise<{ slug: string; approvalId: number }> {
  return page.evaluate(async (articleTitle) => {
    const create = await fetch("/api/agent/blog/articles/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: articleTitle,
        summary: `${articleTitle} 摘要`,
        content: `# ${articleTitle}\n\n这是用于领域目录测试的正文。`,
      }),
    });
    if (create.status !== 202) throw new Error(`article create failed: ${create.status}`);
    const payload = await create.json();
    return { slug: payload.article.slug as string, approvalId: payload.approval.id as number };
  }, title);
}

test("author builds a three-level collection, publishes it, and a reader follows the path", async ({ page, browser }) => {
  test.setTimeout(120_000);
  await login(page, operator);

  // 准备三篇已发布文章：operator 创建 → admin 审批
  const titles = ["快速排序实现", "归并排序边界", "排序算法对比"];
  const drafts = [];
  for (const title of titles) {
    drafts.push(await createArticleDraft(page, title));
  }
  const adminSetup = await browser.newContext();
  try {
    const adminPage = await adminSetup.newPage();
    await login(adminPage, admin);
    for (const draft of drafts) {
      const status = await adminPage.evaluate(async (id) => {
        const response = await fetch(`/api/agent/approvals/${id}/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision: "approve" }),
        });
        return response.status;
      }, draft.approvalId);
      expect(status).toBe(200);
    }
  } finally {
    await adminSetup.close();
  }
  const slugs = drafts.map((draft) => draft.slug);

  // 博客首页 → 领域目录 → 我的领域
  await page.goto("/blog");
  await page.getByRole("button", { name: "领域目录", exact: true }).click();
  await expect(page).toHaveURL(/\/blog\/collections$/);
  await page.getByRole("button", { name: "我的领域", exact: true }).click();
  await expect(page).toHaveURL(/\/blog\/collections\/mine$/);

  // 创建领域
  await page.getByLabel("新领域标题").fill("算法学习路径");
  await page.getByLabel("新领域简介").fill("按课程组织的算法学习路线");
  await page.getByRole("button", { name: "创建领域" }).click();
  await expect(page.getByText("编辑：算法学习路径")).toBeVisible();

  // 三级目录：基础课 → 第一讲 → 排序
  await page.locator(".node-create .parent-select").click();
  await page.getByRole("option", { name: "领域根" }).click();
  await page.getByLabel("节点标题", { exact: true }).fill("基础课");
  await page.getByRole("button", { name: "添加节点" }).click();
  await expect(page.getByRole("list", { name: "节点列表" })).toContainText("基础课");

  await page.locator(".node-create .parent-select").click();
  await page.getByRole("option", { name: "基础课" }).click();
  await page.getByLabel("节点标题", { exact: true }).fill("第一讲");
  await page.getByRole("button", { name: "添加节点" }).click();
  await expect(page.getByRole("list", { name: "节点列表" })).toContainText("第一讲");

  await page.locator(".node-create .parent-select").click();
  await page.getByRole("option", { name: "第一讲" }).click();
  await page.getByLabel("节点标题", { exact: true }).fill("排序");
  await page.getByRole("button", { name: "添加节点" }).click();
  await expect(page.getByRole("list", { name: "节点列表" })).toContainText("排序");

  // 加入文章：两篇挂“排序”，一篇挂领域根
  await page.locator(".entry-create .parent-select").click();
  await page.locator('.el-select-dropdown:visible li[role="option"]:not(.is-disabled)').filter({ hasText: "排序" }).first().click();
  for (const title of ["快速排序实现", "归并排序边界"]) {
    await page.getByLabel("搜索文章", { exact: true }).fill(title);
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await page.locator(".entry-pick .article-select").click();
    await page.locator('.el-select-dropdown:visible li[role="option"]:not(.is-disabled)').filter({ hasText: title }).first().click();
    await page.getByRole("button", { name: /加入所选/ }).click();
    await expect(page.locator(".entry-list")).toContainText(title);
  }

  await page.locator(".entry-create .parent-select").click();
  await page.getByRole("option", { name: "领域根" }).click();
  await page.getByLabel("搜索文章", { exact: true }).fill("排序算法对比");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await page.locator(".entry-pick .article-select").click();
  await page.locator('.el-select-dropdown:visible li[role="option"]:not(.is-disabled)').filter({ hasText: "排序算法对比" }).first().click();
  await page.getByRole("button", { name: /加入所选/ }).click();
  await expect(page.locator(".entry-list")).toContainText("排序算法对比");

  // 按钮排序：把“快速排序实现”下移（同节点内相对顺序改变）
  const quickRow = page.locator(".entry-list .node-row").filter({ hasText: "快速排序实现" });
  await quickRow.getByLabel("下移文章").click();
  await expect
    .poll(async () => {
      const text = await page.locator(".entry-list").innerText();
      return text.indexOf("归并排序边界") < text.indexOf("快速排序实现");
    })
    .toBe(true);

  // 提交审核
  await page.getByRole("button", { name: "提交审核公开" }).click();
  await expect(page.locator(".submit-row")).toContainText("待审中");

  // 管理员批准
  const approvalId = await page.evaluate(async () => {
    const mine = await fetch("/api/agent/blog/collections/mine/");
    const payload = await mine.json();
    return payload.items[0].pending_approval_id as number;
  });
  const adminCtx = await browser.newContext();
  let collectionPublicId = "";
  try {
    const adminPage = await adminCtx.newPage();
    await login(adminPage, admin);
    const decision = await adminPage.evaluate(async (id) => {
      const response = await fetch(`/api/agent/approvals/${id}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approve" }),
      });
      return response.status;
    }, approvalId);
    expect(decision).toBe(200);
    collectionPublicId = await page.evaluate(async () => {
      const mine = await fetch("/api/agent/blog/collections/mine/");
      const payload = await mine.json();
      return payload.items[0].public_id as string;
    });
  } finally {
    await adminCtx.close();
  }

  // 非作者读者：领域列表 → 目录页 → 文章 → 前后篇
  const readerContext = await browser.newContext();
  try {
    const readerPage = await readerContext.newPage();
    await login(readerPage, reader);
    await readerPage.goto("/blog/collections");
    await expect(readerPage.locator(".collection-card")).toContainText("算法学习路径");
    await readerPage.locator(".collection-card").first().getByRole("button", { name: "进入目录" }).click();
    await expect(readerPage).toHaveURL(new RegExp(`/blog/collections/${collectionPublicId}`));
    const body = readerPage.locator(".collection-main");
    await expect(body).toContainText("基础课");
    await expect(body).toContainText("排序算法对比");
    await body.getByRole("button", { name: /基础课/ }).first().click();
    await expect(body).toContainText("第一讲");
    await body.getByRole("button", { name: /第一讲/ }).last().click();
    await expect(body).toContainText("排序");
    await body.getByRole("button", { name: /排序/ }).last().click();
    await expect(body).toContainText("快速排序实现");
    await expect(body).toContainText("归并排序边界");

    // 点击树中节点 → URL 记录位置 → 刷新恢复
    await readerPage.locator(".tree-item", { hasText: "排序" }).first().click();
    await expect(readerPage).toHaveURL(/node=\d+/);
    await readerPage.reload();
    await expect(readerPage.locator(".collection-main")).toContainText("第一讲");

    // 从文章进详情：返回目录 + 前后篇
    await readerPage.locator(".node-article-link", { hasText: "归并排序边界" }).first().click();
    await expect(readerPage).toHaveURL(new RegExp(`/blog/${encodeURIComponent(slugs[1])}`));
    const contextBar = readerPage.locator(".collection-context-bar");
    await expect(contextBar).toContainText("返回目录：算法学习路径");
    await expect(contextBar).toContainText("上一篇");
    await expect(contextBar).toContainText("下一篇");
    await contextBar.locator(".collection-neighbor", { hasText: "下一篇" }).click();
    await expect(readerPage).toHaveURL(new RegExp(`/blog/${encodeURIComponent(slugs[0])}`));
    await expect(readerPage.locator(".collection-context-bar")).toContainText("上一篇");

    // 隐藏文章：管理员删除“归并排序边界”，公开目录立即不再显示
    const adminForDelete = await browser.newContext();
    try {
      const adminPage = await adminForDelete.newPage();
      await login(adminPage, admin);
      const deleteStatus = await adminPage.evaluate(async (slug) => {
        const remove = await fetch(`/api/agent/blog/articles/${slug}/`, { method: "DELETE" });
        if (!remove.ok) return remove.status;
        const approval = (await remove.json()) as { approval: { id: number } };
        const approve = await fetch(`/api/agent/approvals/${approval.approval.id}/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision: "approve" }),
        });
        return approve.status;
      }, slugs[1]);
      expect(deleteStatus).toBe(200);
    } finally {
      await adminForDelete.close();
    }
    await readerPage.goto(`/blog/collections/${collectionPublicId}`);
    await readerPage.locator(".collection-tree .tree-item", { hasText: "排序" }).last().click();
    const bodyAfterHide = readerPage.locator(".collection-main");
    await expect(bodyAfterHide).toContainText("快速排序实现");
    await expect(bodyAfterHide).not.toContainText("归并排序边界");
  } finally {
    await readerContext.close();
  }
});

test("stale approval cannot publish, private collections stay 404, and narrow viewport keeps the tree usable", async ({ page, browser }) => {
  test.setTimeout(180_000);
  await login(page, operator);

  // 通过 API 建第二个领域：提交 v1 → 修改后提交 v2（旧的自动失效）
  const { publicId, staleApprovalId, freshApprovalId, privateId } = await page.evaluate(async () => {
    const post = async (url: string, body: unknown) => {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok && response.status !== 202 && response.status !== 201) {
        throw new Error(`${url} -> ${response.status}`);
      }
      return response.json();
    };
    const created = (await post("/api/agent/blog/collections/", { title: "过时审批领域", description: "v1 简介" })) as {
      public_id: string;
      draft_version: number;
    };
    const draftUrl = `/api/agent/blog/collections/${created.public_id}/draft/`;
    const patch = async (body: Record<string, unknown>) => {
      const response = await fetch(draftUrl, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`patch -> ${response.status}`);
      return response.json();
    };
    const first = (await post(`/api/agent/blog/collections/${created.public_id}/submit/`, {})) as { approval_id: number };
    await patch({ description: "v2 简介", expected_version: created.draft_version });
    const second = (await post(`/api/agent/blog/collections/${created.public_id}/submit/`, {})) as { approval_id: number };
    const privateOne = (await post("/api/agent/blog/collections/", { title: "私有未公开领域" })) as { public_id: string };
    return {
      publicId: created.public_id,
      staleApprovalId: first.approval_id,
      freshApprovalId: second.approval_id,
      privateId: privateOne.public_id,
    };
  });

  const adminContext = await browser.newContext();
  try {
    const adminPage = await adminContext.newPage();
    await login(adminPage, admin);
    const staleStatus = await adminPage.evaluate(async (id) => {
      const response = await fetch(`/api/agent/approvals/${id}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approve" }),
      });
      return { status: response.status, detail: (await response.json()).detail ?? "" };
    }, staleApprovalId);
    expect(staleStatus.status).toBe(400);
    const freshStatus = await adminPage.evaluate(async (id) => {
      const response = await fetch(`/api/agent/approvals/${id}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: "approve" }),
      });
      return response.status;
    }, freshApprovalId);
    expect(freshStatus).toBe(200);
  } finally {
    await adminContext.close();
  }

  // 未公开目录对非 owner 404；跨用户看不到别人的“我的领域”
  const readerContext = await browser.newContext();
  try {
    const readerPage = await readerContext.newPage();
    await login(readerPage, reader);
    await readerPage.goto("/blog/collections/mine");
    await expect(readerPage.getByText("还没有领域草稿")).toBeVisible();
    // 从未提交的私有目录对非 owner 一律 404
    await readerPage.goto(`/blog/collections/${privateId}`);
    await expect(readerPage.locator(".el-alert")).toContainText("领域不存在或尚未公开");
  } finally {
    await readerContext.close();
  }

  // 已公开领域在窄屏下目录可展开、正文可读；宽屏下树与正文并排
  await page.goto(`/blog/collections/${publicId}`);
  await expect(page.locator(".collection-main")).toContainText("过时审批领域");
  await page.setViewportSize({ width: 390, height: 844 });
  const toggle = page.locator(".tree-toggle");
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(page.locator(".collection-tree")).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(page.locator(".collection-tree")).toBeVisible();
});
