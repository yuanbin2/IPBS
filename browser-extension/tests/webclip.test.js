/**
 * B-043 v2 通用网页剪藏协议测试：来源 URL 清洗、UTF-8 分片、记录校验、
 * worker 分块消费一次性、缺片、并发与 ack 语义。
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  MAX_WEB_HTML_BYTES,
  WEB_KIND,
  WEB_PROTOCOL_VERSION,
  chunkUtf8,
  sanitizeWebSourceUrl,
  sha256Hex,
  buildWebClipRecord,
  validateWebRecordAccess,
  validateWebChunkIndex,
  webClipMeta,
} from "../shared/protocol.js";
import { handleWebClipMessage, WebClipFlowError, prepareWebClip } from "../shared/clip-flow.js";

const TARGET_ORIGIN = "http://127.0.0.1:5173";

test("v2 来源 URL 清洗", () => {
  assert.equal(sanitizeWebSourceUrl("https://example.org/post/1"), "https://example.org/post/1");
  assert.equal(sanitizeWebSourceUrl("http://example.org/a?utm_source=x"), "http://example.org/a");
  assert.equal(sanitizeWebSourceUrl("http://user:pass@example.org/x"), "");
  assert.equal(sanitizeWebSourceUrl("javascript:alert(1)"), "");
  assert.equal(sanitizeWebSourceUrl("ftp://example.org/x"), "");
  assert.equal(sanitizeWebSourceUrl(""), "");
  assert.equal(sanitizeWebSourceUrl("x".repeat(3000)), "");
  assert.equal(sanitizeWebSourceUrl("https://example.org/\u0000"), "");
});

test("v2 UTF-8 分片不截断多字节字符", () => {
  const text = "中".repeat(1000);
  const { chunks, totalBytes } = chunkUtf8(text, 64);
  assert.ok(chunks.length > 1);
  assert.equal(totalBytes, new TextEncoder().encode(text).length);
  assert.equal(chunks.join(""), text);
  for (const chunk of chunks) {
    assert.ok(new TextEncoder().encode(chunk).length <= 64);
  }
  const mixed = "a".repeat(63) + "😀" + "中" + "\ud800" + "尾";
  const mixedChunks = chunkUtf8(mixed, 64).chunks;
  assert.equal(mixedChunks.join(""), mixed);
  for (const chunk of mixedChunks) assert.ok(new TextEncoder().encode(chunk).length <= 64);
  assert.equal(MAX_WEB_HTML_BYTES, 2 * 1024 * 1024);
});

test("v2 元数据片数等于实际 UTF-8 分片数", () => {
  const html = `${"a".repeat(65535)}中${"a".repeat(65534)}`;
  assert.equal(new TextEncoder().encode(html).length, 2 * 65536);
  assert.equal(chunkUtf8(html).chunks.length, 3);
  const meta = webClipMeta({
    kind: WEB_KIND,
    version: WEB_PROTOCOL_VERSION,
    html,
    createdAt: Date.now(),
  });
  assert.equal(meta.chunkCount, 3);
  assert.equal(meta.htmlUtf8Bytes, 2 * 65536);
});

test("v2 记录访问校验：origin/端口/路径/tab/过期/重放/版本", () => {
  const now = 1_700_000_000_000;
  const record = buildWebClipRecord({
    nonce: "a".repeat(32),
    sourceUrl: "https://example.org/post",
    canonicalUrl: "https://example.org/post",
    titleCandidate: "标题",
    siteCandidate: "example.org",
    captureMode: "article",
    captureTarget: "private_note",
    targetOrigin: TARGET_ORIGIN,
    extractorVersion: "webclip-extract-1",
    html: "<p>hello</p>",
    markdown: "hello",
    warnings: [],
    createdAt: now,
    expiresAt: now + 300_000,
    targetTabId: 42,
  });
  const sender = { url: "http://127.0.0.1:5173/blog", tab: { id: 42 } };
  const message = { type: "blog.webclip.get-meta", version: 2, nonce: "a".repeat(32) };
  assert.equal(validateWebRecordAccess(message, record, sender, { now }).ok, true);
  assert.equal(validateWebRecordAccess(message, record, { ...sender, url: "http://127.0.0.1:5174/blog" }, { now }).code, "origin_mismatch");
  assert.equal(validateWebRecordAccess(message, record, { ...sender, url: "https://127.0.0.1:5173/blog" }, { now }).code, "origin_mismatch");
  assert.equal(validateWebRecordAccess(message, record, { ...sender, url: "http://127.0.0.1:5173/other" }, { now }).code, "origin_mismatch");
  assert.equal(validateWebRecordAccess(message, record, { ...sender, tab: { id: 7 } }, { now }).code, "tab_mismatch");
  assert.equal(validateWebRecordAccess(message, record, sender, { now: now + 300_001 }).code, "expired");
  assert.equal(validateWebRecordAccess(message, { ...record, consumed: true }, sender, { now }).code, "replayed");
  assert.equal(validateWebRecordAccess({ ...message, version: 1 }, record, sender, { now }).code, "bad_version");
  assert.equal(validateWebRecordAccess(message, null, sender, { now }).code, "unknown_nonce");
  assert.equal(validateWebChunkIndex(-1, 2).code, "chunk_missing");
  assert.equal(validateWebChunkIndex(2, 2).code, "chunk_missing");
  assert.equal(validateWebChunkIndex(1, 2).ok, true);

  const meta = webClipMeta(record);
  assert.equal(meta.kind, WEB_KIND);
  assert.equal(meta.version, WEB_PROTOCOL_VERSION);
  assert.equal(meta.html, undefined);
  assert.equal(meta.markdown, undefined);
  assert.equal(meta.chunkCount, 1);
  assert.equal(meta.htmlUtf8Bytes, 12);
  assert.equal(meta.captureTarget, "private_note");
});

function makeStore(record, nonce) {
  const store = new Map();
  const pending = new Map([["webclip:pending", [nonce]]]);
  return {
    store,
    api: {
      storage: {
        get: async (key) => (store.has(key) ? { [key]: store.get(key) } : pending.has(key) ? { [key]: pending.get(key) } : {}),
        set: async (...args) => {
          assert.equal(args.length, 1, "chrome.storage.set 只接受一个对象参数");
          assert.equal(typeof args[0], "object");
          for (const [key, value] of Object.entries(args[0])) {
            if (key === "webclip:pending") pending.set(key, value);
            else store.set(key, value);
          }
        },
        remove: async (key) => {
          store.delete(key);
        },
      },
    },
  };
}

test("v2 worker 分块消费：拼装、验字节、ack 后清除正文且不再供片", async () => {
  const now = 1_700_000_000_000;
  const nonce = "b".repeat(32);
  const html = `<p>${"x".repeat(200_000)}</p>`;
  const { api, store } = makeStore(null, nonce);
  await api.storage.set({ [`webclip:${nonce}`]: buildWebClipRecord({
    nonce,
    sourceUrl: "https://example.org/big",
    canonicalUrl: "https://example.org/big",
    titleCandidate: "大页",
    captureMode: "article",
    captureTarget: "private_note",
    targetOrigin: TARGET_ORIGIN,
    extractorVersion: "webclip-extract-1",
    html,
    markdown: "x",
    warnings: [{ code: "IMAGE_REMOTE", count: 2 }],
    createdAt: now,
    expiresAt: now + 300_000,
    targetTabId: 9,
  }) });
  const sender = { url: TARGET_ORIGIN + "/blog", tab: { id: 9 } };

  const meta = await handleWebClipMessage(api, { type: "blog.webclip.get-meta", version: 2, nonce }, sender, { now: () => now });
  assert.equal(meta.ok, true);
  assert.equal(meta.meta.htmlUtf8Bytes, new TextEncoder().encode(html).length);

  let assembled = "";
  for (let index = 0; index < meta.meta.chunkCount; index += 1) {
    const part = await handleWebClipMessage(api, { type: "blog.webclip.get-chunk", version: 2, nonce, index }, sender, { now: () => now });
    assert.equal(part.ok, true);
    assert.equal(part.index, index);
    assembled += part.chunk;
  }
  assert.equal(assembled, html);
  assert.equal(chunkUtf8(html).chunks.length, meta.meta.chunkCount);

  const missing = await handleWebClipMessage(api, { type: "blog.webclip.get-chunk", version: 2, nonce, index: 99 }, sender, { now: () => now });
  assert.equal(missing.code, "chunk_missing");

  const ack = await handleWebClipMessage(api, { type: "blog.webclip.ack", version: 2, nonce }, sender, { now: () => now });
  assert.equal(ack.ok, true);
  assert.equal(store.get(`webclip:${nonce}`).html, "");
  assert.equal(store.get(`webclip:${nonce}`).markdown, "");
  const afterAck = await handleWebClipMessage(api, { type: "blog.webclip.get-chunk", version: 2, nonce, index: 0 }, sender, { now: () => now });
  assert.equal(afterAck.code, "replayed");
  const metaAfter = await handleWebClipMessage(api, { type: "blog.webclip.get-meta", version: 2, nonce }, sender, { now: () => now });
  assert.equal(metaAfter.code, "replayed");
  // 已消费：未知类型也安全失败（先判重放，不泄露任何数据）
  const wrongType = await handleWebClipMessage(api, { type: "blog.webclip.anything", version: 2, nonce }, sender, { now: () => now });
  assert.equal(wrongType.code, "replayed");
  // 未消费记录上的未知类型才返回 wrong_type
  const other = await handleWebClipMessage(api, { type: "blog.webclip.anything", version: 2, nonce: "e".repeat(32) }, sender, { now: () => now });
  assert.equal(other.code, "unknown_nonce");
  const badNonce = await handleWebClipMessage(api, { type: "blog.webclip.get-meta", version: 2, nonce: "drop table" }, sender, { now: () => now });
  assert.equal(badNonce.code, "bad_nonce");
});

test("v2 worker 并发消费只成功一次", async () => {
  const now = 1_700_000_000_000;
  const nonce = "c".repeat(32);
  const { api } = makeStore(null, nonce);
  await api.storage.set({ [`webclip:${nonce}`]: buildWebClipRecord({
    nonce,
    sourceUrl: "https://example.org/p",
    canonicalUrl: "https://example.org/p",
    titleCandidate: "t",
    captureMode: "selection",
    captureTarget: "article_draft",
    targetOrigin: "http://127.0.0.1:5174",
    extractorVersion: "webclip-extract-1",
    html: "<p>secret</p>",
    markdown: "secret",
    warnings: [],
    createdAt: now,
    expiresAt: now + 300_000,
    targetTabId: 3,
  }) });
  const sender = { url: "http://127.0.0.1:5174/blog", tab: { id: 3 } };
  const results = await Promise.all([
    handleWebClipMessage(api, { type: "blog.webclip.get-chunk", version: 2, nonce, index: 0 }, sender, { now: () => now }),
    handleWebClipMessage(api, { type: "blog.webclip.ack", version: 2, nonce }, sender, { now: () => now }),
  ]);
  assert.equal(results.filter((item) => item.ok).length, 2);
  const again = await handleWebClipMessage(api, { type: "blog.webclip.get-chunk", version: 2, nonce, index: 0 }, sender, { now: () => now });
  assert.equal(again.code, "replayed");
});

test("v2 worker 对旧版不完整暂存返回可操作错误", async () => {
  const nonce = "f".repeat(32);
  const now = Date.now();
  const { api } = makeStore(null, nonce);
  await api.storage.set({ [`webclip:${nonce}`]: {
    kind: WEB_KIND,
    version: WEB_PROTOCOL_VERSION,
    nonce,
    targetOrigin: TARGET_ORIGIN,
    targetTabId: 9,
    expiresAt: now + 60_000,
    html: "<p>旧记录</p>",
  } });
  const response = await handleWebClipMessage(api, {
    type: "blog.webclip.get-meta", version: WEB_PROTOCOL_VERSION, nonce,
  }, { url: `${TARGET_ORIGIN}/blog`, tab: { id: 9 } }, { now: () => now });
  assert.equal(response.code, "bad_record");
  assert.match(response.detail, /重新加载插件/);
});

test("v2 cancel 清理暂存与 pending 列表", async () => {
  const now = 1_700_000_000_000;
  const nonce = "d".repeat(32);
  const { api, store } = makeStore(null, nonce);
  await api.storage.set({ [`webclip:${nonce}`]: buildWebClipRecord({
    nonce,
    sourceUrl: "https://example.org/c",
    canonicalUrl: "https://example.org/c",
    titleCandidate: "t",
    captureMode: "article",
    captureTarget: "private_note",
    targetOrigin: TARGET_ORIGIN,
    extractorVersion: "webclip-extract-1",
    html: "<p>c</p>",
    markdown: "c",
    warnings: [],
    createdAt: now,
    expiresAt: now + 300_000,
    targetTabId: 4,
  }) });
  const sender = { url: "http://127.0.0.1:5173/blog", tab: { id: 4 } };
  const cancel = await handleWebClipMessage(api, { type: "blog.webclip.cancel", version: 2, nonce }, sender, { now: () => now });
  assert.equal(cancel.ok, true);
  assert.equal(store.has(`webclip:${nonce}`), false);
});

test("v2 popup 流程：目标只来自 UI、超限拒绝、失败清理", async () => {
  const store = new Map();
  const pending = new Map([["webclip:pending", []]]);
  const opened = [];
  const baseApi = {
    extensionId: "ext-id",
    allowedOrigins: [TARGET_ORIGIN, "http://127.0.0.1:8001"],
    getActiveTab: async () => ({ id: 7, url: "https://example.org/article" }),
    extract: async () => ({
      ok: true,
      html: "<p>正文</p>",
      markdown: "正文",
      warnings: [{ code: "IMAGE_REMOTE", count: 1 }],
      titleCandidate: "示例文章",
      siteCandidate: "example.org",
      canonicalUrl: "https://example.org/article",
      extractorVersion: "webclip-extract-1",
      htmlBytes: 12,
    }),
    createNonce: (size) => "a".repeat(size * 2),
    storage: {
      set: async (...args) => {
        assert.equal(args.length, 1, "chrome.storage.set 只接受一个对象参数");
        assert.equal(typeof args[0], "object");
        for (const [key, value] of Object.entries(args[0])) {
          if (key === "webclip:pending") pending.set(key, value);
          else store.set(key, value);
        }
      },
      remove: async (key) => void store.delete(key),
      get: async (key) => (store.has(key) ? { [key]: store.get(key) } : pending.has(key) ? { [key]: pending.get(key) } : {}),
    },
    openTab: async (url) => {
      opened.push(url);
      return { id: 99 };
    },
  };

  // 默认私有笔记
  const result = await prepareWebClip(baseApi, { targetOrigin: TARGET_ORIGIN, ownNote: "我的来源说明" });
  assert.equal(result.tabId, 99);
  assert.match(opened[0], new RegExp(`^${TARGET_ORIGIN.replace(/[.]/g, "\\.")}/blog#clip=[0-9a-f]{32}&ext=ext-id&kind=web$`));
  assert.equal(opened[0].includes("example.org/article"), false);
  assert.equal(opened[0].includes("%3C"), false);
  const [key, record] = [...store.entries()][0];
  assert.equal(key, `webclip:${result.nonce}`);
  assert.equal(record.captureTarget, "private_note");
  assert.equal(record.targetTabId, 99);
  assert.equal(record.kind, WEB_KIND);
  assert.match(record.sha256, /^[0-9a-f]{64}$/);
  assert.equal(record.sha256, await sha256Hex(record.html));
  assert.equal(webClipMeta(record).ownNote, "我的来源说明");
  // 目标不允许时拒绝（不由网页 DOM 指定）
  await assert.rejects(() => prepareWebClip(baseApi, { targetOrigin: TARGET_ORIGIN, captureTarget: "evil_target" }), /保存目标/);
  await assert.rejects(() => prepareWebClip(baseApi, { targetOrigin: "http://evil.example" }), /允许的博客地址/);
  // 读不到 tab URL 时拒绝
  await assert.rejects(
    () => prepareWebClip({ ...baseApi, getActiveTab: async () => ({ id: 1, url: "chrome-extension://x/y" }) }, { targetOrigin: TARGET_ORIGIN }),
    /普通网页/,
  );
  // 抽取失败不暂存不开 tab
  const before = store.size;
  await assert.rejects(
    () => prepareWebClip({ ...baseApi, extract: async () => ({ ok: false, code: "extract_empty", detail: "空页面" }) }, { targetOrigin: TARGET_ORIGIN }),
    /空页面/,
  );
  assert.equal(store.size, before);

  // 待消费达到上限后拒绝
  const liveIds = ["1".repeat(32), "2".repeat(32)];
  for (const id of liveIds) {
    store.set(`webclip:${id}`, { kind: WEB_KIND, consumed: false, expiresAt: Date.now() + 60_000 });
  }
  pending.set("webclip:pending", liveIds);
  await assert.rejects(() => prepareWebClip(baseApi, { targetOrigin: TARGET_ORIGIN }), /待接收剪藏/);

  // 已过期的 pending 不应永久堵住后续剪藏。
  for (const id of liveIds) store.set(`webclip:${id}`, { kind: WEB_KIND, consumed: false, expiresAt: Date.now() - 1 });
  await prepareWebClip({ ...baseApi, createNonce: () => "e".repeat(32) }, { targetOrigin: TARGET_ORIGIN });
  assert.deepEqual(pending.get("webclip:pending"), ["e".repeat(32)]);

  // tab 打开失败时清理暂存
  pending.set("webclip:pending", []);
  store.clear();
  await assert.rejects(
    () => prepareWebClip({ ...baseApi, createNonce: () => "f".repeat(32), openTab: async () => { throw new Error("blocked"); } }, { targetOrigin: TARGET_ORIGIN }),
    /无法打开博客/,
  );
  assert.equal(store.size, 0);
  void WebClipFlowError;
});
