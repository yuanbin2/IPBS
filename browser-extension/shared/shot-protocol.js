/**
 * B-045 screenshot-v1 交接协议：纯函数，Node 单元测试与扩展共用。
 *
 * 边界（docs/长截图OCR转Markdown与私有笔记设计V3.0.md §5）：
 * - 图片 Blob 只存扩展 IndexedDB；storage.session 只存 nonce/元数据。
 * - 不进 storage.sync、URL fragment、日志或剪贴板；不提高 v2 HTML 的 2 MiB 上限。
 * - 消费一次性：ack 原子消费整个会话并清理 Blob；错 origin/错 tab/过期/重放不 ACK。
 */

import { sanitizeWebSourceUrl } from "./protocol.js";

export const SHOT_PROTOCOL_VERSION = 1;
export const SHOT_KIND = "screenshot";

export const SHOT_GET_META = "blog.screenshot.get-meta";
export const SHOT_GET_TILE = "blog.screenshot.get-tile-chunk";
export const SHOT_ACK = "blog.screenshot.ack";
export const SHOT_CANCEL = "blog.screenshot.cancel";

/** 手动长截图上限：30 个视口、约 30,000 CSS px、20 MiB、单次 5 分钟。 */
export const MAX_SHOT_TILES = 30;
export const MAX_SHOT_PAGE_HEIGHT_CSS = 30_000;
export const MAX_SHOT_TOTAL_BYTES = 20 * 1024 * 1024;
export const SHOT_SESSION_TIMEOUT_MS = 5 * 60 * 1000;
/** 图片暂存 TTL：15 分钟。 */
export const SHOT_TTL_MS = 15 * 60 * 1000;
/** 单个 tile 的二进制分片大小（base64 前的字节数）。 */
export const SHOT_CHUNK_BYTES = 64 * 1024;
/** 同一时刻最多几个待接收的截图会话。 */
export const MAX_PENDING_SHOTS = 1;

export const SHOT_MIME_TYPES = ["image/png", "image/jpeg", "image/webp"];
export const SHOT_CAPTURE_MODES = ["screen", "region", "longpage"];

/** 页面 fragment 只带 nonce/扩展 ID/kind，绝无图片数据。 */
export const SHOT_FRAGMENT_KEY = "shot";

/** 用户快滚后的补拍坐标：最多前进 85% 视口，始终与前一屏重叠。 */
export function nextManualShotY(lastY, desiredY, viewportHeight, startY) {
  if (![lastY, desiredY, viewportHeight, startY].every(Number.isFinite) || viewportHeight <= 0) {
    throw new ShotProtocolError("截图滚动坐标无效", "bad_scroll_position");
  }
  const maxY = startY + MAX_SHOT_PAGE_HEIGHT_CSS - viewportHeight;
  if (desiredY <= lastY + 8 || maxY <= lastY + 2) return null;
  return Math.min(desiredY, maxY, lastY + Math.max(50, Math.floor(viewportHeight * 0.85)));
}

export class ShotProtocolError extends Error {
  constructor(message, code) {
    super(message);
    this.name = "ShotProtocolError";
    this.code = code;
  }
}

/* ---------------- 采集计划 ---------------- */

/**
 * 长页采集计划：步进约 85% 视口高（保留 15% 重叠），终点为用户指定 endY。
 * 返回每个 tile 的目标 scrollY、实际覆盖范围与是否被截断。
 */
/**
 * 判断两次读取的 URL 是否仍是同一个文档：只比较 origin + pathname。
 * 许多网站会在用户滚动时用 history.replaceState 把滚动位置写进 URL
 * （query/锚点漂移）；整串相等会把这种「页面自己改 URL」误判成导航。
 */
export function sameShotPageLocation(expectedUrl, actualUrl) {
  if (typeof expectedUrl !== "string" || typeof actualUrl !== "string") return false;
  try {
    const expected = new URL(expectedUrl);
    const actual = new URL(actualUrl);
    return expected.origin === actual.origin && expected.pathname === actual.pathname;
  } catch {
    return expectedUrl === actualUrl;
  }
}

export function planLongPageCapture({ viewportHeight, startY, endY, maxTiles = MAX_SHOT_TILES, maxHeightCss = MAX_SHOT_PAGE_HEIGHT_CSS }) {
  if (!Number.isFinite(viewportHeight) || viewportHeight < 50) {
    throw new ShotProtocolError("视口高度异常", "bad_viewport");
  }
  if (!Number.isFinite(startY) || !Number.isFinite(endY) || endY < startY) {
    throw new ShotProtocolError("截取范围无效", "bad_range");
  }
  const height = endY - startY;
  const truncatedHeight = height > maxHeightCss;
  const cappedEndY = truncatedHeight ? startY + maxHeightCss : endY;
  const step = Math.max(50, Math.floor(viewportHeight * 0.85));
  const scrollYs = [];
  for (let y = startY; ; y += step) {
    const lastStep = y + viewportHeight >= cappedEndY;
    // 最后一步把视口底边对齐到终点：不越过用户选择的 endY（覆盖范围如实记录）
    scrollYs.push(lastStep ? Math.max(0, Math.min(y, cappedEndY - viewportHeight)) : y);
    if (scrollYs.length > maxTiles) break;
    if (lastStep) break;
  }
  const truncated = truncatedHeight || scrollYs.length > maxTiles;
  const tiles = scrollYs.slice(0, maxTiles).map((scrollY, index) => ({ index, scrollY }));
  return {
    tiles,
    step,
    // 记录实际被视口覆盖的范围；张数上限可能早于用户选择的终点。
    // 短于一个视口的选择也会截入周边页面，因此不能把选择范围冒充实际截图范围。
    coveredTop: tiles[0]?.scrollY ?? startY,
    coveredBottom: tiles.length ? tiles[tiles.length - 1].scrollY + viewportHeight : startY,
    truncated,
  };
}

/* ---------------- 会话元数据 ---------------- */

export function sanitizeShotTitle(value, maxChars = 200) {
  if (typeof value !== "string") return "";
  return value.replace(/[\r\n\t]+/g, " ").replace(/[\u0000-\u001f\u007f]+/g, " ").trim().slice(0, maxChars);
}

/** tile 元数据：字节大小、哈希、像素尺寸与页面位置都由扩展计算并写入。 */
export function buildShotTileMeta({ index, mime, bytes, sha256, width, height, scrollX = 0, scrollY = 0 }) {
  if (!SHOT_MIME_TYPES.includes(mime)) {
    throw new ShotProtocolError(`不支持的截图格式：${mime}`, "bad_mime");
  }
  if (!Number.isInteger(index) || index < 0 || index >= MAX_SHOT_TILES) {
    throw new ShotProtocolError("tile 序号超出限制", "too_many_tiles");
  }
  if (!(bytes instanceof ArrayBuffer) && !ArrayBuffer.isView(bytes)) {
    throw new ShotProtocolError("tile 内容必须是二进制", "bad_tile");
  }
  const byteLength = bytes.byteLength;
  if (byteLength <= 0) {
    throw new ShotProtocolError("tile 内容为空", "bad_tile");
  }
  if (typeof sha256 !== "string" || !/^[0-9a-f]{64}$/.test(sha256)) {
    throw new ShotProtocolError("tile 缺少有效校验和", "bad_sha");
  }
  return {
    index,
    mime,
    bytes: byteLength,
    sha256,
    width: Math.max(0, Math.round(Number(width) || 0)),
    height: Math.max(0, Math.round(Number(height) || 0)),
    scrollX: Math.round(Number(scrollX) || 0),
    scrollY: Math.round(Number(scrollY) || 0),
  };
}

/** 仅交接可见图片/代码块的归一化屏幕矩形；不交接图片源 URL 或页面正文。 */
export function normalizeImageCandidates(value) {
  if (!Array.isArray(value)) return [];
  // 每屏候选上限：网页图片 + 代码块（kind:"code"）合计，放宽到 60；
  // 接收端 safeImageCandidates 按同一契约校验。
  return value.slice(0, 60).flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const { x, y, width, height, key, fullX, fullY, fullWidth, fullHeight, priority, kind } = item;
    if (![x, y, width, height].every((number) => typeof number === "number" && Number.isFinite(number))) return [];
    if (x < 0 || y < 0 || width <= 0 || height <= 0 || x + width > 1.001 || y + height > 1.001 || width > 1 || height > 1) return [];
    if (kind !== undefined && kind !== "code") return [];
    const fullValues = [fullX, fullY, fullWidth, fullHeight];
    const hasAnyFull = fullValues.some((number) => number !== undefined);
    const hasFull = fullValues.every((number) => typeof number === "number" && Number.isFinite(number)) &&
      fullX >= 0 && fullX <= 1 && fullY >= 0 && fullY <= 30_000 && fullWidth > 0 && fullWidth <= 1 && fullHeight > 0 && fullHeight <= 30_000;
    if (hasAnyFull && !hasFull) return [];
    return [{ ...(typeof key === "string" && /^(?:code-)?\d{1,8}$/.test(key) ? { key } : {}),
      x: Math.min(1, x), y: Math.min(1, y), width: Math.min(width, 1 - x), height: Math.min(height, 1 - y),
      ...(hasFull ? { fullX, fullY, fullWidth, fullHeight } : {}),
      ...(Number.isInteger(priority) && priority >= 0 && priority <= 2 ? { priority } : {}),
      ...(kind === "code" ? { kind } : {}) }];
  });
}

export function buildShotRecord(input) {
  if (input.mode && !SHOT_CAPTURE_MODES.includes(input.mode)) {
    throw new ShotProtocolError("不支持的截图模式", "bad_mode");
  }
  if (!Array.isArray(input.tiles) || input.tiles.length === 0) {
    throw new ShotProtocolError("至少需要一张截图", "no_tiles");
  }
  if (input.tiles.length > MAX_SHOT_TILES) {
    throw new ShotProtocolError(`最多 ${MAX_SHOT_TILES} 张视口截图`, "too_many_tiles");
  }
  const totalBytes = input.tiles.reduce((sum, tile) => sum + tile.bytes, 0);
  if (totalBytes > MAX_SHOT_TOTAL_BYTES) {
    throw new ShotProtocolError("截图总大小超过 20 MiB 上限", "size_limit");
  }
  const sourceUrl = sanitizeWebSourceUrl(input.sourceUrl ?? "");
  const rawSelection = input.selection;
  let selection = null;
  if (rawSelection != null) {
    const { left, right, top, bottom } = rawSelection;
    if (![left, right, top, bottom].every((value) => typeof value === "number" && Number.isFinite(value)) ||
        left < 0 || right > 1 || right - left < 0.01 || top < 0 || bottom <= top || bottom - top > MAX_SHOT_PAGE_HEIGHT_CSS) {
      throw new ShotProtocolError("截图选择范围无效", "bad_range");
    }
    selection = { left, right, top: Math.round(top), bottom: Math.round(bottom) };
  }
  const record = {
    kind: SHOT_KIND,
    version: SHOT_PROTOCOL_VERSION,
    nonce: input.nonce,
    mode: input.mode ?? "screen",
    sourceUrl,
    titleCandidate: sanitizeShotTitle(input.titleCandidate ?? ""),
    capturedAt: input.capturedAt,
    dpr: Number(input.dpr) || 1,
    viewport: {
      width: Math.round(Number(input.viewportWidth) || 0),
      height: Math.round(Number(input.viewportHeight) || 0),
    },
    covered: {
      top: Math.round(Number(input.coveredTop) || 0),
      bottom: Math.round(Number(input.coveredBottom) || 0),
    },
    truncated: Boolean(input.truncated),
    ...(selection ? { selection } : {}),
    warnings: (Array.isArray(input.warnings) ? input.warnings : []).slice(0, 10).map((w) => sanitizeShotTitle(w, 120)),
    tiles: input.tiles.map((tile) => {
      const imageCandidates = normalizeImageCandidates(tile.imageCandidates);
      const imageCandidateOverflow = Number.isInteger(tile.imageCandidateOverflow) && tile.imageCandidateOverflow >= 0 && tile.imageCandidateOverflow <= 10_000
        ? tile.imageCandidateOverflow : 0;
      return { ...tile, imageCandidateOverflow, ...(imageCandidates.length ? { imageCandidates } : {}) };
    }),
    totalBytes,
    createdAt: input.createdAt,
    expiresAt: input.expiresAt,
    targetOrigin: input.targetOrigin,
    targetTabId: input.targetTabId ?? null,
    consumed: false,
  };
  return record;
}

/** get-meta 响应：只含元数据，不含图片字节。 */
export function shotMeta(record) {
  return {
    kind: record.kind,
    version: record.version,
    mode: record.mode,
    sourceUrl: record.sourceUrl,
    titleCandidate: record.titleCandidate,
    capturedAt: new Date(record.createdAt).toISOString(),
    dpr: record.dpr,
    viewport: record.viewport,
    covered: record.covered,
    truncated: record.truncated,
    ...(record.selection ? { selection: record.selection } : {}),
    warnings: record.warnings,
    tileCount: record.tiles.length,
    tiles: record.tiles,
    totalBytes: record.totalBytes,
  };
}

/* ---------------- worker 侧校验 ---------------- */

/**
 * 与 v2 的 validateWebRecordAccess 同构：消息类型/版本/nonce/TTL、
 * sender origin 精确相等、/blog 路径、目标 tab 绑定、一次性消费。
 */
export function validateShotRecordAccess(message, record, sender, { now = Date.now(), expectPath = "/blog" } = {}) {
  if (!message || typeof message !== "object") {
    return { ok: false, code: "bad_message", detail: "消息格式不正确" };
  }
  if (message.version !== SHOT_PROTOCOL_VERSION) {
    return { ok: false, code: "bad_version", detail: "截图交接协议版本不匹配，请更新扩展" };
  }
  if (!record || record.kind !== SHOT_KIND) {
    return { ok: false, code: "unknown_nonce", detail: "截图交接记录不存在或已被消费" };
  }
  if (record.consumed) {
    return { ok: false, code: "replayed", detail: "该截图已接收过，请从扩展重新发送" };
  }
  if (now >= record.expiresAt) {
    return { ok: false, code: "expired", detail: "截图交接已过期，请从扩展重新发送" };
  }
  const senderUrl = typeof sender?.url === "string" ? sender.url : "";
  let parsed;
  try {
    parsed = new URL(senderUrl);
  } catch {
    return { ok: false, code: "origin_mismatch", detail: "来源页面无法识别" };
  }
  if (parsed.origin !== record.targetOrigin) {
    return { ok: false, code: "origin_mismatch", detail: "来源页面与截图交接目标不一致（协议/主机/端口必须完全相同）" };
  }
  if (!parsed.pathname.startsWith(expectPath)) {
    return { ok: false, code: "origin_mismatch", detail: "来源页面路径不是博客页面" };
  }
  if (sender?.tab?.id == null) {
    return { ok: false, code: "tab_mismatch", detail: "缺少标签页上下文" };
  }
  if (record.targetTabId != null && sender.tab.id !== record.targetTabId) {
    return { ok: false, code: "tab_mismatch", detail: "本标签页不是截图交接目标页面" };
  }
  if (message.nonce !== record.nonce) {
    return { ok: false, code: "nonce_mismatch", detail: "截图交接凭据不匹配" };
  }
  return { ok: true, record };
}

export function validateShotTileIndex(index, tileCount) {
  if (!Number.isInteger(index) || index < 0 || index >= tileCount) {
    return { ok: false, code: "tile_missing", detail: `请求的截图分片不存在（共 ${tileCount} 张）` };
  }
  return { ok: true };
}

/* ---------------- 二进制分片 ---------------- */

/** ArrayBuffer → base64。扩展 worker 与 Node 均有 btoa；分块避免参数长度上限。 */
export function bytesToBase64(bytes) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < view.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, view.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

export function base64ToBytes(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/** 把一个 tile 切成 base64 分片。 */
export function chunkTileToBase64(bytes, chunkSize = SHOT_CHUNK_BYTES) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const chunks = [];
  for (let offset = 0; offset < view.length; offset += chunkSize) {
    chunks.push(bytesToBase64(view.subarray(offset, Math.min(offset + chunkSize, view.length))));
  }
  if (chunks.length === 0) chunks.push("");
  return { chunks, totalBytes: view.length };
}

/** 只编码请求的分块，避免每次 64 KiB 请求都重新编码整张长截图。 */
export function tileChunkBase64(bytes, chunkIndex, chunkSize = SHOT_CHUNK_BYTES) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const count = chunkCountFor(view, chunkSize);
  if (!Number.isInteger(chunkIndex) || chunkIndex < 0 || chunkIndex >= count) {
    throw new ShotProtocolError(`请求的分块不存在（共 ${count} 块）`, "chunk_missing");
  }
  const start = chunkIndex * chunkSize;
  return { chunk: bytesToBase64(view.subarray(start, Math.min(start + chunkSize, view.length))), chunkCount: count };
}

/** 站内侧按 base64 重组并验大小。 */
export function assembleTileFromBase64(chunks, expectedBytes) {
  const parts = [];
  let total = 0;
  for (const chunk of chunks) {
    const bytes = base64ToBytes(chunk);
    total += bytes.length;
    if (total > expectedBytes) {
      throw new ShotProtocolError("分片总大小超过声明值", "size_limit");
    }
    parts.push(bytes);
  }
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  if (total !== expectedBytes) {
    throw new ShotProtocolError("分片总大小与声明不符", "size_limit");
  }
  return out;
}

export function chunkCountFor(bytes, chunkSize = SHOT_CHUNK_BYTES) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  return Math.max(1, Math.ceil(view.length / chunkSize));
}

/** 站内侧的图片签名校验：与站点 screenshotOcr.detectImageSignature 相同的规则。 */
export function detectTileSignature(bytes) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (view.length < 12) return null;
  if (view[0] === 0x89 && view[1] === 0x50 && view[2] === 0x4e && view[3] === 0x47 &&
      view[4] === 0x0d && view[5] === 0x0a && view[6] === 0x1a && view[7] === 0x0a) {
    return "png";
  }
  if (view[0] === 0xff && view[1] === 0xd8 && view[2] === 0xff) return "jpeg";
  if (view[0] === 0x52 && view[1] === 0x49 && view[2] === 0x46 && view[3] === 0x46 &&
      view[8] === 0x57 && view[9] === 0x45 && view[10] === 0x42 && view[11] === 0x50) {
    return "webp";
  }
  return null;
}

/** 页面 fragment：只解析 #shot=<nonce>&ext=<id>&kind=screenshot。 */
export function readScreenshotFragmentParams(search) {
  const params = new URLSearchParams(String(search ?? "").replace(/^#/, ""));
  const nonce = params.get("shot") ?? "";
  const extensionId = params.get("ext") ?? "";
  const kind = params.get("kind") ?? "";
  if (kind !== SHOT_KIND) return null;
  if (!/^[0-9a-f]{32}$/.test(nonce)) return null;
  if (!/^[a-zA-Za-z0-9]{1,128}$/.test(extensionId)) return null;
  return { nonce, extensionId };
}
