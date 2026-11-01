/**
 * B-045 长页截图单元测试：跨屏图片候选合并（mergeCrossTileCandidates）。
 * 同一张网页图片（稳定 key）分布在两个视口时，在拼接长图上只应产生
 * 一个覆盖整张图片的候选框，而不是让用户逐段手工拼图。
 * 运行：node --test tests/ocr/
 */

import test from "node:test";
import assert from "node:assert/strict";

import { mergeCrossTileCandidates, verifyCandidatePixelOverlaps } from "../../src/features/blog/utils/longScreenshot.ts";

type TestTile = Parameters<typeof mergeCrossTileCandidates>[0][number];

function tile(overrides: Partial<TestTile> & { index: number }): TestTile {
  return { scrollY: 0, height: 860, imageCandidates: [], ...overrides };
}

const SELECTION = { top: 0, bottom: 860 };
const VIEWPORT_CSS = 430;

test("跨屏图片：同 key 在两个视口的片段合并为一个覆盖整图的候选框", () => {
  // 一张页面 y 300–560 的图：视口 0（页面 0–430）露出下半段，
  // 视口 1（页面 430–860）露出上半段（tile 内归一化 y=0 起）。
  const tiles: TestTile[] = [
    tile({ index: 0, scrollY: 0, imageCandidates: [{ key: "img-1", x: 0.1, y: 300 / 430, width: 0.5, height: 130 / 430 }] }),
    tile({ index: 1, scrollY: 430, imageCandidates: [{ key: "img-1", x: 0.1, y: 0, width: 0.5, height: 130 / 430 }] }),
  ];
  const merged = mergeCrossTileCandidates(tiles, SELECTION, VIEWPORT_CSS);
  assert.equal(merged.length, 1);
  const box = merged[0];
  assert.equal(box.key, "img-1");
  assert.equal(box.tileIndex, 0);
  assert.ok(Math.abs(box.x - 0.1) < 1e-9);
  assert.ok(Math.abs(box.width - 0.5) < 1e-9);
  // 页面 300–560 映射到 0–860 的拼接图上
  assert.ok(Math.abs(box.y - 300 / 860) < 1e-9);
  assert.ok(Math.abs(box.height - 260 / 860) < 1e-9);
  // anchorY 取首次出现 tile 的设备像素中心
  assert.ok(Math.abs(box.anchorY - (300 / 430 + (130 / 430) / 2) * 860) < 1e-9);
});

test("不同 key 的图片各自成框，不互相吞并", () => {
  const tiles: TestTile[] = [
    tile({ index: 0, scrollY: 0, imageCandidates: [
      { key: "img-a", x: 0.1, y: 0.1, width: 0.3, height: 0.2 },
      { key: "img-b", x: 0.5, y: 0.6, width: 0.4, height: 0.3 },
    ] }),
  ];
  const merged = mergeCrossTileCandidates(tiles, SELECTION, VIEWPORT_CSS);
  assert.equal(merged.length, 2);
  assert.deepEqual(merged.map((item) => item.key).sort(), ["img-a", "img-b"]);
});

test("代码块候选跨屏合并时保留 kind 标记", () => {
  // 页面 y 200–500 的 <pre>：视口 0 露出下半段，视口 1 露出上半段。
  const tiles: TestTile[] = [
    tile({ index: 0, scrollY: 0, imageCandidates: [
      { key: "code-1", x: 0.1, y: 200 / 430, width: 0.6, height: 230 / 430, fullX: 0.1, fullY: 200, fullWidth: 0.6, fullHeight: 300, priority: 2, kind: "code" },
    ] }),
    tile({ index: 1, scrollY: 430, imageCandidates: [
      { key: "code-1", x: 0.1, y: 0, width: 0.6, height: 70 / 430, fullX: 0.1, fullY: 200, fullWidth: 0.6, fullHeight: 300, priority: 2, kind: "code" },
    ] }),
  ];
  const merged = mergeCrossTileCandidates(tiles, SELECTION, VIEWPORT_CSS);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].kind, "code");
  assert.equal(merged[0].coverage, "complete");
});

test("无 key 的片段作为独立待确认候选保留，不凭相邻位置猜成同一张图", () => {
  const tiles: TestTile[] = [
    tile({ index: 0, scrollY: 0, imageCandidates: [{ x: 0.1, y: 0.1, width: 0.3, height: 0.2 }] }),
    tile({ index: 1, scrollY: 430, imageCandidates: [{ x: 0.1, y: 0.2, width: 0.3, height: 0.2 }] }),
  ];
  const merged = mergeCrossTileCandidates(tiles, SELECTION, VIEWPORT_CSS);
  assert.equal(merged.length, 2);
  assert.ok(merged.every((candidate) => candidate.origin === "dom"));
});

test("key 改变时几何重合但像素证据缺失则不合并；通过真实重叠像素验证后合并", () => {
  const tiles: TestTile[] = [
    tile({ index: 0, scrollY: 0, imageCandidates: [{ key: "10", x: 0.2, y: 420 / 430, width: 0.4, height: 10 / 430,
      fullX: 0.2, fullY: 420, fullWidth: 0.4, fullHeight: 40 }] }),
    tile({ index: 1, scrollY: 365, imageCandidates: [{ key: "91", x: 0.2, y: 55 / 430, width: 0.4, height: 40 / 430,
      fullX: 0.2, fullY: 420, fullWidth: 0.4, fullHeight: 40 }] }),
  ];
  const withoutPixelProof = mergeCrossTileCandidates(tiles, SELECTION, VIEWPORT_CSS);
  assert.equal(withoutPixelProof.length, 2);
  const merged = mergeCrossTileCandidates(tiles, SELECTION, VIEWPORT_CSS,
    [{ firstTile: 0, firstCandidate: 0, secondTile: 1, secondCandidate: 0 }]);
  assert.equal(merged.length, 1);
  assert.equal(merged[0]!.coverage, "complete");
  assert.ok(Math.abs(merged[0]!.height - 40 / 860) < 1e-9);
});

test("同 key 被虚拟列表复用到另一位置时保留两张候选", () => {
  const tiles: TestTile[] = [
    tile({ index: 0, scrollY: 0, imageCandidates: [{ key: "7", x: 0.2, y: 0.2, width: 0.4, height: 0.2,
      fullX: 0.2, fullY: 80, fullWidth: 0.4, fullHeight: 80 }] }),
    tile({ index: 1, scrollY: 430, imageCandidates: [{ key: "7", x: 0.2, y: 0.2, width: 0.4, height: 0.2,
      fullX: 0.2, fullY: 510, fullWidth: 0.4, fullHeight: 80 }] }),
  ];
  assert.equal(mergeCrossTileCandidates(tiles, SELECTION, VIEWPORT_CSS).length, 2);
});

test("三屏候选在偏移选区中按统一页面坐标映射，并把未覆盖的完整元素标为部分图片", () => {
  const tiles: TestTile[] = [
    tile({ index: 0, scrollY: 100, imageCandidates: [{ key: "1", x: 0.2, y: 300 / 430, width: 0.4, height: 130 / 430,
      fullX: 0.2, fullY: 400, fullWidth: 0.4, fullHeight: 600 }] }),
    tile({ index: 1, scrollY: 465, imageCandidates: [{ key: "2", x: 0.2, y: 0, width: 0.4, height: 365 / 430,
      fullX: 0.2, fullY: 400, fullWidth: 0.4, fullHeight: 600 }] }),
    tile({ index: 2, scrollY: 795, imageCandidates: [{ key: "3", x: 0.2, y: 0, width: 0.4, height: 105 / 430,
      fullX: 0.2, fullY: 400, fullWidth: 0.4, fullHeight: 600 }] }),
  ];
  const merged = mergeCrossTileCandidates(tiles, { top: 120, bottom: 900 }, VIEWPORT_CSS, [
    { firstTile: 0, firstCandidate: 0, secondTile: 1, secondCandidate: 0 },
    { firstTile: 1, firstCandidate: 0, secondTile: 2, secondCandidate: 0 },
  ]);
  assert.equal(merged.length, 1);
  assert.equal(merged[0]!.coverage, "partial");
  assert.ok(Math.abs(merged[0]!.y - 280 / 780) < 1e-9);
  assert.ok(Math.abs(merged[0]!.height - (1 - 280 / 780)) < 1e-9);
  assert.equal(merged[0]!.fragments?.length, 3);
});

test("同一几何的候选跨采集缺口合并但明确标为缺口", () => {
  const tiles: TestTile[] = [
    tile({ index: 0, scrollY: 0, coveredCssHeight: 200, imageCandidates: [{ key: "3", x: 0.2, y: 0.5, width: 0.4, height: 0.25,
      fullX: 0.2, fullY: 100, fullWidth: 0.4, fullHeight: 220 }] }),
    tile({ index: 1, scrollY: 240, coveredCssHeight: 200, imageCandidates: [{ key: "3", x: 0.2, y: 0, width: 0.4, height: 0.4,
      fullX: 0.2, fullY: 100, fullWidth: 0.4, fullHeight: 220 }] }),
  ];
  const merged = mergeCrossTileCandidates(tiles, { top: 0, bottom: 500 }, 200);
  assert.equal(merged.length, 1);
  assert.equal(merged[0]!.coverage, "gap");
});

test("key 不同时只在相邻 tile 的实际重叠像素相似时提供合并证据", async () => {
  const oldDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
  const oldBitmap = Object.getOwnPropertyDescriptor(globalThis, "createImageBitmap");
  let currentImage = "";
  let different = false;
  Object.defineProperty(globalThis, "document", { configurable: true, value: {
    createElement: () => ({ width: 0, height: 0, getContext: () => ({
      drawImage: (bitmap: { name: string }) => { currentImage = bitmap.name; },
      getImageData: () => ({ data: new Uint8ClampedArray(8 * 8 * 4).map((_, index) =>
        index % 4 === 3 ? 255 : currentImage === "b" && different ? 240 : 40) }),
    }) }),
  } });
  Object.defineProperty(globalThis, "createImageBitmap", { configurable: true, value: async (file: { name: string }) => ({
    name: file.name, width: 100, height: 200, close() {},
  }) });
  const candidate = (key: string, y: number, height: number) => ({ key, x: 0.1, y, width: 0.4, height,
    fullX: 0.1, fullY: 100, fullWidth: 0.4, fullHeight: 100 });
  const tiles = [
    { file: { name: "a" } as File, width: 100, height: 200, scrollX: 0, scrollY: 0, coveredCssHeight: 200,
      index: 5, imageCandidates: [candidate("old-key", 0.5, 0.25)] },
    { file: { name: "b" } as File, width: 100, height: 200, scrollX: 0, scrollY: 120, coveredCssHeight: 200,
      index: 6, imageCandidates: [candidate("new-key", 0, 0.4)] },
  ];
  try {
    assert.deepEqual(await verifyCandidatePixelOverlaps(tiles), [{ firstTile: 5, firstCandidate: 0, secondTile: 6, secondCandidate: 0 }]);
    different = true;
    assert.deepEqual(await verifyCandidatePixelOverlaps(tiles), []);
  } finally {
    if (oldDocument) Object.defineProperty(globalThis, "document", oldDocument);
    else Reflect.deleteProperty(globalThis, "document");
    if (oldBitmap) Object.defineProperty(globalThis, "createImageBitmap", oldBitmap);
    else Reflect.deleteProperty(globalThis, "createImageBitmap");
  }
});

test("超出选区边界的坐标被钳制到拼接图范围内", () => {
  // selection.top=100：视口 0 里贴顶的图片映射后 y 为负，应钳到 0；
  // 底部超出 selection.bottom 的部分钳到 1。
  const tiles: TestTile[] = [
    tile({ index: 0, scrollY: 0, coveredCssHeight: VIEWPORT_CSS, imageCandidates: [
      { key: "img-top", x: 0, y: 0, width: 1, height: 0.5 },
    ] }),
    tile({ index: 1, scrollY: 536.25, coveredCssHeight: VIEWPORT_CSS, imageCandidates: [
      { key: "img-bottom", x: 0, y: 0.5, width: 1, height: 0.5 },
    ] }),
  ];
  const merged = mergeCrossTileCandidates(tiles, { top: 100, bottom: 960 }, VIEWPORT_CSS);
  const byKey = new Map(merged.map((item) => [item.key, item]));
  const topBox = byKey.get("img-top")!;
  assert.ok(Math.abs(topBox.y - 0) < 1e-9);
  const bottomBox = byKey.get("img-bottom")!;
  assert.ok(bottomBox.y + bottomBox.height <= 1 + 1e-9);
});

test("纵向 span 无效或没有 tile 时返回空数组", () => {
  const tiles: TestTile[] = [tile({ index: 0 })];
  assert.deepEqual(mergeCrossTileCandidates(tiles, { top: 500, bottom: 500 }, VIEWPORT_CSS), []);
  assert.deepEqual(mergeCrossTileCandidates([], SELECTION, VIEWPORT_CSS), []);
});

test("coveredCssHeight 缺失时回退到视口高度", () => {
  const tiles: TestTile[] = [
    tile({ index: 0, scrollY: 0, coveredCssHeight: undefined, imageCandidates: [
      { key: "img-1", x: 0.2, y: 0.5, width: 0.4, height: 0.5 },
    ] }),
  ];
  const merged = mergeCrossTileCandidates(tiles, { top: 0, bottom: 430 }, VIEWPORT_CSS);
  assert.equal(merged.length, 1);
  assert.ok(Math.abs(merged[0].y - 0.5) < 1e-9);
  assert.ok(Math.abs(merged[0].height - 0.5) < 1e-9);
});

test("cssHeight 为 0 的 tile 不参与合并（避免除零）", () => {
  const tiles: TestTile[] = [
    tile({ index: 0, scrollY: 0, coveredCssHeight: 0, imageCandidates: [
      { key: "img-1", x: 0.2, y: 0.5, width: 0.4, height: 0.5 },
    ] }),
  ];
  assert.deepEqual(mergeCrossTileCandidates(tiles, SELECTION, undefined), []);
});
