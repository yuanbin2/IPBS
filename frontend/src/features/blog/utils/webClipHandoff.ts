/**
 * B-043 站内侧 v2 通用网页剪藏接收器。
 *
 * 顺序：get-meta → get-chunk(0..n-1) → 本地拼装并验 SHA-256 → ack。
 * 扩展返回的一切都是不可信输入：URL 白名单、文本限长、控制字符剥离；
 * 真正的 HTML 校验仍由后端 imports/html/preview 完成。
 */

export type WebClipTarget = "private_note" | "article_draft";

export interface WebClipChunk {
  index: number;
  chunk: string;
}

export interface WebClipMeta {
  kind: "web";
  version: number;
  sourceUrl: string;
  canonicalUrl: string;
  titleCandidate: string;
  siteCandidate: string;
  captureMode: string;
  captureTarget: WebClipTarget;
  capturedAt: string;
  extractorVersion: string;
  htmlUtf8Bytes: number;
  sha256: string;
  ownNote: string;
  chunkCount: number;
  warnings: Array<{ code: string; count: number }>;
}

export interface WebClipPayload {
  meta: WebClipMeta;
  html: string;
}

export type WebClipFailureReason =
  | "no_extension"
  | "not_authenticated"
  | "expired_or_replayed"
  | "origin_or_tab_mismatch"
  | "chunk_missing"
  | "size_limit"
  | "checksum_mismatch"
  | "extension_error";

export interface WebClipFailure {
  reason: WebClipFailureReason;
  detail: string;
}

export type WebClipOutcome =
  | ({ status: "ok"; payload: WebClipPayload } & Record<string, unknown>)
  | ({ status: "failed" } & WebClipFailure);

const GET_META = "blog.webclip.get-meta";
const GET_CHUNK = "blog.webclip.get-chunk";
const ACK = "blog.webclip.ack";
const CANCEL = "blog.webclip.cancel";
const PROTOCOL_VERSION = 2;
const MAX_HTML_BYTES = 2 * 1024 * 1024;
const MAX_CHUNK_BYTES = 64 * 1024;
const NONCE_PATTERN = /^[0-9a-f]{32}$/;
const EXTENSION_ID_PATTERN = /^[a-zA-Za-z0-9]{1,128}$/;

interface ChromeRuntimeLike {
  sendMessage(extensionId: string, message: unknown, callback: (response: unknown) => void): void;
  lastError?: { message?: string };
}

interface WebClipMessage {
  ok?: boolean;
  meta?: Partial<WebClipMeta>;
  index?: number;
  chunk?: string;
  code?: string;
  detail?: string;
}

function chromeRuntime(): ChromeRuntimeLike | null {
  const runtime = (globalThis as unknown as { chrome?: { runtime?: ChromeRuntimeLike } }).chrome?.runtime;
  if (!runtime || typeof runtime.sendMessage !== "function") return null;
  return runtime;
}

/** 解析 #clip=<nonce>&ext=<id>&kind=web；非法 fragment 一律忽略。 */
export function readWebClipFragment(hash: string): { nonce: string; extensionId: string } | null {
  const raw = String(hash ?? "").replace(/^#/, "");
  if (!raw) return null;
  const params = new URLSearchParams(raw);
  const nonce = params.get("clip") ?? "";
  const extensionId = params.get("ext") ?? "";
  const kind = params.get("kind") ?? "";
  if (kind !== "web") return null;
  if (!NONCE_PATTERN.test(nonce)) return null;
  if (!EXTENSION_ID_PATTERN.test(extensionId)) return null;
  return { nonce, extensionId };
}

export function clearWebClipFragment(): void {
  if (typeof window === "undefined" || !window.location) return;
  const { pathname, search } = window.location;
  window.history.replaceState(window.history.state, "", `${pathname}${search}`);
}

function sanitizeText(value: unknown, maxChars: number): string {
  if (typeof value !== "string") return "";
  return value
    .replace(/[\r\n\t]+/g, " ")
    .replace(/[\u0000-\u001f\u007f]+/g, " ")
    .trim()
    .slice(0, maxChars);
}

function safeSourceUrl(value: unknown): string {
  if (typeof value !== "string") return "";
  const text = value.trim();
  if (!text || text.length > 2048) return "";
  try {
    const url = new URL(text);
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    if (url.username || url.password) return "";
    return url.toString();
  } catch {
    return "";
  }
}

async function utf8Bytes(text: string): Promise<number> {
  return new TextEncoder().encode(text).length;
}

async function sha256Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function send(runtime: ChromeRuntimeLike, extensionId: string, message: unknown): Promise<WebClipMessage> {
  return new Promise<WebClipMessage>((resolve) => {
    let settled = false;
    const finish = (value: WebClipMessage) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const timer = setTimeout(() => finish({ ok: false, code: "extension_error", detail: "扩展响应超时" }), 8000);
    try {
      runtime.sendMessage(extensionId, message, (raw: unknown) => {
        clearTimeout(timer);
        const error = runtime.lastError?.message;
        if (error) {
          finish({ ok: false, code: "extension_error", detail: error });
          return;
        }
        finish((raw ?? {}) as WebClipMessage);
      });
    } catch (cause) {
      clearTimeout(timer);
      finish({
        ok: false,
        code: "extension_error",
        detail: cause instanceof Error ? cause.message : "扩展调用失败",
      });
    }
  });
}

function mapFailure(code: string | undefined, detail: string | undefined): WebClipFailure {
  switch (code) {
    case "expired":
    case "replayed":
    case "unknown_nonce":
      return { reason: "expired_or_replayed", detail: detail ?? "交接已失效，请从扩展重新发送" };
    case "origin_mismatch":
    case "tab_mismatch":
      return { reason: "origin_or_tab_mismatch", detail: detail ?? "交接目标不匹配，请从扩展重新发送" };
    case "chunk_missing":
      return { reason: "chunk_missing", detail: detail ?? "剪藏分片缺失，请重新发送" };
    case "size_limit":
      return { reason: "size_limit", detail: detail ?? "剪藏内容超出大小限制" };
    default:
      return { reason: "extension_error", detail: detail ?? "交接失败，请重新发送" };
  }
}

/** 消费一次性剪藏：取回正文 HTML 与元数据（仅内存，不落库）。 */
export async function consumeWebClip(nonce: string, extensionId: string): Promise<WebClipOutcome> {
  const runtime = chromeRuntime();
  if (!runtime) {
    return { status: "failed", reason: "no_extension", detail: "未检测到浏览器扩展，请从扩展重新发送。" };
  }
  const metaResponse = await send(runtime, extensionId, { type: GET_META, version: PROTOCOL_VERSION, nonce });
  if (!metaResponse.ok || !metaResponse.meta) {
    return { status: "failed", ...mapFailure(metaResponse.code, metaResponse.detail) };
  }
  const raw = metaResponse.meta;
  if (raw.kind !== "web" || raw.version !== PROTOCOL_VERSION) {
    return { status: "failed", reason: "extension_error", detail: "剪藏协议版本不匹配，请更新扩展" };
  }
  const sourceUrl = safeSourceUrl(raw.sourceUrl) || safeSourceUrl(raw.canonicalUrl);
  if (!sourceUrl) {
    return { status: "failed", reason: "extension_error", detail: "交接里的来源链接不合法，请从扩展重新发送" };
  }
  const chunkCount = typeof raw.chunkCount === "number" ? raw.chunkCount : 0;
  const declaredBytes = typeof raw.htmlUtf8Bytes === "number" ? raw.htmlUtf8Bytes : Number.NaN;
  if (!Number.isInteger(chunkCount) || chunkCount < 1 || chunkCount > 64 ||
      !Number.isInteger(declaredBytes) || declaredBytes < 1 || declaredBytes > MAX_HTML_BYTES) {
    return { status: "failed", reason: "size_limit", detail: "剪藏分片数量异常" };
  }
  if (typeof raw.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(raw.sha256)) {
    return { status: "failed", reason: "checksum_mismatch", detail: "剪藏缺少有效校验和，请重新发送" };
  }

  let html = "";
  let receivedBytes = 0;
  for (let index = 0; index < chunkCount; index += 1) {
    const part = await send(runtime, extensionId, { type: GET_CHUNK, version: PROTOCOL_VERSION, nonce, index });
    if (!part.ok || typeof part.chunk !== "string" || part.index !== index) {
      return { status: "failed", ...mapFailure(part.code ?? "chunk_missing", part.detail) };
    }
    const chunkBytes = await utf8Bytes(part.chunk);
    receivedBytes += chunkBytes;
    if (chunkBytes > MAX_CHUNK_BYTES || receivedBytes > MAX_HTML_BYTES || receivedBytes > declaredBytes) {
      await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
      return { status: "failed", reason: "size_limit", detail: "剪藏分片或正文超过声明大小，请重新发送" };
    }
    html += part.chunk;
  }
  const bytes = receivedBytes;
  if (bytes > MAX_HTML_BYTES) {
    await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
    return { status: "failed", reason: "size_limit", detail: "剪藏正文超过 2 MiB 上限，请缩小范围后重试" };
  }
  if (declaredBytes !== bytes) {
    await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
    return { status: "failed", reason: "size_limit", detail: "剪藏字节数与声明不符，请重新发送" };
  }
  const digest = await sha256Hex(html);
  if (digest !== raw.sha256) {
    await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
    return { status: "failed", reason: "checksum_mismatch", detail: "剪藏内容校验失败，请从扩展重新发送" };
  }
  const meta: WebClipMeta = {
    kind: "web",
    version: PROTOCOL_VERSION,
    sourceUrl,
    canonicalUrl: safeSourceUrl(raw.canonicalUrl) || sourceUrl,
    titleCandidate: sanitizeText(raw.titleCandidate, 200),
    siteCandidate: sanitizeText(raw.siteCandidate, 120),
    captureMode: ["article", "selection", "full"].includes(String(raw.captureMode)) ? String(raw.captureMode) : "article",
    captureTarget: raw.captureTarget === "article_draft" ? "article_draft" : "private_note",
    capturedAt: typeof raw.capturedAt === "string" ? raw.capturedAt : new Date().toISOString(),
    extractorVersion: sanitizeText(raw.extractorVersion, 40) || "unknown",
    htmlUtf8Bytes: bytes,
    sha256: digest,
    ownNote: sanitizeText(raw.ownNote, 300),
    chunkCount,
    warnings: Array.isArray(raw.warnings)
      ? raw.warnings
          .filter((item): item is { code: string; count: number } =>
            Boolean(item) && typeof (item as { code?: unknown }).code === "string")
          .slice(0, 20)
      : [],
  };
  const acknowledged = await send(runtime, extensionId, { type: ACK, version: PROTOCOL_VERSION, nonce });
  if (!acknowledged.ok) {
    return { status: "failed", ...mapFailure(acknowledged.code, acknowledged.detail) };
  }
  return { status: "ok", payload: { meta, html } };
}

/** 用户取消时通知扩展清理暂存。 */
export async function cancelWebClip(nonce: string, extensionId: string): Promise<void> {
  const runtime = chromeRuntime();
  if (!runtime) return;
  await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
}

