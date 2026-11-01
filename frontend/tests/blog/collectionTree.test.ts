/**
 * 领域目录树纯函数的单测。
 *
 * 重点覆盖 B-059 回归：**折叠父节点时，父节点自身必须仍然可见**，
 * 否则用户无法把它重新展开。同时覆盖父引用异常时的容错。
 *
 * 运行：npm run test:unit
 */

import test from "node:test";
import assert from "node:assert/strict";
import {
  buildCollectionTree,
  collapsibleIds,
  collectDescendantIds,
  collectTreeIds,
  flattenCollectionTree,
  isHiddenByAncestors,
  type FlatCollectionNode,
} from "../../src/features/blog/utils/collectionTree.ts";

function n(id: number, parent: number | null, position = 0, title = `N${id}`): FlatCollectionNode {
  return { id, title, description: "", position, parent };
}

/** 领域根 → 课程A(1) → 章节A1(2) → 知识点A1a(3)；领域根 → 课程B(4) */
const sample = [n(1, null, 0), n(2, 1, 0), n(3, 2, 0), n(4, null, 1)];

test("buildCollectionTree：按 parent 建树并按 position 排序，depth 从 1 开始", () => {
  const tree = buildCollectionTree(sample);
  assert.equal(tree.length, 2);
  assert.deepEqual(tree.map((t) => t.node.id), [1, 4]);
  assert.equal(tree[0].depth, 1);
  assert.equal(tree[0].children[0].node.id, 2);
  assert.equal(tree[0].children[0].depth, 2);
  assert.equal(tree[0].children[0].children[0].node.id, 3);
  assert.equal(tree[0].children[0].children[0].depth, 3);
});

test("buildCollectionTree：position 决定同级顺序，与输入顺序无关", () => {
  const tree = buildCollectionTree([n(10, null, 2), n(11, null, 0), n(12, null, 1)]);
  assert.deepEqual(tree.map((t) => t.node.id), [11, 12, 10]);
});

test("buildCollectionTree 容错：父引用不存在、自引用、成环都按根处理，节点不丢失", () => {
  const orphan = buildCollectionTree([n(1, 999)]);
  assert.deepEqual(orphan.map((t) => t.node.id), [1]);

  const selfRef = buildCollectionTree([n(1, 1)]);
  assert.deepEqual(selfRef.map((t) => t.node.id), [1]);

  // 1 ↔ 2 互为父子
  const cyclic = buildCollectionTree([n(1, 2), n(2, 1)]);
  const ids = collectTreeIds(cyclic).sort((a, b) => a - b);
  assert.deepEqual(ids, [1, 2], "成环时两个节点都必须出现在树里");
});

test("isHiddenByAncestors：只看祖先，不含自身（B-059 核心规则）", () => {
  const collapsed = new Set([1]);
  assert.equal(isHiddenByAncestors([1], collapsed), true, "祖先被折叠 → 隐藏");
  assert.equal(isHiddenByAncestors([1, 2], collapsed), true);
  assert.equal(isHiddenByAncestors([], collapsed), false, "没有祖先 → 永不隐藏（自身折叠不算）");
  assert.equal(isHiddenByAncestors([4], collapsed), false);
});

test("flattenCollectionTree（B-059 回归）：折叠父节点后，父节点自身仍可见、可再展开", () => {
  const tree = buildCollectionTree(sample);
  const rows = flattenCollectionTree(tree, new Set([1]));
  const ids = rows.map((r) => r.node.id);

  assert.ok(ids.includes(1), "被折叠的父节点自身必须保留，否则无法重新展开");
  assert.ok(!ids.includes(2), "子节点应被隐藏");
  assert.ok(!ids.includes(3), "孙节点也应被隐藏");
  assert.ok(ids.includes(4), "同级的其他分支不受影响");
});

test("flattenCollectionTree：未折叠时全部可见，且带 hasChildren/childCount", () => {
  const tree = buildCollectionTree(sample);
  const rows = flattenCollectionTree(tree, new Set());
  assert.deepEqual(rows.map((r) => r.node.id), [1, 2, 3, 4]);

  const row1 = rows.find((r) => r.node.id === 1)!;
  assert.equal(row1.hasChildren, true);
  assert.equal(row1.childCount, 1);
  assert.equal(row1.depth, 1);

  const row3 = rows.find((r) => r.node.id === 3)!;
  assert.equal(row3.hasChildren, false);
  assert.equal(row3.childCount, 0);
  assert.equal(row3.depth, 3);
});

test("flattenCollectionTree：多层折叠互不干扰", () => {
  const tree = buildCollectionTree(sample);
  // 折叠 1 与 2：1 可见，2、3 隐藏
  assert.deepEqual(flattenCollectionTree(tree, new Set([1, 2])).map((r) => r.node.id), [1, 4]);
  // 只折叠 2：1 可见，2 可见，3 隐藏
  assert.deepEqual(flattenCollectionTree(tree, new Set([2])).map((r) => r.node.id), [1, 2, 4]);
  // 只折叠 3（叶子，无实际作用）
  assert.deepEqual(flattenCollectionTree(tree, new Set([3])).map((r) => r.node.id), [1, 2, 3, 4]);
});

test("collectTreeIds / collectDescendantIds / collapsibleIds", () => {
  const tree = buildCollectionTree(sample);
  assert.deepEqual(collectTreeIds(tree).sort((a, b) => a - b), [1, 2, 3, 4]);
  assert.deepEqual(collectDescendantIds(tree[0]), [2, 3]);
  assert.deepEqual(collectDescendantIds(tree[1]), []);
  // 只有有子节点的才可折叠：3 与 4 是叶子
  assert.deepEqual(collapsibleIds(tree).sort((a, b) => a - b), [1, 2]);
});

test("全部折叠后仍能看到所有父节点本身（可逐个展开回来）", () => {
  const tree = buildCollectionTree(sample);
  const all = collapsibleIds(tree);
  const rows = flattenCollectionTree(tree, new Set(all));
  assert.deepEqual(rows.map((r) => r.node.id), [1, 4], "父节点与无子节点者必须保留");
});
