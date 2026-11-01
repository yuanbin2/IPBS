import { test } from "node:test";
import assert from "node:assert/strict";
import { shouldSyncExternalValue } from "../../src/features/blog/utils/editorSync.ts";

test("值相同（含往返抖动收敛后的等值）时不需要写回", () => {
  assert.equal(shouldSyncExternalValue("abc", "abc", false), false);
  assert.equal(shouldSyncExternalValue("", "", true), false);
});

test("编辑器持有焦点时一律不写回：空行回车等输入瞬间不能重建 DOM", () => {
  // 典型抖动：input 回调吐出的值与 getValue() 序列化结果不一致
  assert.equal(shouldSyncExternalValue("第一段\n\n", "第一段\n", true), false);
  assert.equal(shouldSyncExternalValue("不同", "不同二", true), false);
});

test("未聚焦且值不同时才允许外部同步", () => {
  assert.equal(shouldSyncExternalValue("第一段\n\n", "第一段\n", false), true);
  assert.equal(shouldSyncExternalValue("", "旧内容", false), true);
});
