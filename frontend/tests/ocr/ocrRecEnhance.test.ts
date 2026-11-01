/**
 * B-045/B-048 识别置信度增强的单测：像素统计、调理选择、替换判据与重试行筛选。
 * 运行：node --test tests/ocr/
 */

import test from "node:test";
import assert from "node:assert/strict";
import {
  applyRowEnhancementToPixels,
  computeRowCondition,
  isStrongerHypothesis,
  paddedRectForRow,
  pickRowEnhancement,
  selectUncertainRows,
} from "../../src/features/blog/utils/ocrRecEnhance.ts";
import type { OcrLine } from "../../src/features/blog/utils/screenshotOcr.ts";

/** 构造 RGBA 像素：bg 填充整行，textMarks 的下标处画 text 色块。 */
function rgbaPixels(count: number, bg: number, textMarks: Array<number>, text: number): Uint8ClampedArray {
  const pixels = new Uint8ClampedArray(count * 4);
  for (let index = 0; index < count; index += 1) {
    const value = textMarks.includes(index) ? text : bg;
    pixels[index * 4] = value;
    pixels[index * 4 + 1] = value;
    pixels[index * 4 + 2] = value;
    pixels[index * 4 + 3] = 255;
  }
  return pixels;
}

function line(overrides: Partial<OcrLine> & { confidence: number; bbox: OcrLine["bbox"] }): OcrLine {
  return { text: "示例文本", ...overrides };
}

test("computeRowCondition：亮背景/暗背景/空像素", () => {
  const light = computeRowCondition(rgbaPixels(64, 245, [10, 11, 40, 41], 30));
  assert.ok(light.meanLuma > 200, `亮背景均值应很高，实际 ${light.meanLuma}`);
  assert.ok(light.dynamicRange > 100, `亮暗对比动态范围应大，实际 ${light.dynamicRange}`);

  const dark = computeRowCondition(rgbaPixels(64, 30, [10, 11, 40, 41], 220));
  assert.ok(dark.meanLuma < 110, `暗背景均值应低于阈值，实际 ${dark.meanLuma}`);

  const empty = computeRowCondition(new Uint8ClampedArray(0));
  assert.equal(empty.meanLuma, 255);
  assert.equal(empty.dynamicRange, 255);
});

test("pickRowEnhancement：反色/拉伸/上采样/均匀色块", () => {
  // 暗背景（黑底白字）→ 反色
  assert.deepEqual(
    pickRowEnhancement({ meanLuma: 40, dynamicRange: 180, textHeight: 24 }),
    { invert: true, stretch: false, scale: 1 },
  );
  // 正常亮背景高对比 → 不调理
  assert.deepEqual(
    pickRowEnhancement({ meanLuma: 230, dynamicRange: 180, textHeight: 24 }),
    { invert: false, stretch: false, scale: 1 },
  );
  // 低对比度亮背景 → 拉伸
  assert.deepEqual(
    pickRowEnhancement({ meanLuma: 230, dynamicRange: 60, textHeight: 24 }),
    { invert: false, stretch: true, scale: 1 },
  );
  // 小字上采样：16px 以下 2 倍，10px 以下 3 倍
  assert.equal(pickRowEnhancement({ meanLuma: 230, dynamicRange: 180, textHeight: 15 }).scale, 2);
  assert.equal(pickRowEnhancement({ meanLuma: 230, dynamicRange: 180, textHeight: 9 }).scale, 3);
  // 均匀色块（无文字迹象）不做调理，省掉无意义推理
  assert.deepEqual(
    pickRowEnhancement({ meanLuma: 40, dynamicRange: 4, textHeight: 12 }),
    { invert: false, stretch: false, scale: 1 },
  );
});

test("applyRowEnhancementToPixels：反色保持 alpha，拉伸扩展到全范围", () => {
  const inverted = rgbaPixels(16, 30, [4, 5], 220);
  applyRowEnhancementToPixels(inverted, { invert: true, stretch: false });
  assert.equal(inverted[0], 225);
  assert.equal(inverted[4 * 4], 35);
  assert.equal(inverted[3], 255, "alpha 不参与反色");

  const stretched = rgbaPixels(64, 240, [8, 9, 24, 25, 40, 41], 120);
  applyRowEnhancementToPixels(stretched, { invert: false, stretch: true });
  assert.ok(stretched[8 * 4] <= 20, `暗文字应被压到接近 0，实际 ${stretched[8 * 4]}`);
  assert.ok(stretched[0] >= 240, `背景应保持在高端，实际 ${stretched[0]}`);

  const both = rgbaPixels(64, 30, [8, 9, 24, 25, 40, 41], 200);
  applyRowEnhancementToPixels(both, { invert: true, stretch: true });
  assert.ok(both[8 * 4] <= 20, `反色+拉伸后文字应接近纯黑，实际 ${both[8 * 4]}`);
  assert.ok(both[0] >= 240, `反色+拉伸后背景应接近纯白，实际 ${both[0]}`);
});

test("isStrongerHypothesis：分数增益、长度可信与替换字符守门", () => {
  const incumbent = { text: "这是一行正常长度的文本", confidence: 0.7 };
  assert.equal(isStrongerHypothesis({ text: "这是一行正常长度的文本", confidence: 0.85 }, incumbent), true);
  assert.equal(isStrongerHypothesis({ text: "这是一行正常长度的文本", confidence: 0.75 }, incumbent), false, "增益不足 0.08 不替换");
  assert.equal(isStrongerHypothesis({ text: "短文", confidence: 0.99 }, incumbent), false, "过短片段不能顶替整句");
  assert.equal(isStrongerHypothesis({ text: "含替换字�", confidence: 0.99 }, incumbent), false);
});

test("selectUncertainRows：放宽后的小字/短行可入选，排序与上限", () => {
  const rows: OcrLine[] = [
    line({ confidence: 0.95, bbox: { x: 0, y: 0, width: 200, height: 20 } }), // 高置信度排除
    line({ confidence: 0.5, bbox: { x: 0, y: 30, width: 20, height: 20 } }), // 太窄排除
    line({ confidence: 0.5, bbox: { x: 0, y: 60, width: 200, height: 8 } }), // 太矮排除
    line({ confidence: 0.4, text: "字", bbox: { x: 0, y: 90, width: 40, height: 20 } }), // 单字符排除
    line({ confidence: 0.6, text: "小字", bbox: { x: 0, y: 120, width: 30, height: 9 } }), // 旧门槛(≥12px/≥70px/≥4字)进不来，现在可以
    line({ confidence: 0.3, bbox: { x: 0, y: 150, width: 100, height: 20 } }),
  ];
  const selected = selectUncertainRows(rows, 10);
  assert.deepEqual(selected.map(({ row }) => row.confidence), [0.3, 0.6]);
  assert.equal(selectUncertainRows(rows, 1).length, 1, "按置信度升序截断");
  assert.equal(selectUncertainRows(rows, 1)[0]!.row.confidence, 0.3);
});

test("paddedRectForRow：外扩边距与画布夹紧", () => {
  const inner = paddedRectForRow({ x: 100, y: 50, width: 200, height: 20 }, 1000, 800);
  assert.deepEqual(inner, { x: 98, y: 47, width: 204, height: 26 });

  const corner = paddedRectForRow({ x: 0, y: 0, width: 10, height: 10 }, 1000, 800);
  assert.deepEqual(corner, { x: 0, y: 0, width: 12, height: 13 });

  const rightEdge = paddedRectForRow({ x: 995, y: 0, width: 10, height: 10 }, 1000, 800);
  assert.ok(rightEdge.x + rightEdge.width <= 1000, `右边界不能越界，实际 ${rightEdge.x + rightEdge.width}`);
});
