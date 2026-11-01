import test from "node:test";
import assert from "node:assert/strict";
import { safeImageCandidateOverflow, safeImageCandidates } from "../../src/features/blog/utils/screenshotHandoff.ts";

test("旧 screenshot-v1 缺少候选元数据时兼容为空列表", () => {
  assert.deepEqual(safeImageCandidates(undefined), []);
  assert.equal(safeImageCandidateOverflow(undefined), 0);
});

test("候选溢出计数必须是有界非负整数", () => {
  assert.equal(safeImageCandidateOverflow(24), 24);
  assert.equal(safeImageCandidateOverflow(-1), null);
  assert.equal(safeImageCandidateOverflow(1.5), null);
  assert.equal(safeImageCandidateOverflow(10_001), null);
});

test("接收端拒绝越界、部分完整矩形、URL 字段和超量候选元数据", () => {
  assert.equal(safeImageCandidates([{ x: 0, y: 0, width: 1, height: 0.1, fullY: 100 }]), null);
  assert.equal(safeImageCandidates([{ x: 0, y: 0, width: 1.1, height: 0.1 }]), null);
  assert.equal(safeImageCandidates([{ x: 0, y: 0, width: 1, height: 0.1, src: "https://private.example/image" }]), null);
  // 每屏候选上限已放宽到 60（图片+代码块）：61 个才拒绝
  assert.equal(safeImageCandidates(Array.from({ length: 61 }, () => ({ x: 0, y: 0, width: 0.1, height: 0.1 }))), null);
});

test("代码块候选的 kind 字段与 code- 前缀 key 正常通过，非法 kind 被拒绝", () => {
  assert.deepEqual(
    safeImageCandidates([{ key: "code-3", x: 0.1, y: 0.2, width: 0.5, height: 0.2, kind: "code", priority: 2 }]),
    [{ key: "code-3", x: 0.1, y: 0.2, width: 0.5, height: 0.2, kind: "code", priority: 2 }],
  );
  assert.equal(safeImageCandidates([{ x: 0.1, y: 0.2, width: 0.5, height: 0.2, kind: "video" }]), null);
  assert.equal(safeImageCandidates([{ x: 0.1, y: 0.2, width: 0.5, height: 0.2, key: "img-9" }]), null);
});

test("有界、无源地址的完整矩形正常通过", () => {
  assert.deepEqual(safeImageCandidates([{ key: "17", x: 0.1, y: 0.9, width: 0.4, height: 0.1,
    fullX: 0.1, fullY: 400, fullWidth: 0.4, fullHeight: 260, priority: 1 }]),
  [{ key: "17", x: 0.1, y: 0.9, width: 0.4, height: 0.1, fullX: 0.1, fullY: 400,
    fullWidth: 0.4, fullHeight: 260, priority: 1 }]);
});
