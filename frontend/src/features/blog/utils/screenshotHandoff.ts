/**
 * B-045 站内侧 screenshot-v1 接收器。
 *
 * 顺序：get-meta → 逐 tile get-tile-chunk → 本地拼装并验字节大小/SHA-256/图片签名 → ack。
 * 扩展返回的一切都是不可信输入：元数据限长、分片大小校验、签名白名单；
 * 校验失败一律 cancel（不发 ack），图片 Blob 只在内存中交给本地 OCR。
 */

export interface ScreenshotTileMeta {
  index: number;
  mime: string;
  bytes: number;
  sha256: string;
  width: number;
  height: number;
  scrollX: number;
  scrollY: number;
  /** 可见 DOM 图片在视口中的归一化矩形，不含原图地址。 */
  imageCandidates?: Array<{ key?: string; x: number; y: number; width: number; height: number;
    fullX?: number; fullY?: number; fullWidth?: number; fullHeight?: number; priority?: number; kind?: "code" }>;
  /** 被每屏候选上限截断的数量；旧 screenshot-v1 默认为 0。 */
  imageCandidateOverflow: number;
}

export interface ScreenshotMeta {
  mode: "screen" | "region" | "longpage";
  sourceUrl: string;
  titleCandidate: string;
  capturedAt: string;
  dpr: number;
  viewport: { width: number; height: number };
  covered: { top: number; bottom: number };
  truncated: boolean;
  selection?: { left: number; right: number; top: number; bottom: number };
  warnings: string[];
  tileCount: number;
  tiles: ScreenshotTileMeta[];
  totalBytes: number;
}

export interface ReceivedScreenshotTile {
  meta: ScreenshotTileMeta;
  file: File;
}

export interface ScreenshotPayload {
  meta: ScreenshotMeta;
  tiles: ReceivedScreenshotTile[];
}

export type ScreenshotFailureReason =
  | "no_extension"
  | "not_authenticated"
  | "expired_or_replayed"
  | "origin_or_tab_mismatch"
  | "tile_missing"
  | "chunk_missing"
  | "size_limit"
  | "checksum_mismatch"
  | "signature_rejected"
  | "extension_error";

export interface ScreenshotFailure {
  reason: ScreenshotFailureReason;
  detail: string;
}

export type ScreenshotOutcome =
  | { status: "ok"; payload: ScreenshotPayload }
  | { status: "failed"; failure: ScreenshotFailure };

const GET_META = "blog.screenshot.get-meta";
const GET_TILE = "blog.screenshot.get-tile-chunk";
const ACK = "blog.screenshot.ack";
const CANCEL = "blog.screenshot.cancel";
const PROTOCOL_VERSION = 1;
const MAX_TILES = 30;
const MAX_TOTAL_BYTES = 20 * 1024 * 1024;
const MAX_CHUNK_BYTES = 64 * 1024;
const NONCE_PATTERN = /^[0-9a-f]{32}$/;
const EXTENSION_ID_PATTERN = /^[a-zA-Za-z0-9]{1,128}$/;
const MIME_WHITELIST = ["image/png", "image/jpeg", "image/webp"];

export function safeImageCandidates(value: unknown): NonNullable<ScreenshotTileMeta["imageCandidates"]> | null {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 60) return null;
  const candidates: NonNullable<ScreenshotTileMeta["imageCandidates"]> = [];
  for (const item of value) {
    if (!item || typeof item !== "object" || Array.isArray(item)) return null;
    const rect = item as Record<string, unknown>;
    const allowed = new Set(["key", "x", "y", "width", "height", "fullX", "fullY", "fullWidth", "fullHeight", "priority", "kind"]);
    if (Object.keys(rect).some((key) => !allowed.has(key))) return null;
    const { x, y, width, height } = rect;
    if (![x, y, width, height].every((number) => typeof number === "number" && Number.isFinite(number))) return null;
    const box = { x: x as number, y: y as number, width: width as number, height: height as number };
    if (box.x < 0 || box.x > 1 || box.y < 0 || box.y > 1 || box.width <= 0 || box.width > 1 || box.height <= 0 || box.height > 1 || box.x + box.width > 1.001 || box.y + box.height > 1.001) return null;
    if (rect.key !== undefined && (typeof rect.key !== "string" || !/^(?:code-)?\d{1,8}$/.test(rect.key))) return null;
    if (rect.kind !== undefined && rect.kind !== "code") return null;
    const fullFields = [rect.fullX, rect.fullY, rect.fullWidth, rect.fullHeight];
    const hasFull = fullFields.some((field) => field !== undefined);
    if (hasFull && (!fullFields.every((field) => typeof field === "number" && Number.isFinite(field)) ||
        (rect.fullX as number) < 0 || (rect.fullX as number) > 1 || (rect.fullY as number) < 0 || (rect.fullY as number) > 30_000 ||
        (rect.fullWidth as number) <= 0 || (rect.fullWidth as number) > 1 || (rect.fullHeight as number) <= 0 || (rect.fullHeight as number) > 30_000)) return null;
    if (rect.priority !== undefined && (!Number.isInteger(rect.priority) || (rect.priority as number) < 0 || (rect.priority as number) > 2)) return null;
    candidates.push({ ...box, ...(rect.key ? { key: rect.key as string } : {}),
      ...(rect.kind === "code" ? { kind: "code" as const } : {}),
      ...(hasFull ? { fullX: rect.fullX as number, fullY: rect.fullY as number,
        fullWidth: rect.fullWidth as number, fullHeight: rect.fullHeight as number } : {}),
      ...(rect.priority !== undefined ? { priority: rect.priority as number } : {}) });
  }
  return candidates;
}

export function safeImageCandidateOverflow(value: unknown): number | null {
  if (value === undefined) return 0;
  return Number.isInteger(value) && (value as number) >= 0 && (value as number) <= 10_000
    ? value as number
    : null;
}

function safeSelection(value: unknown): ScreenshotMeta["selection"] {
  if (!value || typeof value !== "object") return undefined;
  const { left, right, top, bottom } = value as Record<string, unknown>;
  if (![left, right, top, bottom].every((item) => typeof item === "number" && Number.isFinite(item)) ||
      (left as number) < 0 || (right as number) > 1 || (right as number) - (left as number) < 0.01 ||
      (top as number) < 0 || (bottom as number) <= (top as number) || (bottom as number) - (top as number) > 30_000) return undefined;
  return { left: left as number, right: right as number, top: top as number, bottom: bottom as number };
}

interface ChromeRuntimeLike {
  sendMessage(extensionId: string, message: unknown, callback: (response: unknown) => void): void;
  lastError?: { message?: string };
}

interface ShotMessage {
  ok?: boolean;
  meta?: Record<string, unknown>;
  tileIndex?: number;
  chunkIndex?: number;
  chunkCount?: number;
  chunk?: string;
  code?: string;
  detail?: string;
}

function chromeRuntime(): ChromeRuntimeLike | null {
  const runtime = (globalThis as unknown as { chrome?: { runtime?: ChromeRuntimeLike } }).chrome?.runtime;
  if (!runtime || typeof runtime.sendMessage !== "function") return null;
  return runtime;
}

export function readScreenshotFragment(hash: string): { nonce: string; extensionId: string } | null {
  const raw = String(hash ?? "").replace(/^#/, "");
  if (!raw) return null;
  const params = new URLSearchParams(raw);
  const nonce = params.get("shot") ?? "";
  const extensionId = params.get("ext") ?? "";
  const kind = params.get("kind") ?? "";
  if (kind !== "screenshot") return null;
  if (!NONCE_PATTERN.test(nonce)) return null;
  if (!EXTENSION_ID_PATTERN.test(extensionId)) return null;
  return { nonce, extensionId };
}

export function clearScreenshotFragment(): void {
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
    for (const key of [...url.searchParams.keys()]) {
      if (/^utm_|^spm$|^from$|^share$|^scene$/i.test(key)) url.searchParams.delete(key);
    }
    return url.toString();
  } catch {
    return "";
  }
}

function send(runtime: ChromeRuntimeLike, extensionId: string, message: unknown): Promise<ShotMessage> {
  return new Promise<ShotMessage>((resolve) => {
    let settled = false;
    const finish = (value: ShotMessage) => {
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
        finish((raw ?? {}) as ShotMessage);
      });
    } catch (cause) {
      clearTimeout(timer);
      finish({ ok: false, code: "extension_error", detail: cause instanceof Error ? cause.message : "扩展调用失败" });
    }
  });
}

function mapFailure(code: string | undefined, detail: string | undefined): ScreenshotFailure {
  switch (code) {
    case "expired":
    case "replayed":
    case "unknown_nonce":
      return { reason: "expired_or_replayed", detail: detail ?? "截图交接已失效，请从扩展重新发送" };
    case "origin_mismatch":
    case "tab_mismatch":
      return { reason: "origin_or_tab_mismatch", detail: detail ?? "交接目标不匹配，请从扩展重新发送" };
    case "tile_missing":
      return { reason: "tile_missing", detail: detail ?? "截图分片缺失，请重新发送" };
    case "chunk_missing":
      return { reason: "chunk_missing", detail: detail ?? "截图分块缺失，请重新发送" };
    case "size_mismatch":
    case "size_limit":
      return { reason: "size_limit", detail: detail ?? "截图大小与声明不符" };
    default:
      return { reason: "extension_error", detail: detail ?? "交接失败，请重新发送" };
  }
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function detectSignature(bytes: Uint8Array): "png" | "jpeg" | "webp" | null {
  if (bytes.length < 12) return null;
  if (bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47 &&
      bytes[4] === 0x0d && bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a) return "png";
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "jpeg";
  if (bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 &&
      bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50) return "webp";
  return null;
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes.slice().buffer as ArrayBuffer);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function extensionFromFileKind(kind: string): string {
  if (kind === "png") return ".png";
  if (kind === "jpeg") return ".jpg";
  return ".webp";
}

/** 消费一次性截图交接：取回每张视口截图与元数据（仅内存，不落库）。 */
export async function consumeScreenshotHandoff(nonce: string, extensionId: string): Promise<ScreenshotOutcome> {
  const runtime = chromeRuntime();
  if (!runtime) {
    return { status: "failed", failure: { reason: "no_extension", detail: "未检测到浏览器扩展，请从扩展重新发送。" } };
  }
  const metaResponse = await send(runtime, extensionId, { type: GET_META, version: PROTOCOL_VERSION, nonce });
  if (!metaResponse.ok || !metaResponse.meta) {
    return { status: "failed", failure: mapFailure(metaResponse.code, metaResponse.detail) };
  }
  const raw = metaResponse.meta;
  if (raw.kind !== "screenshot" || raw.version !== PROTOCOL_VERSION) {
    await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
    return { status: "failed", failure: { reason: "extension_error", detail: "截图交接协议版本不匹配，请更新扩展" } };
  }
  const tilesMeta = Array.isArray(raw.tiles) ? (raw.tiles as Record<string, unknown>[]) : [];
  const totalBytes = typeof raw.totalBytes === "number" ? raw.totalBytes : Number.NaN;
  if (!Array.isArray(tilesMeta) || tilesMeta.length < 1 || tilesMeta.length > MAX_TILES ||
      !Number.isInteger(totalBytes) || totalBytes < 1 || totalBytes > MAX_TOTAL_BYTES) {
    await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
    return { status: "failed", failure: { reason: "size_limit", detail: "截图分片数量或总大小异常" } };
  }
  if (raw.dpr !== undefined && (typeof raw.dpr !== "number" || !Number.isFinite(raw.dpr) || raw.dpr < 0.5 || raw.dpr > 4)) {
    await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
    return { status: "failed", failure: { reason: "extension_error", detail: "截图设备像素比异常" } };
  }
  const selection = safeSelection(raw.selection);
  if (raw.selection !== undefined && !selection) {
    await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
    return { status: "failed", failure: { reason: "extension_error", detail: "长截图选区信息异常，请从扩展重新截取" } };
  }
  const meta: ScreenshotMeta = {
    mode: raw.mode === "region" ? "region" : raw.mode === "longpage" ? "longpage" : "screen",
    sourceUrl: safeSourceUrl(raw.sourceUrl),
    titleCandidate: sanitizeText(raw.titleCandidate, 200),
    capturedAt: typeof raw.capturedAt === "string" ? raw.capturedAt : new Date().toISOString(),
    dpr: typeof raw.dpr === "number" && raw.dpr > 0 ? raw.dpr : 1,
    viewport: {
      width: Number((raw.viewport as { width?: number })?.width) || 0,
      height: Number((raw.viewport as { height?: number })?.height) || 0,
    },
    covered: {
      top: Number((raw.covered as { top?: number })?.top) || 0,
      bottom: Number((raw.covered as { bottom?: number })?.bottom) || 0,
    },
    truncated: Boolean(raw.truncated),
    selection,
    warnings: Array.isArray(raw.warnings)
      ? (raw.warnings as unknown[]).filter((item): item is string => typeof item === "string").slice(0, 10)
      : [],
    tileCount: tilesMeta.length,
    tiles: [],
    totalBytes,
  };

  let receivedTotal = 0;
  const tiles: ReceivedScreenshotTile[] = [];
  let imageCandidateOverflow = 0;
  for (let index = 0; index < tilesMeta.length; index += 1) {
    const tileRaw = tilesMeta[index];
    const candidates = tileRaw.imageCandidates === undefined ? [] : safeImageCandidates(tileRaw.imageCandidates);
    const candidateOverflow = safeImageCandidateOverflow(tileRaw.imageCandidateOverflow);
    if (!candidates) {
      await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
      return { status: "failed", failure: { reason: "extension_error", detail: "图片候选几何越界或字段异常，已拒绝此截图" } };
    }
    if (candidateOverflow === null) {
      await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
      return { status: "failed", failure: { reason: "extension_error", detail: "图片候选数量异常，已拒绝此截图" } };
    }
    imageCandidateOverflow += candidateOverflow;
    const tileMeta: ScreenshotTileMeta = {
      index: Number(tileRaw.index),
      mime: String(tileRaw.mime ?? ""),
      bytes: Number(tileRaw.bytes),
      sha256: String(tileRaw.sha256 ?? ""),
      width: Number(tileRaw.width) || 0,
      height: Number(tileRaw.height) || 0,
      scrollX: Number(tileRaw.scrollX) || 0,
      scrollY: Number(tileRaw.scrollY) || 0,
      imageCandidates: candidates,
      imageCandidateOverflow: candidateOverflow,
    };
    if (tileMeta.index !== index || !MIME_WHITELIST.includes(tileMeta.mime) ||
        !Number.isInteger(tileMeta.bytes) || tileMeta.bytes < 1 || tileMeta.bytes > MAX_TOTAL_BYTES ||
        !Number.isInteger(tileMeta.width) || tileMeta.width < 0 || tileMeta.width > 20_000 ||
        !Number.isInteger(tileMeta.height) || tileMeta.height < 0 || tileMeta.height > 20_000 ||
        !Number.isFinite(tileMeta.scrollX) || Math.abs(tileMeta.scrollX) > 30_000 ||
        !Number.isFinite(tileMeta.scrollY) || tileMeta.scrollY < 0 || tileMeta.scrollY > 30_000 ||
        !/^[0-9a-f]{64}$/.test(tileMeta.sha256)) {
      await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
      return { status: "failed", failure: { reason: "size_limit", detail: "截图分片元数据异常，请重新发送" } };
    }
    // 逐块拉取：先拿 chunkCount，再按序取完
    const first = await send(runtime, extensionId, {
      type: GET_TILE, version: PROTOCOL_VERSION, nonce, tileIndex: index, chunkIndex: 0,
    });
    if (!first.ok || typeof first.chunk !== "string") {
      await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
      return { status: "failed", failure: mapFailure(first.code ?? "tile_missing", first.detail) };
    }
    const chunkCount = typeof first.chunkCount === "number" ? first.chunkCount : 1;
    if (!Number.isInteger(chunkCount) || chunkCount < 1 ||
        chunkCount > Math.ceil(MAX_TOTAL_BYTES / MAX_CHUNK_BYTES) + 1) {
      await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
      return { status: "failed", failure: { reason: "chunk_missing", detail: "截图分块数量异常" } };
    }
    const base64Parts: string[] = [first.chunk];
    for (let chunkIndex = 1; chunkIndex < chunkCount; chunkIndex += 1) {
      const part = await send(runtime, extensionId, {
        type: GET_TILE, version: PROTOCOL_VERSION, nonce, tileIndex: index, chunkIndex,
      });
      if (!part.ok || typeof part.chunk !== "string" || part.chunkIndex !== chunkIndex) {
        await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
        return { status: "failed", failure: mapFailure(part.code ?? "chunk_missing", part.detail) };
      }
      base64Parts.push(part.chunk);
    }
    let bytes: Uint8Array;
    try {
      const binaryParts = base64Parts.map((part) => base64ToBytes(part));
      const total = binaryParts.reduce((sum, part) => sum + part.length, 0);
      if (total !== tileMeta.bytes) {
        await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
        return { status: "failed", failure: { reason: "size_limit", detail: "截图分片大小与声明不符，请重新发送" } };
      }
      const merged = new Uint8Array(total);
      let offset = 0;
      for (const part of binaryParts) {
        merged.set(part, offset);
        offset += part.length;
      }
      bytes = merged;
    } catch {
      await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
      return { status: "failed", failure: { reason: "extension_error", detail: "截图分片解码失败，请重新发送" } };
    }
    receivedTotal += bytes.byteLength;
    if (receivedTotal > MAX_TOTAL_BYTES || receivedTotal > totalBytes) {
      await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
      return { status: "failed", failure: { reason: "size_limit", detail: "截图总大小超过声明上限" } };
    }
    const digest = await sha256Hex(bytes);
    if (digest !== tileMeta.sha256) {
      await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
      return { status: "failed", failure: { reason: "checksum_mismatch", detail: `第 ${index + 1} 张截图校验失败，请从扩展重新发送` } };
    }
    const signature = detectSignature(bytes);
    if (!signature || (signature === "png" ? "image/png" : signature === "jpeg" ? "image/jpeg" : "image/webp") !== tileMeta.mime) {
      await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
      return { status: "failed", failure: { reason: "signature_rejected", detail: `第 ${index + 1} 张截图不是声明的 ${tileMeta.mime} 文件，已拒绝` } };
    }
    const file = new File([bytes.slice().buffer as ArrayBuffer], `tile-${index}${extensionFromFileKind(signature)}`, { type: tileMeta.mime });
    tiles.push({ meta: tileMeta, file });
  }
  if (imageCandidateOverflow > 0) {
    meta.warnings.unshift(`有 ${imageCandidateOverflow} 处网页图片候选超出每屏上限，仍可手动框选。`);
    meta.warnings = meta.warnings.slice(0, 10);
  }
  if (receivedTotal !== totalBytes) {
    await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
    return { status: "failed", failure: { reason: "size_limit", detail: "截图总大小与声明不符，请重新发送" } };
  }
  meta.tiles = tiles.map((tile) => tile.meta);

  const acknowledged = await send(runtime, extensionId, { type: ACK, version: PROTOCOL_VERSION, nonce });
  if (!acknowledged.ok) {
    return { status: "failed", failure: mapFailure(acknowledged.code, acknowledged.detail) };
  }
  return { status: "ok", payload: { meta, tiles } };
}

/** 用户取消时通知扩展清理暂存。 */
export async function cancelScreenshotHandoff(nonce: string, extensionId: string): Promise<void> {
  const runtime = chromeRuntime();
  if (!runtime) return;
  await send(runtime, extensionId, { type: CANCEL, version: PROTOCOL_VERSION, nonce });
}
