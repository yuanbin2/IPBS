/**
 * B-045 screenshot-v1 单元测试：采集计划、tile 元数据/总量限制、
 * base64 分片完整性、签名校验、TTL/重放/并发双消费、origin/tab 不匹配与清理。
 * 运行：node --test browser-extension/tests/
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  MAX_SHOT_TILES,
  MAX_SHOT_TOTAL_BYTES,
  SHOT_CHUNK_BYTES,
  ShotProtocolError,
  assembleTileFromBase64,
  base64ToBytes,
  buildShotRecord,
  buildShotTileMeta,
  bytesToBase64,
  chunkCountFor,
  chunkTileToBase64,
  detectTileSignature,
  normalizeImageCandidates,
  nextManualShotY,
  planLongPageCapture,
  readScreenshotFragmentParams,
  sameShotPageLocation,
  shotMeta,
  tileChunkBase64,
  validateShotRecordAccess,
  validateShotTileIndex,
} from "../shared/shot-protocol.js";
import { dropPendingShots, handleScreenshotMessage, purgeExpiredShots, saveScreenshotSession } from "../shared/screenshot-flow.js";

const TARGET_ORIGIN = "http://127.0.0.1:5174";

function fakeNonce() {
  // saveScreenshotSession 期望 createNonce(size) 直接返回 32 位十六进制字符串
  return (size) => "c7".repeat(size);
}

function pngBytes(size = 64) {
  const bytes = new Uint8Array(size);
  bytes[0] = 0x89; bytes[1] = 0x50; bytes[2] = 0x4e; bytes[3] = 0x47;
  bytes[4] = 0x0d; bytes[5] = 0x0a; bytes[6] = 0x1a; bytes[7] = 0x0a;
  return bytes;
}

async function sha256Hex(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/* ---------------- 采集计划 ---------------- */

test("长页计划：85% 步进重叠、覆盖终点", () => {
  const plan = planLongPageCapture({ viewportHeight: 800, startY: 0, endY: 800 * 3 });
  assert.equal(plan.tiles.length, 4); // 0, 680, 1360, 1600(=2400-800)
  assert.equal(plan.coveredBottom, 2400);
  assert.equal(plan.truncated, false);
  const ys = plan.tiles.map((tile) => tile.scrollY);
  assert.deepEqual(ys, [0, 680, 1360, 1600]);
});

test("长页计划：超出 30000px 或 30 张即截断", () => {
  const tall = planLongPageCapture({ viewportHeight: 800, startY: 0, endY: 8_000_000 });
  assert.equal(tall.truncated, true);
  const many = planLongPageCapture({ viewportHeight: 100, startY: 0, endY: 12_000 });
  assert.equal(many.truncated, true);
  assert.ok(many.tiles.length <= MAX_SHOT_TILES);
  assert.equal(many.coveredBottom, many.tiles.at(-1).scrollY + 100);
  assert.ok(many.coveredBottom < 12_000, "不能把未截取的末尾报成已覆盖");
  const short = planLongPageCapture({ viewportHeight: 800, startY: 500, endY: 700 });
  assert.equal(short.coveredTop, short.tiles[0].scrollY);
  assert.equal(short.coveredBottom, short.tiles[0].scrollY + 800);
});

test("手动快滚按 85% 视口补齐至用户停下的位置，不会遗漏中间屏", () => {
  const viewport = 800;
  const ys = [200];
  const desiredY = 4900;
  while (true) {
    const next = nextManualShotY(ys.at(-1), desiredY, viewport, 200);
    if (next == null) break;
    assert.ok(next > ys.at(-1));
    assert.ok(next - ys.at(-1) <= viewport * 0.85);
    ys.push(next);
  }
  assert.equal(ys.at(-1), desiredY);
  assert.equal(nextManualShotY(desiredY, desiredY, viewport, 200), null);
  // 高度上限：startY=200、viewport=800 时 maxY = 200 + 30000 - 800 = 29400，
  // 用户想越过上限继续滚（desiredY=30000）→ 停在 null。
  assert.equal(nextManualShotY(29_400, 30_000, viewport, 200), null);
  assert.throws(() => nextManualShotY(0, Number.NaN, viewport, 0), ShotProtocolError);
});

test("可见配图候选只保留有限归一化矩形，不交接原图 URL", () => {
  const candidates = normalizeImageCandidates([
    { key: "7", x: 0.1, y: 0.2, width: 0.4, height: 0.3, src: "https://private.example/image" },
    { x: -1, y: 0, width: 0.2, height: 0.2 },
    { x: 0, y: 0, width: Number.POSITIVE_INFINITY, height: 0.2 },
  ]);
  assert.deepEqual(candidates, [{ key: "7", x: 0.1, y: 0.2, width: 0.4, height: 0.3 }]);
});

test("跨屏图片几何在协议内保留，越界几何与非白名单字段被剔除", () => {
  const normalized = normalizeImageCandidates([
    { key: "12", x: 0.1, y: 0.98, width: 0.4, height: 0.02,
      fullX: 0.1, fullY: 420, fullWidth: 0.4, fullHeight: 260, priority: 1 },
    { x: 0, y: 0, width: 1, height: 0.01, fullY: 24_001, fullHeight: 400 },
  ]);
  assert.equal(normalized.length, 1);
  assert.deepEqual(normalized[0], { key: "12", x: 0.1, y: 0.98, width: 0.4, height: 0.02,
    fullX: 0.1, fullY: 420, fullWidth: 0.4, fullHeight: 260, priority: 1 });
});

test("代码块候选保留 kind 与 code- 前缀 key，非法 kind 被剔除", () => {
  const normalized = normalizeImageCandidates([
    { key: "code-3", x: 0.1, y: 0.2, width: 0.5, height: 0.2, fullX: 0.1, fullY: 300,
      fullWidth: 0.5, fullHeight: 200, priority: 2, kind: "code" },
    { x: 0, y: 0, width: 0.2, height: 0.2, kind: "video" },
  ]);
  assert.equal(normalized.length, 1);
  assert.deepEqual(normalized[0], { key: "code-3", x: 0.1, y: 0.2, width: 0.5, height: 0.2,
    fullX: 0.1, fullY: 300, fullWidth: 0.5, fullHeight: 200, priority: 2, kind: "code" });
});

test("长页计划：非法范围拒绝", () => {
  assert.throws(() => planLongPageCapture({ viewportHeight: 800, startY: 500, endY: 100 }), ShotProtocolError);
  assert.throws(() => planLongPageCapture({ viewportHeight: 10, startY: 0, endY: 100 }), ShotProtocolError);
});

test("长图选择范围随元数据传递，拒绝越界宽度", async () => {
  const bytes = pngBytes();
  const sha256 = await sha256Hex(bytes);
  const base = {
    nonce: "b".repeat(32), mode: "longpage", sourceUrl: "https://example.com/article",
    capturedAt: Date.now(), dpr: 1, viewportWidth: 1000, viewportHeight: 800,
    coveredTop: 100, coveredBottom: 900, targetOrigin: TARGET_ORIGIN,
    createdAt: Date.now(), expiresAt: Date.now() + 60_000,
    tiles: [{ ...buildShotTileMeta({ index: 0, mime: "image/png", bytes, sha256, width: 1000, height: 800 }),
      imageCandidateOverflow: 3 }],
  };
  const selection = { left: 0.15, right: 0.85, top: 120, bottom: 880 };
  const record = buildShotRecord({ ...base, selection });
  assert.deepEqual(shotMeta(record).selection, selection);
  assert.equal(shotMeta(record).tiles[0].imageCandidateOverflow, 3);
  assert.throws(() => buildShotRecord({ ...base, selection: { ...selection, right: 1.2 } }), ShotProtocolError);
});

/* ---------------- tile 元数据与总量 ---------------- */

test("tile 元数据：MIME 白名单与哈希必填", async () => {
  const bytes = pngBytes();
  const sha = await sha256Hex(bytes);
  const meta = buildShotTileMeta({ index: 0, mime: "image/png", bytes, sha256: sha, width: 100, height: 50 });
  assert.equal(meta.bytes, 64);
  assert.throws(() => buildShotTileMeta({ index: 0, mime: "image/svg+xml", bytes, sha256: sha }), ShotProtocolError);
  assert.throws(() => buildShotTileMeta({ index: 0, mime: "image/png", bytes, sha256: "deadbeef" }), ShotProtocolError);
  assert.throws(
    () => buildShotTileMeta({ index: MAX_SHOT_TILES, mime: "image/png", bytes, sha256: sha }),
    ShotProtocolError,
  );
});

test("会话记录：总量 20MiB 上限与空 tile 拒绝", () => {
  const tileMeta = { index: 0, mime: "image/png", bytes: MAX_SHOT_TOTAL_BYTES + 1, sha256: "a".repeat(64), width: 1, height: 1 };
  assert.throws(
    () => buildShotRecord({ nonce: "1".repeat(32), tiles: [tileMeta], createdAt: 1, expiresAt: 2, targetOrigin: TARGET_ORIGIN }),
    ShotProtocolError,
  );
  assert.throws(
    () => buildShotRecord({ nonce: "1".repeat(32), tiles: [], createdAt: 1, expiresAt: 2, targetOrigin: TARGET_ORIGIN }),
    ShotProtocolError,
  );
});

/* ---------------- base64 分片完整性 ---------------- */

test("base64 分片：多字节边界无损、可重组、可验大小", async () => {
  // getRandomValues 单次上限 64KiB
  const bytes = pngBytes(65_000);
  crypto.getRandomValues(bytes);
  const { chunks, totalBytes } = chunkTileToBase64(bytes);
  assert.equal(totalBytes, bytes.byteLength);
  assert.equal(chunkCountFor(bytes), chunks.length);
  const reassembled = assembleTileFromBase64(chunks, bytes.byteLength);
  assert.deepEqual(Buffer.from(reassembled), Buffer.from(bytes));
  assert.throws(() => assembleTileFromBase64(chunks, bytes.byteLength - 1), ShotProtocolError);
  const roundTrip = base64ToBytes(bytesToBase64(bytes));
  assert.deepEqual(Buffer.from(roundTrip), Buffer.from(bytes));
  const last = tileChunkBase64(bytes, chunks.length - 1);
  assert.equal(last.chunkCount, chunks.length);
  assert.equal(last.chunk, chunks.at(-1));
  assert.throws(() => tileChunkBase64(bytes, chunks.length), ShotProtocolError);
});

test("图片签名：PNG/JPEG/WebP 通过，HTML/SVG 冒充拒绝", () => {
  assert.equal(detectTileSignature(pngBytes()), "png");
  const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0, 0, 0, 0]);
  assert.equal(detectTileSignature(jpeg), "jpeg");
  const html = new TextEncoder().encode("<html><script>1</script></html>");
  assert.equal(detectTileSignature(html), null);
});

test("fragment 只接受合法 nonce/扩展 ID/kind", () => {
  assert.deepEqual(readScreenshotFragmentParams("#shot=" + "a".repeat(32) + "&ext=abc&kind=screenshot"), {
    nonce: "a".repeat(32),
    extensionId: "abc",
  });
  assert.equal(readScreenshotFragmentParams("#clip=xxx&ext=abc&kind=web"), null);
  assert.equal(readScreenshotFragmentParams("#shot=short&ext=abc&kind=screenshot"), null);
});

/* ---------------- worker 消费：TTL/重放/双消费/origin/tab ---------------- */

function makeApi() {
  const sessionData = new Map();
  const tileData = new Map();
  const claims = new Set();
  return {
    extensionId: "testext",
    allowedOrigins: [TARGET_ORIGIN],
    createNonce: fakeNonce(),
    claimNonce: (key) => { if (claims.has(key)) return false; claims.add(key); return true; },
    releaseNonce: (key) => claims.delete(key),
    storage: {
      async get(key) {
        return sessionData.has(key) ? { [key]: sessionData.get(key) } : {};
      },
      async set(obj) {
        for (const [key, value] of Object.entries(obj)) sessionData.set(key, value);
      },
      async remove(key) {
        sessionData.delete(key);
      },
      dump: sessionData,
    },
    tileStore: {
      async put(nonce, index, bytes) { tileData.set(`${nonce}:${index}`, bytes); },
      async get(nonce, index) { return tileData.get(`${nonce}:${index}`) ?? null; },
      async deleteNonce(nonce) {
        for (const key of [...tileData.keys()]) if (key.startsWith(`${nonce}:`)) tileData.delete(key);
      },
      dump: tileData,
    },
    openTab: async () => ({ id: 4321, url: "about:blank" }),
    activateTab: async (tab, url) => {
      const record = [...sessionData.values()].find((item) => item?.kind === "screenshot" && !item.consumed);
      assert.equal(record?.targetTabId, tab.id, "导航前必须先绑定目标标签页");
      tab.url = url;
    },
    log: () => undefined,
  };
}

async function prepareSession(api, { mode = "screen" } = {}) {
  return saveScreenshotSession(api, {
    targetOrigin: TARGET_ORIGIN,
    mode,
    sourceUrl: "https://example.com/article?utm_source=x",
    titleCandidate: "示例文章",
    dpr: 1.25,
    viewportWidth: 1280,
    viewportHeight: 800,
    coveredTop: 100,
    coveredBottom: 900,
    truncated: false,
    warnings: [],
    tiles: [{ bytes: pngBytes(3000), mime: "image/png", width: 1600, height: 1000, scrollX: 0, scrollY: 100,
      imageCandidates: [{ x: 0.1, y: 0.2, width: 0.4, height: 0.3, src: "https://private.example/image" }] }],
  });
}

function senderOf(tabId = 4321, path = "/blog") {
  return { url: `${TARGET_ORIGIN}${path}`, tab: { id: tabId } };
}

test("保存会话：元数据入 session、字节入 IndexedDB、fragment 无图片", async () => {
  const api = makeApi();
  const { nonce } = await prepareSession(api);
  const record = api.storage.dump.get(`shot:${nonce}`);
  assert.equal(record.kind, "screenshot");
  assert.equal(record.sourceUrl.includes("utm_source"), false);
  assert.deepEqual(record.tiles[0].imageCandidates, [{ x: 0.1, y: 0.2, width: 0.4, height: 0.3 }]);
  assert.equal(api.tileStore.dump.has(`${nonce}:0`), true);
  const serialized = JSON.stringify(record);
  assert.ok(!serialized.includes("iVBOR"), "storage.session 不得包含图片字节");
});

test("第二张截图暂存失败时清理第一张，不留下私有图片孤儿", async () => {
  const api = makeApi();
  const originalPut = api.tileStore.put;
  api.tileStore.put = async (nonce, index, bytes) => {
    if (index === 1) throw new Error("quota exceeded");
    await originalPut(nonce, index, bytes);
  };
  await assert.rejects(() => saveScreenshotSession(api, {
    targetOrigin: TARGET_ORIGIN,
    mode: "longpage",
    tiles: [0, 1].map(() => ({ bytes: pngBytes(3000), mime: "image/png", width: 100, height: 50 })),
  }), (error) => error.code === "storage_failed");
  assert.equal(api.tileStore.dump.size, 0);
  assert.deepEqual(api.storage.dump.get("shot:pending"), []);
});

test("get-meta → get-tile-chunk → ack 后原子清理", async () => {
  const api = makeApi();
  const { nonce } = await prepareSession(api);
  const metaResponse = await handleScreenshotMessage(api, { type: "blog.screenshot.get-meta", version: 1, nonce }, senderOf());
  assert.equal(metaResponse.ok, true);
  assert.equal(metaResponse.meta.tileCount, 1);
  assert.equal(metaResponse.meta.tiles[0].bytes, 3000);
  assert.equal(metaResponse.meta.sourceUrl.includes("utm_source"), false);

  const chunk = await handleScreenshotMessage(
    api, { type: "blog.screenshot.get-tile-chunk", version: 1, nonce, tileIndex: 0, chunkIndex: 0 }, senderOf(),
  );
  assert.equal(chunk.ok, true);
  const reassembled = assembleTileFromBase64([chunk.chunk], 3000);
  assert.equal(detectTileSignature(reassembled), "png");

  const ack = await handleScreenshotMessage(api, { type: "blog.screenshot.ack", version: 1, nonce }, senderOf());
  assert.equal(ack.ok, true);
  assert.equal(api.tileStore.dump.size, 0, "ack 后必须删除图片字节");
  const replay = await handleScreenshotMessage(api, { type: "blog.screenshot.get-meta", version: 1, nonce }, senderOf());
  assert.equal(replay.ok, false);
  assert.equal(replay.code, "replayed");
});

test("错 origin、错 tab、过期与未知 nonce 不 ACK", async () => {
  const api = makeApi();
  const { nonce } = await prepareSession(api);
  const wrongOrigin = await handleScreenshotMessage(
    api, { type: "blog.screenshot.get-meta", version: 1, nonce },
    { url: "https://evil.example/blog", tab: { id: 4321 } },
  );
  assert.equal(wrongOrigin.ok, false);
  assert.equal(wrongOrigin.code, "origin_mismatch");
  const invalidAck = await handleScreenshotMessage(
    api, { type: "blog.screenshot.ack", version: 1, nonce },
    { url: "https://evil.example/blog", tab: { id: 4321 } },
  );
  assert.equal(invalidAck.code, "origin_mismatch");
  assert.equal(api.tileStore.dump.size, 1, "无权限 ACK 不得删除图片");

  const wrongTab = await handleScreenshotMessage(
    api, { type: "blog.screenshot.get-meta", version: 1, nonce }, senderOf(9999),
  );
  assert.equal(wrongTab.ok, false);
  assert.equal(wrongTab.code, "tab_mismatch");

  const wrongPath = await handleScreenshotMessage(
    api, { type: "blog.screenshot.get-meta", version: 1, nonce }, senderOf(4321, "/other"),
  );
  assert.equal(wrongPath.ok, false);

  const unknown = await handleScreenshotMessage(
    api, { type: "blog.screenshot.get-meta", version: 1, nonce: "f".repeat(32) }, senderOf(),
  );
  assert.equal(unknown.ok, false);
  assert.equal(unknown.code, "unknown_nonce");
  const validAck = await handleScreenshotMessage(
    api, { type: "blog.screenshot.ack", version: 1, nonce }, senderOf(),
  );
  assert.equal(validAck.ok, true, "失败的 ACK 不得占用合法接收者的一次性锁");
});

test("过期会话清理图片并从 pending 移除", async () => {
  const api = makeApi();
  const { nonce } = await prepareSession(api);
  const record = api.storage.dump.get(`shot:${nonce}`);
  record.expiresAt = Date.now() - 1;
  const response = await handleScreenshotMessage(api, { type: "blog.screenshot.get-meta", version: 1, nonce }, senderOf());
  assert.equal(response.ok, false);
  assert.equal(response.code, "expired");
  assert.equal(api.tileStore.dump.size, 0);
  assert.deepEqual(api.storage.dump.get("shot:pending"), []);
});

test("重复消费并发：两个 ack 只有一个成功且字节只删一次", async () => {
  const api = makeApi();
  const { nonce } = await prepareSession(api);
  const [first, second] = await Promise.all([
    handleScreenshotMessage(api, { type: "blog.screenshot.ack", version: 1, nonce }, senderOf()),
    handleScreenshotMessage(api, { type: "blog.screenshot.ack", version: 1, nonce }, senderOf()),
  ]);
  const successes = [first, second].filter((r) => r.ok);
  assert.equal(successes.length, 1);
  assert.equal(api.tileStore.dump.size, 0);
});

test("cancel 删除图片与记录", async () => {
  const api = makeApi();
  const { nonce } = await prepareSession(api);
  const response = await handleScreenshotMessage(api, { type: "blog.screenshot.cancel", version: 1, nonce }, senderOf());
  assert.equal(response.ok, true);
  assert.equal(api.tileStore.dump.size, 0);
  assert.equal(api.storage.dump.has(`shot:${nonce}`), false);
  assert.deepEqual(api.storage.dump.get("shot:pending"), []);
});

test("tile/chunk 越界拒绝", async () => {
  const api = makeApi();
  const { nonce } = await prepareSession(api);
  const badTile = await handleScreenshotMessage(
    api, { type: "blog.screenshot.get-tile-chunk", version: 1, nonce, tileIndex: 5, chunkIndex: 0 }, senderOf(),
  );
  assert.equal(badTile.ok, false);
  assert.equal(badTile.code, "tile_missing");
  assert.equal(validateShotTileIndex(-1, 1).ok, false);
});

test("purgeExpiredShots 只清理过期/已消费会话", async () => {
  const api = makeApi();
  const { nonce } = await prepareSession(api);
  const staleNonce = "a".repeat(32);
  api.storage.dump.set(`shot:${staleNonce}`, {
    kind: "screenshot", version: 1, nonce: staleNonce, consumed: false,
    createdAt: 0, expiresAt: Date.now() - 1000, tiles: [], totalBytes: 0,
    targetOrigin: TARGET_ORIGIN, targetTabId: null,
  });
  api.storage.dump.set("shot:pending", [nonce, staleNonce]);
  await purgeExpiredShots(api);
  const pending = api.storage.dump.get("shot:pending");
  assert.deepEqual(pending, [nonce]);
  assert.equal(api.storage.dump.has(`shot:${staleNonce}`), false);
});

test("shotMeta 不包含任何图片字节", async () => {
  const api = makeApi();
  const { nonce } = await prepareSession(api);
  const record = api.storage.dump.get(`shot:${nonce}`);
  const meta = shotMeta(record);
  const serialized = JSON.stringify(meta);
  assert.ok(!serialized.includes("iVBOR"));
  assert.ok(!serialized.includes("WKFDRQ"));
});

test("并发双保存受 MAX_PENDING_SHOTS 限制", async () => {
  const api = makeApi();
  await prepareSession(api);
  await assert.rejects(
    () => prepareSession(api),
    (error) => error.code === "too_many_pending",
  );
});

test("sameShotPageLocation：滚动导致的 query/锚点漂移不算导航", () => {
  // 站点滚动时 replaceState 更新查询参数/锚点，采集不应中止
  assert.equal(sameShotPageLocation(
    "https://example.org/article/long-page",
    "https://example.org/article/long-page?position=3#heading-12",
  ), true);
  assert.equal(sameShotPageLocation(
    "https://example.org/article/long-page?pos=1",
    "https://example.org/article/long-page?pos=2",
  ), true);
  // 真正换了路径/域名仍要中止
  assert.equal(sameShotPageLocation(
    "https://example.org/article/long-page",
    "https://example.org/other/page",
  ), false);
  assert.equal(sameShotPageLocation(
    "https://example.org/article",
    "https://evil.example.org/article",
  ), false);
  // scheme 变化视为导航
  assert.equal(sameShotPageLocation(
    "https://example.org/article",
    "http://example.org/article",
  ), false);
});

test("sameShotPageLocation：非法或非字符串输入安全回退", () => {
  assert.equal(sameShotPageLocation("not a url", "not a url"), true);
  assert.equal(sameShotPageLocation("not a url", "another"), false);
  assert.equal(sameShotPageLocation(undefined, "https://example.org/"), false);
  assert.equal(sameShotPageLocation("https://example.org/", null), false);
});

test("dropPendingShots 释放唯一 pending 名额后可再次保存", async () => {
  const api = makeApi();
  await prepareSession(api);
  // 名额被占：再次保存必须拒绝
  await assert.rejects(() => prepareSession(api), (error) => error.code === "too_many_pending");
  // 用户开始新采集时清空旧 pending
  await dropPendingShots(api);
  const stored = (await api.storage.get("shot:pending")) ?? {};
  assert.deepEqual(stored["shot:pending"], []);
  // 清空后同一 api 可再次保存成功
  await assert.doesNotReject(() => prepareSession(api));
});
