/**
 * v2 通用网页剪藏流程：popup 侧准备与 worker 侧分块消费。
 * DOM/BOM 通过 adapter 注入，便于 Node 单元测试驱动完整流程。
 */

import {
  MAX_PENDING_CLIPS,
  MAX_WEB_HTML_BYTES,
  WEB_ACK,
  WEB_CANCEL,
  WEB_GET_CHUNK,
  WEB_GET_META,
  WEB_KIND,
  WEB_PROTOCOL_VERSION,
  WEB_TARGETS,
  WebClipError,
  buildWebClipRecord,
  chunkUtf8,
  sanitizeWebSourceUrl,
  sha256Hex,
  utf8ByteLength,
  validateWebChunkIndex,
  validateWebRecordAccess,
  webClipMeta,
} from "./protocol.js";

export class WebClipFlowError extends Error {
  constructor(message, code) {
    super(message);
    this.name = "WebClipFlowError";
    this.code = code;
  }
}

function assertCaptureTarget(target) {
  if (!WEB_TARGETS.includes(target)) {
    throw new WebClipFlowError("请选择保存目标（私有笔记或博客草稿）", "bad_target");
  }
}

function assertOriginAllowed(origin, allowedOrigins) {
  if (!allowedOrigins.includes(origin)) {
    throw new WebClipFlowError("请选择允许的博客地址", "origin_not_allowed");
  }
}

async function removePending(api, nonce) {
  const pending = (await api.storage.get("webclip:pending")) ?? {};
  const ids = Array.isArray(pending["webclip:pending"]) ? pending["webclip:pending"] : [];
  await api.storage.set({ "webclip:pending": ids.filter((item) => item !== nonce) });
}

async function livePendingIds(api, now) {
  const pending = (await api.storage.get("webclip:pending")) ?? {};
  const ids = Array.isArray(pending["webclip:pending"]) ? pending["webclip:pending"] : [];
  const live = [];
  for (const id of ids) {
    if (typeof id !== "string" || !/^[0-9a-f]{32}$/.test(id)) continue;
    const key = `webclip:${id}`;
    const record = ((await api.storage.get(key)) ?? {})[key];
    if (record?.kind === WEB_KIND && !record.consumed && Number(record.expiresAt) > now) {
      live.push(id);
    } else {
      await api.storage.remove(key);
    }
  }
  if (live.length !== ids.length) await api.storage.set({ "webclip:pending": live });
  return live;
}

/**
 * popup 主流程：取浏览器提供的当前 tab → 用户点击后才抽取 → 暂存分块 → 开博客 tab。
 * 目标（私有笔记/博客草稿）只来自扩展 UI 的用户选择，不接受网页 DOM 指定。
 */
export async function prepareWebClip(api, input) {
  if (!input || typeof input !== "object") throw new WebClipFlowError("请求无效", "bad_input");
  const { targetOrigin, captureTarget = "private_note", ownNote = "" } = input;
  assertCaptureTarget(captureTarget);
  assertOriginAllowed(targetOrigin, api.allowedOrigins);

  if (utf8ByteLength(ownNote) > 16 * 1024) {
    throw new WebClipFlowError("附言不能超过 16 KiB", "note_too_large");
  }

  const activeTab = await api.getActiveTab();
  const tabId = activeTab?.id;
  const pageUrl = typeof activeTab?.url === "string" ? activeTab.url : "";
  if (!pageUrl || /^chrome-extension:\/\//.test(pageUrl)) {
    throw new WebClipFlowError("读不到当前标签页地址；请先在普通网页上点击扩展", "no_tab_url");
  }
  if (tabId == null) {
    throw new WebClipFlowError("读不到当前标签页；请刷新页面后重试", "no_tab");
  }

  const extraction = await api.extract(tabId, input.captureMode ?? "article");
  if (!extraction?.ok) {
    throw new WebClipFlowError(extraction?.detail ?? "抽取失败", extraction?.code ?? "extract_failed");
  }
  const sourceUrl = sanitizeWebSourceUrl(input.sourceUrl ?? pageUrl) || sanitizeWebSourceUrl(pageUrl);
  if (!sourceUrl) {
    throw new WebClipFlowError("来源链接不合法", "bad_source_url");
  }

  const now = Date.now();
  const pendingIds = await livePendingIds(api, now);
  if (pendingIds.length >= MAX_PENDING_CLIPS) {
    throw new WebClipFlowError(
      `已有 ${pendingIds.length} 条待接收剪藏；请先在博客里完成接收，或稍后再试`,
      "too_many_pending",
    );
  }

  const nonce = api.createNonce(16);
  const html = extraction.html;
  const record = buildWebClipRecord({
    nonce,
    sourceUrl,
    canonicalUrl: sanitizeWebSourceUrl(extraction.canonicalUrl) || sourceUrl,
    titleCandidate: String(input.titleCandidate ?? extraction.titleCandidate ?? "").slice(0, 200),
    siteCandidate: String(input.siteCandidate ?? extraction.siteCandidate ?? "").slice(0, 120),
    captureMode: input.captureMode ?? "article",
    captureTarget,
    targetOrigin,
    extractorVersion: extraction.extractorVersion ?? "webclip-extract-1",
    html,
    markdown: extraction.markdown ?? "",
    sha256: await sha256Hex(html),
    ownNote,
    warnings: extraction.warnings ?? [],
    createdAt: now,
    expiresAt: now + 5 * 60 * 1000,
    targetTabId: null,
  });

  await api.storage.set({ [`webclip:${nonce}`]: record });
  await api.storage.set({ "webclip:pending": [...pendingIds, nonce] });

  let blogTab;
  try {
    blogTab = await api.openTab(
      `${targetOrigin}/blog#clip=${nonce}&ext=${api.extensionId}&kind=${WEB_KIND}`,
    );
  } catch {
    await api.storage.remove(`webclip:${nonce}`);
    await api.storage.set({ "webclip:pending": pendingIds.filter((item) => item !== nonce) });
    throw new WebClipFlowError("无法打开博客页面，请检查博客是否在运行后重试", "tab_open_failed");
  }
  if (blogTab?.id != null) {
    const bound = { ...record, targetTabId: blogTab.id };
    await api.storage.set({ [`webclip:${nonce}`]: bound });
  }
  return { nonce, tabId: blogTab?.id ?? null, captureTarget };
}

/** worker 侧统一入口：get-meta / get-chunk / ack / cancel。 */
export async function handleWebClipMessage(api, message, sender, options = {}) {
  const validate = options.validate ?? validateWebRecordAccess;
  if (!message || typeof message !== "object") {
    return { ok: false, code: "bad_message", detail: "消息格式不正确" };
  }
  const nonce = typeof message.nonce === "string" ? message.nonce : "";
  if (!/^[0-9a-f]{32}$/.test(nonce)) {
    return { ok: false, code: "bad_nonce", detail: "剪藏凭据格式不正确" };
  }
  const key = `webclip:${nonce}`;
  const stored = (await api.storage.get(key)) ?? {};
  const record = stored[key] ?? null;
  const verdict = validate(message, record, sender, { now: options.now ? options.now() : Date.now() });
  if (!verdict.ok) {
    // 记录已过期/不存在时也清理，避免堆积
    if (record && verdict.code === "expired") await api.storage.remove(key);
    if (record && verdict.code === "expired") await removePending(api, nonce);
    return { ok: false, code: verdict.code, detail: verdict.detail };
  }
  const live = record.consumed ? null : verdict.record;
  if (!live) {
    return { ok: false, code: "replayed", detail: "该剪藏已接收过，请从扩展重新发送" };
  }
  if (!Number.isFinite(live.createdAt) || !Number.isFinite(live.expiresAt) ||
      typeof live.html !== "string" || !live.html) {
    return {
      ok: false,
      code: "bad_record",
      detail: "扩展暂存记录格式不完整；请在扩展管理页重新加载插件后重新剪藏",
    };
  }

  switch (message.type) {
    case WEB_GET_META:
      api.log?.("webclip meta", { nonce: nonce.slice(0, 6) });
      return { ok: true, meta: webClipMeta(live) };

    case WEB_GET_CHUNK: {
      const meta = webClipMeta(live);
      const indexCheck = validateWebChunkIndex(message.index, meta.chunkCount);
      if (!indexCheck.ok) {
        return { ok: false, code: indexCheck.code, detail: indexCheck.detail };
      }
      const { chunks } = chunkUtf8(live.html);
      return { ok: true, index: message.index, chunk: chunks[message.index] };
    }

    case WEB_ACK: {
      // 成功交接后立即清除正文，只保留不含内容的 tombstone 用于重放提示。
      const consumed = { ...live, html: "", markdown: "", ownNote: "", consumed: true };
      await api.storage.set({ [key]: consumed });
      await removePending(api, nonce);
      api.log?.("webclip ack", { nonce: nonce.slice(0, 6) });
      return { ok: true };
    }

    case WEB_CANCEL: {
      await api.storage.remove(key);
      await removePending(api, nonce);
      api.log?.("webclip cancel", { nonce: nonce.slice(0, 6) });
      return { ok: true };
    }

    default:
      return { ok: false, code: "wrong_type", detail: "不支持的消息类型" };
  }
}

export { MAX_WEB_HTML_BYTES, WEB_PROTOCOL_VERSION, WEB_KIND, WebClipError };
