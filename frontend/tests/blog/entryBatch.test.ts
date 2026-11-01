import { test } from "node:test";
import assert from "node:assert/strict";

import {
  autoRuleKey,
  autoRuleLabel,
  canCreateRule,
  dedupeArticleIds,
  pendingArticleIds,
  summarizeBatchResult,
} from "../../src/features/blog/utils/entryBatch.ts";

test("dedupeArticleIds 过滤非法值并保持顺序", () => {
  assert.deepEqual(dedupeArticleIds([3, 1, 3, 2]), [3, 1, 2]);
  assert.deepEqual(dedupeArticleIds([5, "6", 0, -1, null, undefined, 1.5]), [5, 6]);
  assert.deepEqual(dedupeArticleIds("not-a-list"), []);
});

test("pendingArticleIds 去掉已收录的文章", () => {
  assert.deepEqual(pendingArticleIds([1, 2, 3], [2]), [1, 3]);
  assert.deepEqual(pendingArticleIds([1, 2], [1, 2]), []);
  assert.deepEqual(pendingArticleIds([], [1]), []);
});

test("summarizeBatchResult 覆盖四种组合", () => {
  assert.match(summarizeBatchResult(3, 0), /已加入 3 篇/);
  assert.match(summarizeBatchResult(2, 1), /已加入 2 篇/);
  assert.match(summarizeBatchResult(2, 1), /1 篇此前已在目录中/);
  assert.match(summarizeBatchResult(0, 2), /已经在该目录中/);
  assert.match(summarizeBatchResult(0, 0), /没有可加入的文章/);
});

test("autoRuleLabel 展示分类、标签与落点", () => {
  assert.equal(
    autoRuleLabel({ node: 7, node_label: "第一章", category: { id: 1, name: "算法" } }),
    "算法 → 第一章",
  );
  assert.equal(
    autoRuleLabel({ node: 7, node_label: "第一章", category: { id: 1, name: "算法" }, tag: { id: 2, name: "动态规划" } }),
    "算法 #动态规划 → 第一章",
  );
  assert.equal(autoRuleLabel({ node: null, category: { id: 1, name: "随笔" } }), "随笔 → 领域根");
});

test("autoRuleKey 区分节点与标签组合", () => {
  assert.equal(autoRuleKey(7, 1, null), "7/1/-");
  assert.equal(autoRuleKey(null, 1, 2), "root/1/2");
  assert.notEqual(autoRuleKey(7, 1, null), autoRuleKey(null, 1, null));
});

test("canCreateRule 要求分类必填", () => {
  assert.equal(canCreateRule(3), true);
  assert.equal(canCreateRule(null), false);
  assert.equal(canCreateRule(0), false);
  assert.equal(canCreateRule(undefined), false);
});
