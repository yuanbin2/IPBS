/**
 * 长截图滚动容器判定单测：窗口优先、尺寸护栏、最大容器选择、三点探测保留。
 * 运行：node --test tests/scroll-root.test.js
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import scrollRoot from "../shared/scroll-root.js";

const { resolveScrollMode } = scrollRoot;

/** 便捷构造：innerHeight 800，祖先链从命中元素向 document 方向排列。 */
function decide(ancestors, { scrollHeight = 700, innerHeight = 800 } = {}) {
  return resolveScrollMode({ scrollingElementScrollHeight: scrollHeight, innerHeight, ancestors });
}

const codeBlock = { clientHeight: 300, scrollHeight: 5000, overflowY: "auto" };
const mainContainer = { clientHeight: 700, scrollHeight: 9000, overflowY: "auto" };

test("窗口可滚 + 链上有代码块 → 窗口模式（代码块不抢 root，面试鸭案例）", () => {
  assert.equal(decide([codeBlock, mainContainer], { scrollHeight: 6000 }), -1);
});

test("窗口不可滚 + 主容器达标 → 容器模式，且跳过代码块选主容器", () => {
  assert.equal(decide([codeBlock, mainContainer]), 1);
});

test("窗口不可滚 + 只有代码块（300 < 0.5×800 护栏）→ 窗口模式", () => {
  // 取舍：页面此时其实无处可滚（窗口也不可滚），与其把监听挂在小容器上
  // 采出坐标错乱的碎片，不如按窗口模式采集——宁可整段不可采也不采错。
  assert.equal(decide([codeBlock]), -1);
});

test("尺寸护栏：clientHeight < 200 的小容器一律不选", () => {
  const small = { clientHeight: 150, scrollHeight: 4000, overflowY: "auto" };
  assert.equal(decide([small]), -1);
});

test("命中多个合格容器 → 取 clientHeight 最大者", () => {
  const medium = { clientHeight: 420, scrollHeight: 9000, overflowY: "auto" };
  const large = { clientHeight: 760, scrollHeight: 9000, overflowY: "auto" };
  assert.equal(decide([medium, large]), 1);
  assert.equal(decide([large, medium]), 0);
});

test("overflowY 不为 auto/scroll/overlay 的元素不参评", () => {
  const visible = { clientHeight: 700, scrollHeight: 9000, overflowY: "visible" };
  const clipped = { clientHeight: 700, scrollHeight: 9000, overflowY: "clip" };
  assert.equal(decide([visible, clipped]), -1);
});

test("内容没超出（scrollHeight ≤ clientHeight + 16）不参评", () => {
  const full = { clientHeight: 700, scrollHeight: 708, overflowY: "auto" };
  assert.equal(decide([full]), -1);
});

test("三点探测（上缘/中心/下缘）行为保留：pickWidth 仍依次探测三处命中", () => {
  const source = readFileSync(new URL("../shared/shot-content.js", import.meta.url), "utf8");
  assert.match(source, /findScrollRoot\(hitX, Math\.min\(window\.innerHeight - 1, topClient \+ 10\)\)/);
  assert.match(source, /findScrollRoot\(hitX, Math\.min\(window\.innerHeight - 1, Math\.max\(0, middleClient\)\)\)/);
  assert.match(source, /findScrollRoot\(hitX, Math\.min\(window\.innerHeight - 1, bottomClient - 10\)\)/);
});
