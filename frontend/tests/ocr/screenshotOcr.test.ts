/**
 * B-045 阶段A 单元测试：图片签名校验、尺寸/像素限制、块推断与 Markdown 组装。
 * 运行：node --test tests/ocr/
 */

import test from "node:test";
import assert from "node:assert/strict";
import { dedupeOverlappingBandLines, mapBandLines, OCR_BAND_HEIGHT, OCR_BAND_OVERLAP, OCR_FIRST_BAND_HEIGHT, planOcrBands } from "../../src/features/blog/utils/ocrBands.ts";

import {
  IMAGE_MAX_BYTES,
  IMAGE_MAX_PIXELS,
  assembleMarkdown,
  blockEditableText,
  blocksToMarkdown,
  detectImageSignature,
  inferBlocks,
  isProofreadWarning,
  isTextCoveredByRect,
  validateDecodedImage,
  validateImageFile,
  type OcrLine,
} from "../../src/features/blog/utils/screenshotOcr.ts";

function pngMagic(): Uint8Array {
  return new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0]);
}

function jpegMagic(): Uint8Array {
  return new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0, 0, 0, 0]);
}

function webpMagic(): Uint8Array {
  return new Uint8Array([0x52, 0x49, 0x46, 0x46, 0x11, 0x00, 0x00, 0x00, 0x57, 0x45, 0x42, 0x50]);
}

test("PNG/JPEG/WebP 签名识别", () => {
  assert.equal(detectImageSignature(pngMagic()), "png");
  assert.equal(detectImageSignature(jpegMagic()), "jpeg");
  assert.equal(detectImageSignature(webpMagic()), "webp");
});

test("SVG/HTML/伪装文件必须拒绝", () => {
  const svg = new TextEncoder().encode("<svg xmlns='http://www.w3.org/2000/svg'></svg>");
  assert.equal(detectImageSignature(svg), null);
  const html = new TextEncoder().encode("<html><body>x</body></html>");
  assert.equal(detectImageSignature(html), null);
  const verdict = validateImageFile({ name: "evil.png", size: svg.length, type: "image/svg+xml" }, svg);
  assert.equal(verdict.ok, false);
  if (!verdict.ok) assert.equal(verdict.code, "signature_rejected");
});

test("超限与空文件报错且信息可操作", () => {
  const big = new Uint8Array(IMAGE_MAX_BYTES + 1).fill(0x89);
  const tooLarge = validateImageFile({ name: "big.png", size: big.length, type: "image/png" }, big);
  assert.equal(tooLarge.ok, false);
  if (!tooLarge.ok) assert.equal(tooLarge.code, "too_large");

  const empty = validateImageFile({ name: "empty.png", size: 0, type: "image/png" }, new Uint8Array());
  assert.equal(empty.ok, false);
  if (!empty.ok) assert.equal(empty.code, "empty");
});

test("解码后像素数限制", () => {
  assert.equal(validateDecodedImage(100, 100).ok, true);
  const hugeSide = validateDecodedImage(20_001, 10);
  assert.equal(hugeSide.ok, false);
  const hugePixels = validateDecodedImage(6000, 6000);
  assert.equal(hugePixels.ok, false);
  assert.equal(6000 * 6000 > IMAGE_MAX_PIXELS, true);
});

function line(text: string, y: number, height: number, confidence = 0.98, x = 16): OcrLine {
  return { text, confidence, bbox: { x, y, width: 200 + text.length, height } };
}

test("长图 OCR 分段保留原始像素尺度，重叠区只归属一段", () => {
  const bands = planOcrBands(10_000);
  assert.ok(bands.length > 1);
  assert.ok(bands.every((band) => band.bottom - band.top <= OCR_BAND_HEIGHT));
  assert.equal(bands[0].bottom, OCR_FIRST_BAND_HEIGHT);
  assert.equal(bands[0].top, 0);
  assert.equal(bands.at(-1)?.bottom, 10_000);
  const seamY = bands[0].keepBottom - 10;
  const first = mapBandLines(bands[0], [line("接缝文字", seamY, 16)]);
  const second = mapBandLines(bands[1], [line("接缝文字", seamY - bands[1].top, 16)]);
  assert.equal(first.length + second.length, 1);
  assert.equal((first[0] ?? second[0])?.bbox.y, seamY);
});

test("OCR bands keep continuous full-image coverage with a wider first seam overlap", () => {
  const height = 13_119;
  const bands = planOcrBands(height);
  assert.equal(bands[0]?.top, 0);
  assert.equal(bands[0]?.bottom, OCR_FIRST_BAND_HEIGHT);
  assert.equal(bands.at(-1)?.bottom, height);
  for (let i = 1; i < bands.length; i += 1) {
    const previous = bands[i - 1]!;
    const current = bands[i]!;
    assert.equal(previous.bottom - current.top, OCR_BAND_OVERLAP);
    assert.equal(previous.keepBottom, current.keepTop);
    assert.ok(current.keepTop < current.top + OCR_BAND_OVERLAP);
  }
  const seam = bands[0]!.keepBottom - 2;
  const a = mapBandLines(bands[0]!, [line("边缘薄片段", seam, 10)]);
  const b = mapBandLines(bands[1]!, [line("边缘薄片段", seam - bands[1]!.top, 10)]);
  assert.equal(a.length + b.length, 1);
});

test("重叠中线不会丢失只在非归属段识别到的文字，并按文本与坐标去重", () => {
  const bands = planOcrBands(4_000);
  const later = bands[1]!;
  const centerAboveOwnership = later.keepTop - 1;
  const onlyInLater = line("边界漏检恢复", centerAboveOwnership - later.top - 6, 12, 0.92);
  assert.equal(mapBandLines(later, [onlyInLater]).length, 0);
  const preserved = mapBandLines(later, [onlyInLater], true);
  assert.equal(preserved.length, 1);
  assert.equal(preserved[0]?.bbox.y, centerAboveOwnership - 6);

  const sameA = { ...line("同一行", 820, 14, 0.78), bbox: { x: 40, y: 820, width: 120, height: 14 } };
  const sameB = { ...line("同一行", 821, 14, 0.95), bbox: { x: 41, y: 821, width: 120, height: 14 } };
  const repeatedElsewhere = { ...sameB, bbox: { ...sameB.bbox, y: 1_420 } };
  const merged = dedupeOverlappingBandLines([sameA, sameB, repeatedElsewhere, ...preserved]);
  assert.equal(merged.length, 3);
  assert.equal(merged.find((item) => item.bbox.y === 821)?.confidence, 0.95);
  assert.ok(merged.some((item) => item.text === "边界漏检恢复"));
});

test("同一物理文字框的明显低置信度变体保留为校对备选，近邻框不合并", () => {
  const base = { x: 120, y: 2400, width: 510, height: 24 };
  const weak = { text: "RPC 协议头部存在字符错读", confidence: 0.42, bbox: { ...base } };
  const strong = { text: "RPC 协议头部存在字符误读", confidence: 0.91, bbox: { x: 121, y: 2401, width: 510, height: 24 } };
  const nearby = { text: "下一行独立文字", confidence: 0.88, bbox: { x: 120, y: 2427, width: 210, height: 24 } };
  const merged = dedupeOverlappingBandLines([weak, strong, nearby]);
  assert.equal(merged.length, 2);
  assert.equal(merged[0]?.text, strong.text);
  assert.deepEqual(merged[0]?.alternatives, [{ text: weak.text, confidence: weak.confidence }]);
  assert.equal(merged[1]?.text, nearby.text);
  const block = inferBlocks(merged)[0]!;
  // 主读法 0.91 高置信度：备选仅留档，不再挂“请对照原图”警告，避免文字明明正确仍常驻警示
  assert.equal(block.warnings.some((warning) => warning.includes(weak.text)), false);
});

test("主读法置信度不足时，备选才提示对照原图", () => {
  const blocks = inferBlocks([
    {
      text: "RPC 协议头部存在字符误读", confidence: 0.85,
      bbox: { x: 120, y: 2400, width: 510, height: 24 },
      alternatives: [{ text: "RPC 协议头部存在字符错读", confidence: 0.42 }],
    },
  ]);
  assert.ok(blocks[0]!.warnings.some((warning) => warning.includes("字符错读")));
});

test("isProofreadWarning 匹配校对类提示，放过图片权限等状态提示", () => {
  assert.equal(isProofreadWarning("含低置信度文字，请对照原图校对"), true);
  assert.equal(isProofreadWarning("同一文字框的 OCR 备选（置信度 0.42）：“错读”；请对照原图"), true);
  assert.equal(isProofreadWarning("标题置信度较低，请核对层级与文字"), true);
  assert.equal(isProofreadWarning("代码块候选：OCR 易混淆缩进与符号，请核对后补充语言"), true);
  assert.equal(isProofreadWarning("疑似表格或多栏文字：当前按检测框顺序保留为多行，请对照原图校对单元格关系"), true);
  assert.equal(isProofreadWarning("私有图片引用：保存笔记后本人可读"), false);
  assert.equal(isProofreadWarning("博客图片引用：提交公开前请核对图片使用权"), false);
});

test("只保留图片的覆盖判定：零几何块（插图/手动）永不算覆盖，OCR 块按 50% 阈值", () => {
  const rect = { x: 100, y: 200, width: 300, height: 150 };
  // 插图引用块与手动添加块的 bbox 为 0：绝不能判为“被插图覆盖的文字”，
  // 否则 0 < 0 为 false，第二次插图会把之前的引用块全部清掉，只剩最后一张
  assert.equal(isTextCoveredByRect({ id: "blk-figure-1", bbox: { x: 0, y: 0, width: 0, height: 0 } }, rect), false);
  assert.equal(isTextCoveredByRect({ id: "blk-manual-1", bbox: { x: 0, y: 0, width: 0, height: 0 } }, rect), false);
  // 完全在插图内的 OCR 文字块 → 覆盖
  assert.equal(isTextCoveredByRect({ id: "blk-0-220", bbox: { x: 150, y: 240, width: 120, height: 24 } }, rect), true);
  // 约 25% 重叠（低于 50% 阈值）→ 保留
  assert.equal(isTextCoveredByRect({ id: "blk-0-320", bbox: { x: 350, y: 320, width: 200, height: 30 } }, rect), false);
  // 完全不相交 → 保留
  assert.equal(isTextCoveredByRect({ id: "blk-0-500", bbox: { x: 500, y: 500, width: 100, height: 20 } }, rect), false);
});

test("置信度相近的重叠读法都保留，不能凭分数删除疑难文字", () => {
  const a = { text: "协议内容 A", confidence: 0.71, bbox: { x: 30, y: 2500, width: 350, height: 22 } };
  const b = { text: "协议内容 B", confidence: 0.63, bbox: { x: 31, y: 2500, width: 350, height: 22 } };
  assert.equal(dedupeOverlappingBandLines([a, b]).length, 2);
});

test("短图只识别一段，非法分段尺寸拒绝", () => {
  assert.deepEqual(planOcrBands(900), [{ top: 0, bottom: 900, keepTop: 0, keepBottom: 900 }]);
  assert.throws(() => planOcrBands(0));
  assert.throws(() => planOcrBands(2000, 100, 100));
});

test("正文段落聚合为段落块", () => {
  const blocks = inferBlocks([
    line("当网页正文确实显示在屏幕上，而常规的文档对象模型抽取失败时，", 100, 14),
    line("用户可以主动截取需要的区域，在博客内对照原图校正识别结果。", 124, 14),
    line("第二段落开始了，这里与上面有明显的段间距。", 190, 14),
  ]);
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].kind, "paragraph");
  assert.equal(blocks[1].kind, "paragraph");
});

test("大字号短行推断为标题", () => {
  const blocks = inferBlocks([
    line("长截图OCR转Markdown的设计", 20, 24),
    line("正文第一行，字号比标题小很多。", 70, 14),
  ]);
  assert.equal(blocks[0].kind, "heading");
  assert.equal(blocks[0].level, 2);
});

test("编号行推断为列表", () => {
  const blocks = inferBlocks([
    line("1. 安装依赖", 20, 16),
    line("2. 配置模型路径", 46, 16),
    line("3. 校验哈希", 72, 16),
  ]);
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].kind, "list");
});

test("连续 ASCII 符号行推断为代码并标记需校对", () => {
  const blocks = inferBlocks([
    { ...line("def dedupe_lines(tiles):", 20, 15), bbox: { x: 20, y: 20, width: 220, height: 15 } },
    { ...line("seen = set()", 45, 15), bbox: { x: 55, y: 45, width: 120, height: 15 } },
    { ...line("return result", 70, 15), bbox: { x: 55, y: 70, width: 135, height: 15 } },
  ]);
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].kind, "code");
  assert.ok(blocks[0].warnings.some((w) => w.includes("代码块候选")));
  assert.match(blockEditableText(blocks[0]), /\n {3,}seen/);
});

test("同一行错开的文字框提示表格/多栏关系需核对", () => {
  const blocks = inferBlocks([
    { ...line("名称", 20, 15), bbox: { x: 20, y: 20, width: 45, height: 15 } },
    { ...line("状态", 20, 15), bbox: { x: 240, y: 20, width: 45, height: 15 } },
  ]);
  assert.ok(blocks[0]?.warnings.some((warning) => warning.includes("表格或多栏")));
  assert.deepEqual(blocks[0]?.lines.map((item) => item.text), ["名称", "状态"]);
});

test("低置信度行会出现在块警告里", () => {
  const blocks = inferBlocks([line("识别不太确定的文字", 10, 14, 0.55)]);
  assert.ok(blocks[0].warnings.some((w) => w.includes("低置信度")));
});

test("Markdown 组装：标题/列表/代码/段落", () => {
  const md = assembleMarkdown([
    { kind: "heading", level: 2, text: "设计标题" },
    { kind: "paragraph", text: "正文段落。" },
    { kind: "list", text: "1. 安装依赖\n2. 校验哈希" },
    { kind: "code", text: "def f():\n    return 1" },
  ]);
  assert.ok(md.includes("## 设计标题"));
  assert.ok(md.includes("正文段落。"));
  assert.ok(md.includes("1. 安装依赖"));
  assert.ok(md.includes("```"));
  assert.ok(md.includes("    return 1"));
});

test("Markdown 组装不会伪造表格或语言标签", () => {
  const md = assembleMarkdown([{ kind: "code", text: "SELECT 1" }]);
  assert.equal(md, "```\nSELECT 1\n```\n");
  assert.ok(!md.includes("```sql"));
  assert.ok(!md.includes("```python"));
});

test("blocksToMarkdown 与可编辑文本一致", () => {
  const blocks = inferBlocks([
    line("标题行", 10, 24),
    line("def f():", 60, 14),
    line("    pass", 84, 14),
  ]);
  assert.equal(blocksToMarkdown(blocks), assembleMarkdown(blocks.map((b) => ({ kind: b.kind, level: b.level, text: blockEditableText(b) }))));
});

test("OCR 文本中的控制字符被剥离", () => {
  const blocks = inferBlocks([line("正常文字\u0000\u0007后面", 10, 14)]);
  assert.equal(blocks[0].lines[0].text.includes("\u0000"), false);
  assert.equal(blocks[0].lines[0].text.includes("\u0007"), false);
});

import { dedupeBlocksAcrossTiles } from "../../src/features/blog/utils/screenshotOcr.ts";

test("跨屏去重：固定导航的重复块被删掉，正文保留", () => {
  const headerA = inferBlocks([line("网站导航 · 首页 · 登录", 10, 14)]);
  const bodyA = inferBlocks([line("第一屏的正文内容，讲述设计背景。", 60, 14)]);
  const headerB = inferBlocks([line("网站导航 · 首页 · 登录", 10, 14)]);
  const bodyB = inferBlocks([line("第二屏的正文内容，接着上面的段落。", 60, 14)]);
  const { blocks, dropped } = dedupeBlocksAcrossTiles([[...headerA, ...bodyA], [...headerB, ...bodyB]]);
  assert.equal(dropped, 1);
  assert.equal(blocks.length, 3);
  const texts = blocks.map((block) => block.lines.map((l) => l.text).join(""));
  assert.equal(texts.filter((text) => text.includes("网站导航")).length, 1);
  assert.ok(texts.some((text) => text.includes("第二屏的正文")));
});

test("跨屏去重：部分被切断的行不会误删", () => {
  const a = inferBlocks([line("这是跨屏被切断的半行文字", 100, 14)]);
  const b = inferBlocks([line("这是跨屏被切断的半行", 10, 14)]);
  const { blocks, dropped } = dedupeBlocksAcrossTiles([a, b]);
  assert.equal(dropped, 0);
  assert.equal(blocks.length, 2);
});

test("跨屏去重：多行块需逐行匹配才去重", () => {
  const navA = inferBlocks([line("菜单 A", 10, 14), line("菜单 B", 40, 14)]);
  const navB = inferBlocks([line("菜单 A", 10, 14), line("菜单 C", 40, 14)]);
  const { dropped } = dedupeBlocksAcrossTiles([navA, navB]);
  assert.equal(dropped, 0);
});
