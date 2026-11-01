/**
 * 应用外壳可见性判断的单测（B-058 回归）。
 *
 * 覆盖两件事：
 * ① 未登录访客的公开展示页行为**保持不变**（/blog 系列仍然是干净裸页）；
 * ② 已登录用户访问 /blog 系列时**必须保留 AppShell**，否则领域目录等页面会
 *    丢失左侧导航、无法返回博客。
 *
 * 运行：npm run test:unit
 */

import test from "node:test";
import assert from "node:assert/strict";
import {
  BLOG_PATH_PREFIX,
  isBlogPath,
  shouldRenderWithoutShell,
} from "../../src/router/shellVisibility.ts";

test("isBlogPath：精确匹配 /blog 与 /blog/ 前缀，不误伤同前缀路径", () => {
  assert.equal(isBlogPath("/blog"), true);
  assert.equal(isBlogPath("/blog/"), true);
  assert.equal(isBlogPath("/blog/collections"), true);
  assert.equal(isBlogPath("/blog/collections/abc123"), true);
  assert.equal(isBlogPath("/blog/settings"), true);

  // 只是同前缀，不是 /blog 系列
  assert.equal(isBlogPath("/blogger"), false);
  assert.equal(isBlogPath("/blogs"), false);
  assert.equal(isBlogPath("/knowledge"), false);
  assert.equal(BLOG_PATH_PREFIX, "/blog");
});

test("未登录访客：/blog 系列保持裸页（公开访客体验不变）", () => {
  const cases = ["/blog", "/blog/collections", "/blog/collections/abc123"];
  for (const path of cases) {
    assert.equal(
      shouldRenderWithoutShell({ isPublic: true, path, isAuthenticated: false }),
      true,
      `未登录访问 ${path} 应为裸页`,
    );
  }
});

test("已登录用户：/blog 系列必须保留 AppShell（B-058 回归）", () => {
  const cases = [
    "/blog",
    "/blog/collections",
    "/blog/collections/abc123",
    "/blog/settings",
  ];
  for (const path of cases) {
    assert.equal(
      shouldRenderWithoutShell({ isPublic: true, path, isAuthenticated: true }),
      false,
      `已登录访问 ${path} 应保留外壳，否则左侧导航消失`,
    );
  }
});

test("已登录用户：非 /blog 的公开页面仍为裸页（行为不变）", () => {
  assert.equal(
    shouldRenderWithoutShell({ isPublic: true, path: "/landing", isAuthenticated: true }),
    true,
  );
  assert.equal(
    shouldRenderWithoutShell({ isPublic: true, path: "/login", isAuthenticated: true }),
    true,
  );
});

test("非公开路由一律走外壳，与登录状态无关", () => {
  for (const isAuthenticated of [true, false]) {
    for (const path of ["/knowledge", "/chat", "/mcp-tools", "/blog/collections/mine"]) {
      assert.equal(
        shouldRenderWithoutShell({ isPublic: false, path, isAuthenticated }),
        false,
        `${path}（isAuthenticated=${isAuthenticated}）应走外壳`,
      );
    }
  }
});

test("同前缀路径不会被误判为 /blog 系列", () => {
  // 若用朴素 startsWith("/blog") 实现，/blogger 会被误判成站内页面。
  assert.equal(
    shouldRenderWithoutShell({ isPublic: true, path: "/blogger", isAuthenticated: true }),
    true,
  );
});
