/**
 * 长截图本地保存的拼接几何单测：DPR 换算、选区裁剪、画布上限缩放、tile 排布。
 * 运行：node --test tests/
 */

import test from "node:test";
import assert from "node:assert/strict";
import { computeStitchPlan, stitchShotTiles } from "../shared/longshot-stitch.js";

function record(overrides = {}) {
  return {
    dpr: 2,
    viewport: { width: 1000, height: 500 },
    covered: { top: 100, bottom: 1300 },
    selection: { left: 0.1, right: 0.6, top: 100, bottom: 1300 },
    coveredTop: 100,
    coveredBottom: 1300,
    tiles: [
      { index: 0, scrollY: 100, width: 2000, height: 1000, mime: "image/jpeg" },
      { index: 1, scrollY: 600, width: 2000, height: 1000, mime: "image/jpeg" },
      { index: 2, scrollY: 1100, width: 2000, height: 1000, mime: "image/jpeg" },
    ],
    ...overrides,
  };
}

test("computeStitchPlan：按 DPR 与选区计算画布，tile 只画框内", () => {
  const plan = computeStitchPlan(record());
  // 选区宽 (0.6-0.1)*1000=500 CSS → 1000 设备像素；高 (1300-100)=1200 CSS → 2400
  assert.equal(plan.width, 1000);
  assert.equal(plan.height, 2400);
  assert.equal(plan.placements.length, 3);
  // 首屏 tile.scrollY=top → dy=0
  assert.equal(plan.placements[0].dy, 0);
  // 第二屏 scrollY=600 → (600-100)*2=1000
  assert.equal(plan.placements[1].dy, 1000);
  // 水平裁剪：sx=0.1*1000*2=200，sw=0.5*1000*2=1000
  assert.equal(plan.placements[0].sx, 200);
  assert.equal(plan.placements[0].sw, 1000);
  assert.equal(plan.placements[0].dw, plan.width);
});

test("computeStitchPlan：范围外 tile 被跳过，底边被 coveredBottom 收口", () => {
  const plan = computeStitchPlan(record({
    selection: { left: 0, right: 1, top: 100, bottom: 1300 },
    coveredBottom: 1150, // 实际只截到 1150
  }));
  // 高度 (1150-100)*2=2100
  assert.equal(plan.height, 2100);
  // 第三屏 scrollY=1100，顶边仍在范围内（1100 < 1150），保留
  assert.equal(plan.placements.length, 3);
  const plan2 = computeStitchPlan(record({
    selection: { left: 0, right: 1, top: 100, bottom: 1300 },
    coveredBottom: 1090, // 只截到 1090：第三屏(1100)完全在范围外
  }));
  assert.equal(plan2.height, (1090 - 100) * 2);
  assert.equal(plan2.placements.length, 2);
});

test("computeStitchPlan：超大截图按上限缩放", () => {
  // 5000 CSS 宽 × DPR2 = 10000px 宽；30000 CSS 高 × DPR2 = 60000px 高 → 超上限
  const plan = computeStitchPlan({
    dpr: 2,
    viewportWidth: 5000,
    viewportHeight: 2000,
    selection: { left: 0, right: 1, top: 0, bottom: 30000 },
    coveredTop: 0,
    coveredBottom: 30000,
    tiles: [{ index: 0, scrollY: 0, width: 10000, height: 4000, mime: "image/jpeg" }],
  });
  // 等比缩放，且不超过边长/像素上限（像素上限 30MP 先于 20000 边长绑定）
  assert.ok(plan.height <= 20000);
  assert.ok(plan.width <= 20000);
  assert.ok(plan.width * plan.height <= 30_000_000);
  assert.ok(Math.abs(plan.width / plan.height - 10000 / 60000) < 1e-6);
});

test("computeStitchPlan：无选区时用完整覆盖范围", () => {
  const plan = computeStitchPlan(record({ selection: null }));
  assert.equal(plan.width, 2000);
  assert.equal(plan.height, 2400);
  assert.equal(plan.placements[0].sx, 0);
});

test("computeStitchPlan：无效输入给出可读错误", () => {
  assert.throws(() => computeStitchPlan(null), /截图会话不完整/);
  assert.throws(() => computeStitchPlan(record({ tiles: [] })), /缺少视口信息或截图分片/);
  assert.throws(() => computeStitchPlan(record({ coveredBottom: 100, selection: { left: 0, right: 1, top: 100, bottom: 1300 } })), /没有截取到有效内容/);
});

test("stitchShotTiles：按计划绘制并输出 Blob", async () => {
  const plan = computeStitchPlan(record());
  const drawn = [];
  const fakeCtx = { fillStyle: "", fillRect() {} };
  const adapter = {
    createCanvas: (w, h) => ({ width: w, height: h, getContext: () => fakeCtx }),
    loadTile: async (index) => new Uint8Array([index]),
    decode: async (bytes) => ({ id: bytes[0] }),
    drawImage: (ctx, image, placement) => drawn.push({ image: image.id, ...placement }),
    toBlob: async (canvas, mime) => ({ size: canvas.width * canvas.height, mime }),
  };
  const blob = await stitchShotTiles(plan, adapter);
  assert.equal(blob.mime, "image/png");
  assert.equal(drawn.length, 3);
  assert.deepEqual(drawn.map((item) => item.image), [0, 1, 2]);
  assert.equal(drawn[0].dy, 0);
  assert.equal(drawn[1].dy, 1000);
});

test("stitchShotTiles：分片丢失时报错且不产出 Blob", async () => {
  const plan = computeStitchPlan(record());
  await assert.rejects(
    stitchShotTiles(plan, {
      createCanvas: (w, h) => ({ width: w, height: h, getContext: () => ({ fillStyle: "", fillRect() {} }) }),
      loadTile: async (index) => (index === 1 ? null : new Uint8Array([1])),
      decode: async () => ({}),
      drawImage: () => {},
      toBlob: async () => ({}),
    }),
    /截图分片已丢失/,
  );
});
