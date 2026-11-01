/**
 * 安全审计滚动分页的纯逻辑单测。
 *
 * 回归点：翻页追加不能产生重复 id 的行（Vue v-for key 会报重复），
 * 到底后不得再显示「下滑加载更多」，且 loading 态文案优先。
 *
 * 运行：npm run test:unit
 */

import test from "node:test";
import assert from "node:assert/strict";
import {
  auditFeedHint,
  mergeAuditEvents,
  shouldLoadOnScroll,
  type IdentifiableRow,
} from "../../src/features/security/utils/auditFeed.ts";

function rows(...ids: number[]): IdentifiableRow[] {
  return ids.map((id) => ({ id }));
}

test("mergeAuditEvents：追加新页并保持已有顺序", () => {
  const merged = mergeAuditEvents(rows(5, 4), rows(3, 2));
  assert.deepEqual(
    merged.map((row) => row.id),
    [5, 4, 3, 2],
  );
});

test("mergeAuditEvents：重复 id 只保留第一次出现的那行", () => {
  const merged = mergeAuditEvents(rows(9, 8), rows(8, 7, 9));
  assert.deepEqual(
    merged.map((row) => row.id),
    [9, 8, 7],
  );
});

test("mergeAuditEvents：空页返回原数组引用", () => {
  const existing = rows(2, 1);
  assert.equal(mergeAuditEvents(existing, []), existing);
});

test("mergeAuditEvents：不改动入参数组", () => {
  const existing = rows(2, 1);
  const incoming = rows(0);
  mergeAuditEvents(existing, incoming);
  assert.deepEqual(
    existing.map((row) => row.id),
    [2, 1],
  );
  assert.deepEqual(
    incoming.map((row) => row.id),
    [0],
  );
});

test("shouldLoadOnScroll：只有滚到接近底部才返回 true", () => {
  assert.equal(shouldLoadOnScroll(0, 400, 1000, 60), false);
  assert.equal(shouldLoadOnScroll(600, 400, 1000, 60), true);
  assert.equal(shouldLoadOnScroll(540, 400, 1000, 60), true);
});

test("shouldLoadOnScroll：内容不足一屏时 scrollTop 为 0 也算到底", () => {
  assert.equal(shouldLoadOnScroll(0, 400, 380, 60), true);
});

test("shouldLoadOnScroll：滚动框还没渲染（高度为 0）不触发", () => {
  assert.equal(shouldLoadOnScroll(0, 0, 0, 60), false);
});

test("auditFeedHint：加载中文案优先于条数文案", () => {
  assert.equal(auditFeedHint({ loaded: 3, total: 40, hasMore: true, loading: true }), "正在加载…");
});

test("auditFeedHint：首批未到且未知是否有更多时显示加载中", () => {
  assert.equal(auditFeedHint({ loaded: 0, total: 0, hasMore: true, loading: false }), "正在加载…");
});

test("auditFeedHint：还有下一页时给出已显示 / 总数", () => {
  assert.equal(auditFeedHint({ loaded: 20, total: 42, hasMore: true, loading: false }), "已显示 20 / 42 条，下滑加载更多");
});

test("auditFeedHint：到底后给出总量", () => {
  assert.equal(auditFeedHint({ loaded: 42, total: 42, hasMore: false, loading: false }), "已全部加载，共 42 条");
});

test("auditFeedHint：确实没有事件时不显示「正在加载」", () => {
  assert.equal(auditFeedHint({ loaded: 0, total: 0, hasMore: false, loading: false }), "暂无安全审计事件");
});
