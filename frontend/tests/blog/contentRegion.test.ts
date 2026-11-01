/**
 * contentRegion 主内容区域检测的单元测试：合成 RGBA 像素矩阵驱动纯函数
 * detectContentRegion / estimateBackgroundColor，不依赖 DOM。
 * 运行：cd frontend && npm run test:unit
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  detectContentRegion,
  estimateBackgroundColor,
  type NormalizedRect,
} from "../../src/features/blog/utils/contentRegion.ts";

/** 生成 width×height 的 RGBA 像素，fill 返回每个像素的 RGB。 */
function rgba(
  width: number,
  height: number,
  fill: (x: number, y: number) => [number, number, number],
): Uint8ClampedArray {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const [r, g, b] = fill(x, y);
      const offset = (y * width + x) * 4;
      data[offset] = r;
      data[offset + 1] = g;
      data[offset + 2] = b;
      data[offset + 3] = 255;
    }
  }
  return data;
}

test("estimateBackgroundColor：白底四角众数即白色", () => {
  const data = rgba(64, 64, (x, y) => (x >= 20 && x < 44 && y >= 20 && y < 44 ? [10, 200, 30] : [255, 255, 255]));
  assert.deepEqual(estimateBackgroundColor(data, 64, 64), [255, 255, 255]);
});

test("estimateBackgroundColor：纯色图返回该颜色", () => {
  const data = rgba(32, 32, () => [24, 48, 96]);
  assert.deepEqual(estimateBackgroundColor(data, 32, 32), [24, 48, 96]);
});

test("居中的主内容区域被定位，输出归一化并含少量边距", () => {
  // 200×200 白底；内容块在 x[40,160) y[50,150)（深色）。
  const data = rgba(200, 200, (x, y) =>
    x >= 40 && x < 160 && y >= 50 && y < 150 ? [20, 20, 20] : [255, 255, 255]);
  const region = detectContentRegion(data, 200, 200);
  assert.ok(region, "应能定位主内容区域");
  // 内容归一化范围：x 0.2–0.8，y 0.25–0.75；留 3% 边距后允许少量外扩。
  const assertNear = (value: number, expected: number, tolerance = 0.02) =>
    assert.ok(Math.abs(value - expected) <= tolerance, `期望 ${expected}±${tolerance}，实际 ${value}`);
  assertNear(region.x0, 0.2 - 0.03, 0.03);
  assertNear(region.x1, 0.8 + 0.03, 0.03);
  assertNear(region.y0, 0.25 - 0.03, 0.03);
  assertNear(region.y1, 0.75 + 0.03, 0.03);
  // 预填框必须完整覆盖内容块本体。
  assert.ok(region.x0 <= 0.2 && region.x1 >= 0.8 && region.y0 <= 0.25 && region.y1 >= 0.75);
});

test("带页眉页脚的网页式布局：主区域排除页眉/页脚", () => {
  // 400×300 白底：页眉 y[0,30)，正文 y[60,240)，页脚 y[270,300)。
  const data = rgba(400, 300, (x, y) => {
    if (y < 30 || y >= 270) return [240, 240, 240]; // 浅灰条
    if (y >= 60 && y < 240 && x >= 40 && x < 360) return [30, 30, 30];
    return [255, 255, 255];
  });
  const region: NormalizedRect | null = detectContentRegion(data, 400, 300);
  assert.ok(region, "应能定位正文主区域");
  assert.ok(region.y0 >= 30 / 300 - 0.05, "上边界不应吃进页眉");
  assert.ok(region.y1 <= 270 / 300 + 0.05, "下边界不应吃进页脚");
  assert.ok(region.y0 <= 60 / 300 && region.y1 >= 240 / 300, "正文必须被完整覆盖");
});

test("整图都是内容时返回接近全图的区域", () => {
  const data = rgba(100, 100, (x, y) => [x * 2, y * 2, 128]);
  const region = detectContentRegion(data, 100, 100);
  assert.ok(region);
  assert.ok(region.x0 <= 0.02 && region.y0 <= 0.02 && region.x1 >= 0.98 && region.y1 >= 0.98);
});

test("纯色图无法定位内容，返回 null", () => {
  const data = rgba(64, 64, () => [200, 200, 200]);
  assert.equal(detectContentRegion(data, 64, 64), null);
});

test("内容过小（低于 20% 维度）视为不可靠，返回 null", () => {
  const data = rgba(200, 200, (x, y) => (x >= 95 && x < 105 && y >= 95 && y < 105 ? [0, 0, 0] : [255, 255, 255]));
  assert.equal(detectContentRegion(data, 200, 200), null);
});

test("非法输入安全返回 null", () => {
  assert.equal(detectContentRegion(new Uint8ClampedArray(16), 4, 4), null);
  assert.equal(detectContentRegion(new Uint8ClampedArray(8 * 8 * 4 - 1), 8, 8), null); // 长度不足
  assert.equal(detectContentRegion(null as unknown as Uint8ClampedArray, 64, 64), null);
  assert.equal(detectContentRegion(new Uint8ClampedArray(64 * 64 * 4), Number.NaN, 64), null);
});

test("透明像素按背景处理", () => {
  // 内容块 alpha=0：无有效内容 → null。
  const data = new Uint8ClampedArray(100 * 100 * 4);
  for (let y = 20; y < 80; y += 1) {
    for (let x = 20; x < 80; x += 1) {
      const offset = (y * 100 + x) * 4;
      data[offset] = 0; data[offset + 1] = 0; data[offset + 2] = 0; data[offset + 3] = 0;
    }
  }
  assert.equal(detectContentRegion(data, 100, 100), null);
});
