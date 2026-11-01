/**
 * 一次性交接协议：纯函数，Node 单元测试与浏览器扩展共用。
 *
 * 边界：交接只传“正文或链接 + 页面标题候选 + 用户自己填写的笔记 + 目标选择”，
 * 绝不承载博客登录令牌、网页 Cookie、整页脚本或他人内容。
 * URL 与历史记录里只有随机 nonce 与扩展 ID。
 *
 * 历史：v1 力扣剪藏协议已于 2026-10-07 随「力扣导入」功能一并移除，
 * 原先为它定义的 PROTOCOL_VERSION / MAX_NOTE_BYTES / MAX_RECORD_BYTES /
 * RECORD_TTL_MS / MAX_TITLE_CHARS / MAX_FRONTEND_ID_CHARS / MAX_SOURCE_URL_CHARS
 * 等常量已无任何引用，随本次清理删除。
 */

/** nonce 至少 128-bit。 */
export const NONCE_BYTES = 16;

/* ---------------- v2 通用网页剪藏（kind=web） ---------------- */

export const WEB_PROTOCOL_VERSION = 2;
export const WEB_KIND = "web";
export const MAX_WEB_HTML_BYTES = 2 * 1024 * 1024;
export const MAX_CHUNK_BYTES = 64 * 1024;
export const MAX_PENDING_CLIPS = 2;
export const MAX_WEB_SOURCE_URL_CHARS = 2048;
export const MAX_WEB_TITLE_CHARS = 200;

export const WEB_GET_META = "blog.webclip.get-meta";
export const WEB_GET_CHUNK = "blog.webclip.get-chunk";
export const WEB_ACK = "blog.webclip.ack";
export const WEB_CANCEL = "blog.webclip.cancel";

export const WEB_TARGETS = ["private_note", "article_draft"];

export class WebClipError extends Error {
  constructor(message, code) {
    super(message);
    this.name = "WebClipError";
    this.code = code;
  }
}
/** 本地调试站点：构建时登记；生产域名未确定前不预置。 */
export const DEFAULT_TARGET_ORIGINS = ["http://127.0.0.1:8001", "http://127.0.0.1:5173", "http://127.0.0.1:5174"];


export function utf8ByteLength(value) {
  if (typeof value !== "string") return 0;
  return new TextEncoder().encode(value).length;
}

export async function sha256Hex(value) {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** 128-bit 加密随机 nonce，转十六进制。浏览器与 Node（crypto.webcrypto）通用。 */
export function createNonce(randomBytes) {
  const bytes = typeof randomBytes === "function" ? randomBytes(NONCE_BYTES) : null;
  if (!bytes) {
    throw new WebClipError("无法生成安全随机数", "no_entropy");
  }
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function originOf(rawUrl) {
  try {
    return new URL(rawUrl).origin;
  } catch {
    return "";
  }
}

/* ---------------- v2 剪藏记录与校验 ---------------- */

/** 站内来源 URL：仅 HTTP(S)、无凭据、限长；存储前由站内再去掉跟踪参数。 */
export function sanitizeWebSourceUrl(raw) {
  if (typeof raw !== "string") return "";
  const value = raw.trim();
  if (!value || value.length > MAX_WEB_SOURCE_URL_CHARS) return "";
  if (/[\x00-\x1f\x7f]/.test(value)) return "";
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    if (url.username || url.password) return "";
    // 常见跟踪参数不作为来源信息保存
    for (const key of [...url.searchParams.keys()]) {
      if (/^utm_|^spm$|^from$|^share$|^scene$/i.test(key)) url.searchParams.delete(key);
    }
    return url.toString();
  } catch {
    return "";
  }
}

/** 按 UTF-8 字节切片：绝不多字节字符中间截断。 */
export function chunkUtf8(text, maxBytes = MAX_CHUNK_BYTES) {
  const total = new TextEncoder().encode(text).length;
  const chunks = [];
  let start = 0;
  let currentBytes = 0;
  for (let index = 0; index < text.length;) {
    const point = text.codePointAt(index);
    const size = point <= 0x7f ? 1 : point <= 0x7ff ? 2 : point <= 0xffff ? 3 : 4;
    if (currentBytes + size > maxBytes && index > start) {
      chunks.push(text.slice(start, index));
      start = index;
      currentBytes = 0;
    }
    currentBytes += size;
    index += point > 0xffff ? 2 : 1;
  }
  if (start < text.length) chunks.push(text.slice(start));
  return { chunks, totalBytes: total };
}

export function buildWebClipRecord(input) {
  const record = {
    kind: WEB_KIND,
    version: WEB_PROTOCOL_VERSION,
    nonce: input.nonce,
    sourceUrl: input.sourceUrl,
    canonicalUrl: input.canonicalUrl ?? input.sourceUrl,
    titleCandidate: input.titleCandidate ?? "",
    siteCandidate: input.siteCandidate ?? "",
    captureMode: input.captureMode,
    captureTarget: input.captureTarget,
    targetOrigin: input.targetOrigin,
    extractorVersion: input.extractorVersion,
    html: input.html,
    markdown: input.markdown ?? "",
    sha256: input.sha256 ?? "",
    ownNote: input.ownNote ?? "",
    warnings: input.warnings ?? [],
    createdAt: input.createdAt,
    expiresAt: input.expiresAt,
    targetTabId: input.targetTabId ?? null,
    consumed: false,
  };
  if (typeof record.html !== "string" || !record.html || utf8ByteLength(record.html) > MAX_WEB_HTML_BYTES) {
    throw new WebClipError("剪藏正文超出大小限制或为空", "size_limit");
  }
  if (utf8ByteLength(JSON.stringify(record)) > MAX_WEB_HTML_BYTES + 64 * 1024) {
    throw new WebClipError("剪藏内容超出大小限制", "size_limit");
  }
  return record;
}

/** get-meta 响应：只含元数据，不含正文。 */
export function webClipMeta(record) {
  return {
    kind: record.kind,
    version: record.version,
    sourceUrl: record.sourceUrl,
    canonicalUrl: record.canonicalUrl,
    titleCandidate: record.titleCandidate,
    siteCandidate: record.siteCandidate,
    captureMode: record.captureMode,
    captureTarget: record.captureTarget,
    capturedAt: new Date(record.createdAt).toISOString(),
    extractorVersion: record.extractorVersion,
    htmlUtf8Bytes: utf8ByteLength(record.html),
    sha256: record.sha256,
    ownNote: record.ownNote,
    // UTF-8 分片不能截断多字节字符；每片可能少于上限，不能用总字节数除以上限估算片数。
    chunkCount: chunkUtf8(record.html).chunks.length,
    warnings: record.warnings,
  };
}

/**
 * 站内侧对 worker 响应的校验：消息类型/版本、origin（协议+主机+端口）、
 * /blog 路径、目标 tab、nonce、TTL 与记录存在性。
 */
export function validateWebRecordAccess(message, record, sender, { now = Date.now(), expectPath = "/blog" } = {}) {
  if (!message || typeof message !== "object") {
    return { ok: false, code: "bad_message", detail: "消息格式不正确" };
  }
  if (message.version !== WEB_PROTOCOL_VERSION) {
    return { ok: false, code: "bad_version", detail: "剪藏协议版本不匹配，请更新扩展" };
  }
  if (!record || record.kind !== WEB_KIND) {
    return { ok: false, code: "unknown_nonce", detail: "剪藏记录不存在或已被消费" };
  }
  if (record.consumed) {
    return { ok: false, code: "replayed", detail: "该剪藏已接收过，请从扩展重新发送" };
  }
  if (now >= record.expiresAt) {
    return { ok: false, code: "expired", detail: "剪藏已过期，请从扩展重新发送" };
  }
  const senderUrl = typeof sender?.url === "string" ? sender.url : "";
  let parsed;
  try {
    parsed = new URL(senderUrl);
  } catch {
    return { ok: false, code: "origin_mismatch", detail: "来源页面无法识别" };
  }
  if (parsed.origin !== record.targetOrigin) {
    return { ok: false, code: "origin_mismatch", detail: "来源页面与剪藏目标不一致（协议/主机/端口必须完全相同）" };
  }
  if (!parsed.pathname.startsWith(expectPath)) {
    return { ok: false, code: "origin_mismatch", detail: "来源页面路径不是博客页面" };
  }
  if (sender?.tab?.id == null) {
    return { ok: false, code: "tab_mismatch", detail: "缺少标签页上下文" };
  }
  if (record.targetTabId != null && sender.tab.id !== record.targetTabId) {
    return { ok: false, code: "tab_mismatch", detail: "本标签页不是剪藏目标页面" };
  }
  if (message.nonce !== record.nonce) {
    return { ok: false, code: "nonce_mismatch", detail: "剪藏凭据不匹配" };
  }
  return { ok: true, record };
}

export function validateWebChunkIndex(index, chunkCount) {
  if (!Number.isInteger(index) || index < 0 || index >= chunkCount) {
    return { ok: false, code: "chunk_missing", detail: `请求的分片不存在（共 ${chunkCount} 片）` };
  }
  return { ok: true };
}
