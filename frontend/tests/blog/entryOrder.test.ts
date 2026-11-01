/**
 * 领域目录文章拖拽排序的纯逻辑单测（B-064 回归）。
 *
 * 核心回归点：拖拽落点必须换算成**同节点下全量 id 的新顺序**，
 * 列表被筛选框过滤时也不能算错（隐藏项保持相对顺序并让位）。
 *
 * 运行：npm run test:unit
 */

import test from "node:test";
import assert from "node:assert/strict";
import {
  isSameOrder,
  moveEntryRelative,
  sortEntriesByPosition,
  type OrderableEntry,
} from "../../src/features/blog/utils/entryOrder.ts";

test("sortEntriesByPosition：按 (position, id) 排序，与后端 ordering 一致", () => {
  const rows: OrderableEntry[] = [
    { id: 3, position: 1 },
    { id: 1, position: 2 },
    { id: 2, position: 1 },
  ];
  assert.deepEqual(
    sortEntriesByPosition(rows).map((row) => row.id),
    [2, 3, 1],
  );
});

test("sortEntriesByPosition：不改动原数组", () => {
  const rows: OrderableEntry[] = [
    { id: 2, position: 1 },
    { id: 1, position: 0 },
  ];
  const sorted = sortEntriesByPosition(rows);
  assert.deepEqual(rows.map((row) => row.id), [2, 1]);
  assert.deepEqual(sorted.map((row) => row.id), [1, 2]);
});

test("moveEntryRelative：往后拖（放到目标之后）", () => {
  assert.deepEqual(moveEntryRelative([1, 2, 3, 4], 1, 3, "after"), [2, 3, 1, 4]);
});

test("moveEntryRelative：往前拖（放到目标之前）", () => {
  assert.deepEqual(moveEntryRelative([1, 2, 3, 4], 4, 2, "before"), [1, 4, 2, 3]);
});

test("moveEntryRelative：相邻下移等价于交换", () => {
  assert.deepEqual(moveEntryRelative([1, 2, 3], 1, 2, "after"), [2, 1, 3]);
});

test("moveEntryRelative：相邻上移等价于交换", () => {
  assert.deepEqual(moveEntryRelative([1, 2, 3], 2, 1, "before"), [2, 1, 3]);
});

test("moveEntryRelative：拖到自己身上不改顺序", () => {
  assert.deepEqual(moveEntryRelative([1, 2, 3], 2, 2, "before"), [1, 2, 3]);
  assert.deepEqual(moveEntryRelative([1, 2, 3], 2, 2, "after"), [1, 2, 3]);
});

test("moveEntryRelative：id 不在列表中时原样返回", () => {
  assert.deepEqual(moveEntryRelative([1, 2, 3], 9, 2, "before"), [1, 2, 3]);
  assert.deepEqual(moveEntryRelative([1, 2, 3], 1, 9, "after"), [1, 2, 3]);
});

test("moveEntryRelative：空列表与单项列表不炸", () => {
  assert.deepEqual(moveEntryRelative([], 1, 1, "after"), []);
  assert.deepEqual(moveEntryRelative([7], 7, 7, "before"), [7]);
});

test("moveEntryRelative：拖到首位（before 第一项）", () => {
  assert.deepEqual(moveEntryRelative([1, 2, 3], 3, 1, "before"), [3, 1, 2]);
});

test("moveEntryRelative：拖到末位（after 最后一项）", () => {
  assert.deepEqual(moveEntryRelative([1, 2, 3], 1, 3, "after"), [2, 3, 1]);
});

test("moveEntryRelative：列表被筛选时隐藏项保持相对顺序", () => {
  // 真实顺序 [10,20,30,40,50]，可见 20/50；把 20 拖到 50 之后。
  // 隐藏的 30/40 必须仍夹在 20 与 50 之间被越过，最终 20 落在 50 之后。
  assert.deepEqual(moveEntryRelative([10, 20, 30, 40, 50], 20, 50, "after"), [10, 30, 40, 50, 20]);
  // 把 50 拖到 20 之前：隐藏的 30/40 仍在 20 之后、被拖项之后保持原序。
  assert.deepEqual(moveEntryRelative([10, 20, 30, 40, 50], 50, 20, "before"), [10, 50, 20, 30, 40]);
});

test("isSameOrder：长度或任一位不同即不等", () => {
  assert.equal(isSameOrder([1, 2, 3], [1, 2, 3]), true);
  assert.equal(isSameOrder([1, 2, 3], [1, 3, 2]), false);
  assert.equal(isSameOrder([1, 2], [1, 2, 3]), false);
});
