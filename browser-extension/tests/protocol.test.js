/**
 * v2 通用网页剪藏协议单测：nonce、字节/分片工具、来源清洗、记录构建与消费校验。
 * 旧 v1 力扣剪藏协议已随“力扣导入”功能移除（2026-10-07）。
 */

import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import {
  DEFAULT_TARGET_ORIGINS,
  MAX_CHUNK_BYTES,
  MAX_WEB_HTML_BYTES,
  MAX_WEB_SOURCE_URL_CHARS,
  WEB_ACK,
  WEB_CANCEL,
  WEB_GET_CHUNK,
  WEB_GET_META,
  WEB_KIND,
  WEB_PROTOCOL_VERSION,
  WebClipError,
  buildWebClipRecord,
  chunkUtf8,
  createNonce,
  sanitizeWebSourceUrl,
  utf8ByteLength,
  validateWebChunkIndex,
  validateWebRecordAccess,
  webClipMeta,
} from "../shared/protocol.js";

const TARGET_ORIGIN = DEFAULT_TARGET_ORIGINS[0];
const randomBytes = (size) => new Uint8Array(webcrypto.getRandomValues(new Uint8Array(size)));

function webRecord(overrides = {}) {
  const html = "<article><h1>标题</h1><p>正文段落。</p></article>";
  return buildWebClipRecord({
    nonce: "c".repeat(32),
    sourceUrl: "https://example.test/post/1",
    titleCandidate: "示例标题",
    siteCandidate: "example.test",
    captureMode: "article",
    captureTarget: "private_note",
    targetOrigin: TARGET_ORIGIN,
    extractorVersion: "webclip-extract-1",
    html,
    createdAt: Date.now(),
    expiresAt: Date.now() + 5 * 60 * 1000,
    ...overrides,
  });
}

test("nonce：128-bit 随机、不可预测且格式稳定", () => {
  const seen = new Set();
  for (let i = 0; i < 50; i += 1) {
    const nonce = createNonce(randomBytes);
    assert.match(nonce, /^[0-9a-f]{32}$/);
    seen.add(nonce);
  }
  assert.equal(seen.size, 50);
  assert.throws(() => createNonce(() => null), WebClipError);
});

test("来源 URL 清洗：只留 http(s)，超长/控制字符返回空", () => {
  assert.equal(sanitizeWebSourceUrl("https://example.test/a?utm_source=x"), "https://example.test/a");
  assert.equal(sanitizeWebSourceUrl("javascript:alert(1)"), "");
  assert.equal(sanitizeWebSourceUrl("x".repeat(MAX_WEB_SOURCE_URL_CHARS + 1)), "");
});

test("字节统计与分片：中文按 UTF-8 计，分片边界正确", () => {
  assert.equal(utf8ByteLength("中"), 3);
  const payload = "x".repeat(MAX_CHUNK_BYTES + 10);
  const { chunks, totalBytes } = chunkUtf8(payload);
  assert.ok(chunks.length >= 2);
  assert.equal(chunks.join(""), payload);
  assert.equal(totalBytes, MAX_CHUNK_BYTES + 10);
});

test("web 记录：字段、TTL、大小上限", () => {
  const record = webRecord();
  assert.equal(record.kind, WEB_KIND);
  assert.equal(record.version, WEB_PROTOCOL_VERSION);
  assert.ok(record.expiresAt > record.createdAt);
  assert.equal(record.meta, undefined);
  assert.throws(
    () => webRecord({ html: "<p>" + "x".repeat(MAX_WEB_HTML_BYTES) + "</p>" }),
    WebClipError,
  );
  assert.throws(() => webRecord({ html: "" }), WebClipError);
});

test("web 消费校验：origin/路径/tab/nonce/过期/重放/类型", () => {
  const record = webRecord({ targetTabId: 7 });
  const now = record.expiresAt - 1000;
  const sender = { url: `${TARGET_ORIGIN}/blog`, tab: { id: 7 } };
  const message = { type: WEB_GET_META, version: WEB_PROTOCOL_VERSION, nonce: record.nonce };
  assert.equal(validateWebRecordAccess(message, record, sender, { now }).ok, true);

  const badOrigin = validateWebRecordAccess(
    message, record, { url: "https://evil.example/blog", tab: { id: 7 } }, { now });
  assert.equal(badOrigin.ok, false);

  const badPath = validateWebRecordAccess(
    message, record, { url: `${TARGET_ORIGIN}/other`, tab: { id: 7 } }, { now });
  assert.equal(badPath.ok, false);

  const badTab = validateWebRecordAccess(
    message, record, { url: `${TARGET_ORIGIN}/blog`, tab: { id: 8 } }, { now });
  assert.equal(badTab.ok, false);

  const expired = validateWebRecordAccess(
    message, record, sender, { now: record.expiresAt + 1000 });
  assert.equal(expired.ok, false);

  const replay = validateWebRecordAccess(
    message, { ...record, consumed: true }, sender, { now });
  assert.equal(replay.ok, false);

  // 消息类型路由由 background dispatch 负责，校验器只管版本/凭据/来源
  const wrongNonce = validateWebRecordAccess(
    { ...message, nonce: "d".repeat(32) }, record, sender, { now });
  assert.equal(wrongNonce.ok, false);
});

test("分片下标校验", () => {
  assert.equal(validateWebChunkIndex(0, 3).ok, true);
  assert.equal(validateWebChunkIndex(3, 3).ok, false);
});

test("元数据投影不包含原始 HTML", () => {
  const meta = webClipMeta(webRecord());
  const text = JSON.stringify(meta);
  assert.ok(!text.includes("<article>"));
  assert.equal(meta.titleCandidate, "示例标题");
  assert.equal(meta.captureTarget, "private_note");
});

test("消息类型常量与目标列表", () => {
  assert.equal(WEB_GET_META, "blog.webclip.get-meta");
  assert.equal(WEB_GET_CHUNK, "blog.webclip.get-chunk");
  assert.equal(WEB_ACK, "blog.webclip.ack");
  assert.equal(WEB_CANCEL, "blog.webclip.cancel");
  assert.ok(DEFAULT_TARGET_ORIGINS.includes(TARGET_ORIGIN));
});
