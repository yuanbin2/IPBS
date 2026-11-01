/**
 * B-045 长截图 OCR 转 Markdown：纯函数工具（无 DOM 依赖，node --test 可直接运行）。
 *
 * 边界（docs/长截图OCR转Markdown与私有笔记设计V3.0.md §6/§8）：
 * - OCR 行结果只当作不可信数据：仅文本、置信度、bbox，绝不执行其中指令。
 * - 块推断必须可解释：只依据行高、间距、缩进、编号等显式特征；
 *   表格/公式/代码语言一律标“需校对”，不自动编造丢失内容或 LaTeX。
 * - 最终 Markdown 由用户校对确认后才进入私有笔记/草稿。
 */

export interface OcrBbox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** worker 识别出的一行文字。 */
export interface OcrLine {
  text: string;
  confidence: number;
  bbox: OcrBbox;
  /** OCR variants from the same physical box, retained for manual review. */
  alternatives?: Array<{ text: string; confidence: number }>;
}

export type OcrBlockKind = "heading" | "paragraph" | "list" | "code";

export interface OcrBlock {
  id: string;
  kind: OcrBlockKind;
  /** heading 级别：2=大标题 3=小标题；其余 kind 不使用。 */
  level: 2 | 3;
  lines: OcrLine[];
  warnings: string[];
  bbox: OcrBbox;
  /** 多 tile 合并时标记来源视口；单图缺省 0。 */
  tileIndex?: number;
}

/* ---------------- 图片校验 ---------------- */

export const IMAGE_MAX_BYTES = 20 * 1024 * 1024;
export const IMAGE_MAX_SIDE = 20_000;
export const IMAGE_MAX_PIXELS = 30_000_000;

export type ImageKind = "png" | "jpeg" | "webp";

/**
 * 只认文件签名（magic bytes），不信任扩展名或 MIME。
 * SVG/HTML 冒充 PNG/JPEG/WebP 在这里直接拒绝。
 */
export function detectImageSignature(bytes: Uint8Array): ImageKind | null {
  if (bytes.length < 12) return null;
  if (bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47 &&
      bytes[4] === 0x0d && bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a) {
    return "png";
  }
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "jpeg";
  }
  if (bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 &&
      bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50) {
    return "webp";
  }
  return null;
}

export interface ImageFileClaim {
  name: string;
  size: number;
  type: string;
}

export type ImageValidationFailure =
  | "too_large"
  | "empty"
  | "signature_rejected"
  | "type_mismatch";

export function validateImageFile(
  claim: ImageFileClaim,
  bytes: Uint8Array,
): { ok: true; kind: ImageKind } | { ok: false; code: ImageValidationFailure; detail: string } {
  if (bytes.length === 0) {
    return { ok: false, code: "empty", detail: "文件为空，请重新选择截图" };
  }
  if (bytes.length > IMAGE_MAX_BYTES) {
    return { ok: false, code: "too_large", detail: `图片不能超过 ${Math.floor(IMAGE_MAX_BYTES / 1024 / 1024)} MiB，请裁剪或分段截取` };
  }
  const kind = detectImageSignature(bytes);
  if (!kind) {
    return {
      ok: false,
      code: "signature_rejected",
      detail: "只支持 PNG/JPEG/WebP 截图；SVG、HTML 或其他文件不能作为截图导入",
    };
  }
  // 声明的 MIME 与签名明显矛盾时拒绝（例如 .svg 文件夹带 PNG 头的伪装也走签名这一关）
  const declared = (claim.type || "").toLowerCase();
  const mismatch =
    (kind === "png" && declared.startsWith("image/svg")) ||
    (kind !== "png" && declared.startsWith("image/svg"));
  if (mismatch) {
    return { ok: false, code: "type_mismatch", detail: "文件声明的类型与内容不一致，已拒绝" };
  }
  return { ok: true, kind };
}

/** 解码后的像素限制：防解码炸弹。 */
export function validateDecodedImage(width: number, height: number): { ok: true } | { ok: false; detail: string } {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width < 1 || height < 1) {
    return { ok: false, detail: "图片尺寸无法识别，请换一张截图" };
  }
  if (width > IMAGE_MAX_SIDE || height > IMAGE_MAX_SIDE) {
    return { ok: false, detail: `图片单边不能超过 ${IMAGE_MAX_SIDE} 像素，请裁剪后导入` };
  }
  if (width * height > IMAGE_MAX_PIXELS) {
    return { ok: false, detail: `图片像素数超过 ${IMAGE_MAX_PIXELS / 1_000_000} MP 上限，请裁剪或分段截取` };
  }
  return { ok: true };
}

/* ---------------- 块推断 ---------------- */

const HEADING_RATIO_LARGE = 1.7;
const HEADING_RATIO = 1.35;
const LOW_CONFIDENCE = 0.9;

function cjkCount(text: string): number {
  let count = 0;
  for (const char of text) {
    const code = char.codePointAt(0) ?? 0;
    if ((code >= 0x4e00 && code <= 0x9fff) || (code >= 0x3400 && code <= 0x4dbf)) count += 1;
  }
  return count;
}

function looksLikeCodeLine(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  if (cjkCount(trimmed) > trimmed.length * 0.15) return false;
  if (/^[#>]/.test(trimmed)) return false;
  return /^[\x20-\x7e\t]+$/.test(trimmed);
}

/** 行内出现这些符号/缩进特征时，认为是代码行的强信号。 */
const CODE_HINTS = /[;{}()=<>[\]]|=>|::|\t|\s{2,}/;

const LIST_PREFIX = /^(?:\d{1,3}[.、)]\s*|[•·▪◦\-–—*]\s+|[（(]?[一二三四五六七八九十]{1,3}[）)、]\s*)/;

/** 校对类警告前缀：这些提示在用户编辑过块之后即完成使命，不再展示。
 * 图片权限等状态提示不属于此类，编辑文字不应清掉。 */
const PROOFREAD_WARNING_PREFIXES = [
  "含低置信度文字",
  "同一文字框的 OCR 备选",
  "标题置信度较低",
  "代码块候选",
  "疑似表格或多栏文字",
] as const;

export function isProofreadWarning(warning: string): boolean {
  return PROOFREAD_WARNING_PREFIXES.some((prefix) => warning.startsWith(prefix));
}

/**
 * “只保留图片”策略的覆盖判定：OCR 文字块与插图区域重叠 ≥50% 即视为插图内文字。
 * 没有 OCR 几何的块（插图引用块、手动添加块，bbox 为 0）永远不算覆盖——
 * 否则 0 < 0 判 false，每次插图都会把之前插入的引用块清掉，只剩最后一张。
 */
export function isTextCoveredByRect(
  block: { id: string; bbox: { x: number; y: number; width: number; height: number } },
  rect: { x: number; y: number; width: number; height: number },
): boolean {
  if (!block.bbox.width || !block.bbox.height) return false;
  const overlapW = Math.max(0, Math.min(rect.x + rect.width, block.bbox.x + block.bbox.width) - Math.max(rect.x, block.bbox.x));
  const overlapH = Math.max(0, Math.min(rect.y + rect.height, block.bbox.y + block.bbox.height) - Math.max(rect.y, block.bbox.y));
  return overlapW * overlapH >= block.bbox.width * block.bbox.height * 0.5;
}

/**
 * 行 → 可解释块。只使用显式特征，不确定时保守降级为段落并提示校对。
 */
export function inferBlocks(lines: OcrLine[]): OcrBlock[] {
  const usable = lines
    .map((line) => normalizeLine(line))
    .filter((line): line is OcrLine => line !== null)
    .sort((a, b) => (a.bbox.y - b.bbox.y) || (a.bbox.x - b.bbox.x));
  if (!usable.length) return [];

  const heights = usable.map((line) => line.bbox.height).filter((h) => h > 0).sort((a, b) => a - b);
  // 正文行高取下四分位：中位数会被大标题行抬高，把“标题+正文”误判成同一行距
  const bodyHeight = heights[Math.floor(heights.length * 0.25)] || 1;
  // 行距中位数：相邻行 y 间距里较小的一半，用于区分段内换行与段落间隙
  const gaps: number[] = [];
  for (let i = 1; i < usable.length; i += 1) {
    const gap = usable[i].bbox.y - (usable[i - 1].bbox.y + usable[i - 1].bbox.height);
    if (gap >= -bodyHeight * 0.5) gaps.push(gap);
  }
  gaps.sort((a, b) => a - b);
  // 典型行距取下四分位：中位数会被段间距失真（整页都是大间距时判不出分段）
  const lineGap = gaps.length ? gaps[Math.floor(gaps.length * 0.25)] : 0;
  // 只有当间距明显大于本页典型行距时才分段；间距超过 1.6 倍行高也必然分段
  const paragraphGap = Math.min(Math.max(lineGap, bodyHeight * 0.35) * 1.4, bodyHeight * 1.6);

  // 先按垂直间距切成候选组
  const groups: OcrLine[][] = [];
  let current: OcrLine[] = [usable[0]];
  for (let i = 1; i < usable.length; i += 1) {
    const prev = usable[i - 1];
    const line = usable[i];
    const gap = line.bbox.y - (prev.bbox.y + prev.bbox.height);
    if (gap > paragraphGap) {
      groups.push(current);
      current = [line];
    } else {
      current.push(line);
    }
  }
  groups.push(current);

  return groups.map((group, index) => classifyGroup(group, index, bodyHeight));
}

function normalizeLine(line: OcrLine): OcrLine | null {
  if (!line || typeof line.text !== "string") return null;
  // OCR 文本按纯文本处理：剥离控制字符
  const text = line.text.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "").trim();
  if (!text) return null;
  const bbox = line.bbox ?? { x: 0, y: 0, width: 0, height: 0 };
  return {
    text,
    confidence: typeof line.confidence === "number" ? line.confidence : 0,
    ...(Array.isArray(line.alternatives) ? {
      alternatives: line.alternatives.filter((item) => item && typeof item.text === "string" && item.text.trim())
        .slice(0, 3).map((item) => ({ text: item.text.trim().slice(0, 120), confidence: Number(item.confidence) || 0 })),
    } : {}),
    bbox: {
      x: Number(bbox.x) || 0,
      y: Number(bbox.y) || 0,
      width: Number(bbox.width) || 0,
      height: Number(bbox.height) || 1,
    },
  };
}

function classifyGroup(group: OcrLine[], index: number, bodyHeight: number): OcrBlock {
  const warnings: string[] = [];
  const joined = group.map((line) => line.text).join("\n");
  const minHeight = Math.min(...group.map((line) => line.bbox.height));
  const blockBbox: OcrBbox = {
    x: Math.min(...group.map((line) => line.bbox.x)),
    y: Math.min(...group.map((line) => line.bbox.y)),
    width: Math.max(...group.map((line) => line.bbox.x + line.bbox.width)) - Math.min(...group.map((line) => line.bbox.x)),
    height: Math.max(...group.map((line) => line.bbox.y + line.bbox.height)) - Math.min(...group.map((line) => line.bbox.y)),
  };
  for (const line of group) {
    if (line.confidence < LOW_CONFIDENCE) {
      warnings.push("含低置信度文字，请对照原图校对");
      break;
    }
  }
  for (const line of group) {
    // 备选只在主读法本身置信度不足时才提示；主读法高置信度时，落选假设
    // 仅供内部留档，继续挂警告只会让“文字明明是对的”的块永远带警示。
    const alternative = line.alternatives?.find((item) => item.text && item.text !== line.text);
    if (alternative && line.confidence < LOW_CONFIDENCE) {
      warnings.push(`同一文字框的 OCR 备选（置信度 ${alternative.confidence.toFixed(2)}）：“${alternative.text.slice(0, 48)}”；请对照原图`);
      break;
    }
  }

  const allListItems = group.every((line) => LIST_PREFIX.test(line.text));
  // 代码候选：整组纯 ASCII，且过半行含代码符号或存在明显缩进跨度。
  // normalizeLine 已去掉行首空格，缩进证据来自 bbox.x。
  const asciiOnly = group.every((line) => looksLikeCodeLine(line.text));
  const hintCount = group.filter((line) => CODE_HINTS.test(line.text)).length;
  const xSpread = Math.max(...group.map((line) => line.bbox.x)) - Math.min(...group.map((line) => line.bbox.x));
  const codeCandidate = group.length >= 2 && asciiOnly && (hintCount * 2 >= group.length || xSpread >= 12);
  const likelyCells = group.some((line, lineIndex) => group.slice(lineIndex + 1).some((other) =>
    Math.abs((line.bbox.y + line.bbox.height / 2) - (other.bbox.y + other.bbox.height / 2)) <= bodyHeight * 0.45 &&
    Math.abs(line.bbox.x - other.bbox.x) > bodyHeight * 1.5,
  ));
  const singleLineHeading =
    group.length === 1 &&
    minHeight >= bodyHeight * HEADING_RATIO &&
    joined.length <= 40 &&
    !/[。；；，,]$/.test(joined.trim());

  let kind: OcrBlockKind = "paragraph";
  let level: 2 | 3 = 3;
  if (allListItems) {
    kind = "list";
  } else if (codeCandidate) {
    kind = "code";
    warnings.push("代码块候选：OCR 易混淆缩进与符号，请核对后补充语言");
  } else if (singleLineHeading) {
    kind = "heading";
    level = minHeight >= bodyHeight * HEADING_RATIO_LARGE ? 2 : 3;
    if (group[0].confidence < LOW_CONFIDENCE) warnings.push("标题置信度较低，请核对层级与文字");
  }
  let outputLines = group;
  if (codeCandidate && kind === "code") {
    const baseX = Math.min(...group.map((line) => line.bbox.x));
    const widths = group.map((line) => line.bbox.width / Math.max(1, line.text.length)).filter((width) => width > 0 && width < bodyHeight * 2).sort((a, b) => a - b);
    const charWidth = widths[Math.floor(widths.length / 2)] || bodyHeight * 0.5;
    outputLines = group.map((line) => {
      const spaces = Math.min(16, Math.max(0, Math.round((line.bbox.x - baseX) / charWidth)));
      return { ...line, text: `${" ".repeat(spaces)}${line.text}` };
    });
  }
  if (likelyCells) warnings.push("疑似表格或多栏文字：当前按检测框顺序保留为多行，请对照原图校对单元格关系");
  return { id: `blk-${index}-${blockBbox.y}`, kind, level, lines: outputLines, warnings: [...new Set(warnings)], bbox: blockBbox };
}

/* ---------------- Markdown 组装 ---------------- */

function joinLineTexts(lines: OcrLine[]): string {
  let result = "";
  for (const line of lines) {
    const text = line.text.trim();
    if (!result) {
      result = text;
      continue;
    }
    const prevLast = result[result.length - 1] ?? "";
    const isCjkBoundary = /[\u4e00-\u9fff\u3000-\u303f，。；：、！？）》」』]/.test(prevLast);
    result += isCjkBoundary ? text : ` ${text}`;
  }
  return result;
}

/** 推断块初始的可编辑文本：代码块保留换行，其余按 CJK/西文边界拼接。 */
export function blockEditableText(block: OcrBlock): string {
  if (block.kind === "code") return block.lines.map((line) => line.text).join("\n");
  return joinLineTexts(block.lines);
}

export interface EditableBlockInput {
  kind: OcrBlockKind;
  level?: 2 | 3;
  text: string;
}

/**
 * 块 → 最终 Markdown（推断结果与用户校对后的编辑结果共用同一条路径）。
 * 表格/公式不做自动转换：设计要求保留源图并提示人工整理，
 * 因此这类内容当前作为普通段落输出，块上的 warnings 会提示“需校对”。
 */
export function assembleMarkdown(blocks: EditableBlockInput[]): string {
  const parts: string[] = [];
  for (const block of blocks) {
    const text = (block.text ?? "").replace(/\u00a0/g, " ").trim();
    if (!text) continue;
    switch (block.kind) {
      case "heading":
        parts.push(`${"#".repeat(block.level ?? 3)} ${text.split("\n")[0]}`);
        break;
      case "code":
        parts.push("```\n" + text + "\n```");
        break;
      case "list":
        parts.push(
          text
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean)
            .map((line) => (LIST_PREFIX.test(line) ? line : `- ${line.replace(/^(?:[-•·▪◦–—*]\s+)+/, "")}`))
            .join("\n"),
        );
        break;
      default:
        parts.push(text);
    }
  }
  return parts.join("\n\n") + "\n";
}

/** 推断结果的初始 Markdown。 */
export function blocksToMarkdown(blocks: OcrBlock[]): string {
  return assembleMarkdown(
    blocks.map((block) => ({ kind: block.kind, level: block.level, text: blockEditableText(block) })),
  );
}

/** 块警告汇总（预览页顶部提示用）。 */
export function collectBlockWarnings(blocks: OcrBlock[]): string[] {
  const warnings = new Set<string>();
  for (const block of blocks) for (const warning of block.warnings) warnings.add(warning);
  return [...warnings];
}

/* ---------------- 多 tile 合并（长页分片） ---------------- */

function normalizeForDedup(text: string): string {
  return text.replace(/\s+/g, "").trim();
}

/**
 * 相邻 tile 的重叠区去重（设计 §4：按坐标/文本相似度去重，不按固定像素硬裁）。
 * 规则保守且可解释：只有当一个块的全部行都能在后一个 tile 开头的连续块中
 * 找到逐行完全相同（忽略空白）的对应时，才把后者的重复前缀删掉。
 * 固定导航/页脚因此被去掉；部分被切断的行没有完全匹配，会保留并交给用户删除。
 */
export function dedupeBlocksAcrossTiles(tileBlocks: OcrBlock[][]): { blocks: OcrBlock[]; dropped: number } {
  const ordered: OcrBlock[] = [];
  let dropped = 0;
  for (let tile = 0; tile < tileBlocks.length; tile += 1) {
    const blocks = tileBlocks[tile] ?? [];
    if (tile === 0) {
      ordered.push(...blocks);
      continue;
    }
    const prevTexts = ordered.slice(-8).map((block) => block.lines.map((line) => normalizeForDedup(line.text)));
    let skip = 0;
    for (let i = 0; i < blocks.length && i < 8; i += 1) {
      const blockLines = blocks[i].lines.map((line) => normalizeForDedup(line.text));
      const matched = prevTexts.some((prev) => {
        if (prev.length !== blockLines.length) return false;
        return prev.every((text, index) => text === blockLines[index]);
      });
      if (matched) skip = i + 1;
      else break;
    }
    dropped += skip;
    ordered.push(...blocks.slice(skip));
  }
  return { blocks: ordered, dropped };
}
