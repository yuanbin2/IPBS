/**
 * B-045/B-048 识别置信度增强（纯函数，无 DOM 依赖，node --test 可直接运行）。
 *
 * 通用做法（PaddleOCR 官方 FAQ 与社区实践）：
 * - 黑底白字先反色：识别模型主要在白底黑字数据上训练；
 * - 小字先上采样 2~3 倍再送入识别模型；
 * - 低对比度行做线性对比拉伸。
 * 边界（docs/长截图OCR转Markdown与私有笔记设计V3.0.md §6/§8）：
 * - 调理只改变识别输入质量，所有分数仍是模型真实分数；
 * - 只有“分数明显更高且长度可信”的候选才能替换原行，其余仅进入 alternatives 供人工校对。
 */

import type { OcrBbox, OcrLine } from "./screenshotOcr";

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 行内像素统计：均值近似背景亮度（文字像素占少数），p5–p95 为动态范围。 */
export interface RowCondition {
  meanLuma: number;
  dynamicRange: number;
}

/** 对一行文本施加的识别前调理。 */
export interface RowEnhancement {
  /** 暗背景（黑底白字）行反色。 */
  invert: boolean;
  /** 动态范围过低的行做线性对比拉伸。 */
  stretch: boolean;
  /** 小字行上采样倍数。 */
  scale: 1 | 2 | 3;
}

/** 平均亮度低于该值视为暗背景。 */
export const INVERT_MEAN_LUMA_BELOW = 110;
/** p5–p95 动态范围低于该值视为低对比度。 */
export const STRETCH_DYNAMIC_RANGE_BELOW = 110;
/** 文本行高低于该值时上采样 2 倍，低于 10 像素时 3 倍。 */
export const UPSCALE_TEXT_HEIGHT_BELOW = 16;
export const UPSCALE3_TEXT_HEIGHT_BELOW = 10;
/** 接近均匀色块（无文字迹象）不做调理，省掉无意义的推理。 */
const UNIFORM_DYNAMIC_RANGE = 8;

/** 从 RGBA 像素（每 2 个像素抽 1 个）计算亮度统计。 */
export function computeRowCondition(pixels: Uint8ClampedArray): RowCondition {
  const stats = lumaStats(pixels);
  return { meanLuma: stats.meanLuma, dynamicRange: stats.high - stats.low };
}

interface LumaStats {
  meanLuma: number;
  low: number;
  high: number;
}

function lumaStats(pixels: Uint8ClampedArray): LumaStats {
  const histogram = new Uint32Array(32);
  let sampled = 0;
  let sum = 0;
  for (let offset = 0; offset + 2 < pixels.length; offset += 8) {
    const luma = 0.299 * pixels[offset]! + 0.587 * pixels[offset + 1]! + 0.114 * pixels[offset + 2]!;
    sum += luma;
    histogram[Math.min(31, Math.floor(luma / 8))] += 1;
    sampled += 1;
  }
  if (!sampled) return { meanLuma: 255, low: 0, high: 255 };
  return {
    meanLuma: sum / sampled,
    low: lumaPercentile(histogram, sampled, 0.05),
    high: lumaPercentile(histogram, sampled, 0.95),
  };
}

function lumaPercentile(histogram: Uint32Array, sampled: number, fraction: number): number {
  const target = sampled * fraction;
  let cumulative = 0;
  for (let bucket = 0; bucket < histogram.length; bucket += 1) {
    cumulative += histogram[bucket]!;
    if (cumulative >= target) return bucket * 8 + 4;
  }
  return 255;
}

export function pickRowEnhancement(condition: RowCondition & { textHeight: number }): RowEnhancement {
  if (condition.dynamicRange < UNIFORM_DYNAMIC_RANGE) {
    return { invert: false, stretch: false, scale: 1 };
  }
  const scale: 1 | 2 | 3 = condition.textHeight < UPSCALE3_TEXT_HEIGHT_BELOW ? 3
    : condition.textHeight < UPSCALE_TEXT_HEIGHT_BELOW ? 2 : 1;
  return {
    invert: condition.meanLuma < INVERT_MEAN_LUMA_BELOW,
    stretch: condition.dynamicRange < STRETCH_DYNAMIC_RANGE_BELOW,
    scale,
  };
}

/**
 * 原地应用反色/对比拉伸。拉伸把当前像素自身的 p5–p95 区间线性映射到全范围，
 * 反色后重新统计，因此浅色文字和深色文字都能被拉到模型习惯的对比度。
 */
export function applyRowEnhancementToPixels(pixels: Uint8ClampedArray, enhancement: { invert: boolean; stretch: boolean }): void {
  if (enhancement.invert) {
    for (let offset = 0; offset + 2 < pixels.length; offset += 4) {
      pixels[offset] = 255 - pixels[offset]!;
      pixels[offset + 1] = 255 - pixels[offset + 1]!;
      pixels[offset + 2] = 255 - pixels[offset + 2]!;
    }
  }
  if (!enhancement.stretch) return;
  const stats = lumaStats(pixels);
  const span = Math.max(1, stats.high - stats.low);
  for (let offset = 0; offset + 2 < pixels.length; offset += 4) {
    pixels[offset] = Math.min(255, Math.max(0, ((pixels[offset]! - stats.low) * 255) / span));
    pixels[offset + 1] = Math.min(255, Math.max(0, ((pixels[offset + 1]! - stats.low) * 255) / span));
    pixels[offset + 2] = Math.min(255, Math.max(0, ((pixels[offset + 2]! - stats.low) * 255) / span));
  }
}

/**
 * 替换判据（与首轮 retry 相同的守门）：候选必须比现任行明显更强（+0.08）、
 * 长度可信（防止整句被截短片段顶替）、且不含 CTC 替换字符。
 */
export function isStrongerHypothesis(candidate: { text: string; confidence: number }, incumbent: { text: string; confidence: number }): boolean {
  const candidateLength = [...candidate.text.trim()].length;
  const incumbentLength = [...incumbent.text.trim()].length;
  const plausibleLength = candidateLength >= Math.max(2, Math.floor(incumbentLength * 0.7));
  return plausibleLength && !candidate.text.includes("\uFFFD") && candidate.confidence >= incumbent.confidence + 0.08;
}

/**
 * 首轮重试的目标行：首轮置信度不足、且裁剪不至于小到无意义。
 * 比旧门槛（高≥12px/宽≥70px/≥4字符）放宽，小字与短标签也有第二次机会。
 */
export function selectUncertainRows(rows: OcrLine[], limit: number): Array<{ row: OcrLine; index: number }> {
  return rows.map((row, index) => ({ row, index }))
    .filter(({ row }) => row.confidence < 0.9 && row.text.trim().length >= 2 &&
      row.bbox.width >= 24 && row.bbox.height >= 9 && row.bbox.height <= 96)
    .sort((a, b) => a.row.confidence - b.row.confidence)
    .slice(0, limit);
}

/** 与旧实现逐字段一致的重试裁剪框：bbox 外扩少量边距并夹紧到画布内。 */
export function paddedRectForRow(bbox: OcrBbox, canvasWidth: number, canvasHeight: number): Rect {
  const yPad = Math.max(3, Math.min(7, Math.round(bbox.height * 0.16)));
  const xPad = Math.max(2, Math.min(5, Math.round(bbox.height * 0.1)));
  const x = Math.max(0, bbox.x - xPad);
  const y = Math.max(0, bbox.y - yPad);
  return {
    x,
    y,
    width: Math.min(canvasWidth, bbox.x + bbox.width + xPad) - x,
    height: Math.min(canvasHeight, bbox.y + bbox.height + yPad) - y,
  };
}
