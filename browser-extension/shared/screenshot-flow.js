/**
 * B-045 screenshot-v1 流程：会话暂存与 worker 侧分块消费。
 * 图片 Blob 经 adapter 存 IndexedDB；storage.session 只存元数据。
 * DOM/chrome API 通过 adapter 注入，Node 单元测试可驱动完整流程。
 */

import {
  MAX_PENDING_SHOTS,
  SHOT_ACK,
  SHOT_CANCEL,
  SHOT_GET_META,
  SHOT_GET_TILE,
  SHOT_KIND,
  SHOT_PROTOCOL_VERSION,
  SHOT_TTL_MS,
  ShotProtocolError,
  buildShotRecord,
  chunkCountFor,
  tileChunkBase64,
  shotMeta,
  validateShotRecordAccess,
  validateShotTileIndex,
} from "./shot-protocol.js";

export class ShotFlowError extends Error {
  constructor(message, code) {
    super(message);
    this.name = "ShotFlowError";
    this.code = code;
  }
}

async function sha256Hex(bytes) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const digest = await crypto.subtle.digest("SHA-256", view);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function liveShotIds(api, now) {
  const stored = (await api.storage.get("shot:pending")) ?? {};
  const ids = Array.isArray(stored["shot:pending"]) ? stored["shot:pending"] : [];
  const live = [];
  for (const id of ids) {
    if (typeof id !== "string" || !/^[0-9a-f]{32}$/.test(id)) continue;
    const key = `shot:${id}`;
    const record = ((await api.storage.get(key)) ?? {})[key];
    if (record?.kind === SHOT_KIND && !record.consumed && Number(record.expiresAt) > now) {
      live.push(id);
    } else {
      await api.tileStore.deleteNonce(id);
      await api.storage.remove(key);
    }
  }
  if (live.length !== ids.length) await api.storage.set({ "shot:pending": live });
  return live;
}

/**
 * 采集完成后保存会话：校验 tile、写 IndexedDB 与 storage.session，打开博客页。
 * tile 内容绝不进入 storage、URL、日志。
 */
/**
 * 清空待接收会话：用户开始新采集即表示放弃旧 pending，
 * 避免 MAX_PENDING_SHOTS=1 的名额被 15 分钟 TTL 卡住后续截图。
 */
export async function dropPendingShots(api) {
  const stored = (await api.storage.get("shot:pending")) ?? {};
  const ids = Array.isArray(stored["shot:pending"]) ? stored["shot:pending"] : [];
  for (const id of ids) {
    if (typeof id !== "string" || !/^[0-9a-f]{32}$/.test(id)) continue;
    try {
      await api.tileStore.deleteNonce(id);
    } catch {
      // 尽力清理；tile 过期后本就会被 purge 移除。
    }
    await api.storage.remove(`shot:${id}`);
  }
  await api.storage.set({ "shot:pending": [] });
}

export async function saveScreenshotSession(api, input) {
  if (!input || typeof input !== "object") throw new ShotFlowError("请求无效", "bad_input");
  const { targetOrigin, tiles } = input;
  if (!api.allowedOrigins.includes(targetOrigin)) {
    throw new ShotFlowError("请选择允许的博客地址", "origin_not_allowed");
  }
  if (!Array.isArray(tiles) || tiles.length === 0) {
    throw new ShotFlowError("没有可交接的截图", "no_tiles");
  }

  const now = Date.now();
  const pending = await liveShotIds(api, now);
  if (pending.length >= MAX_PENDING_SHOTS) {
    throw new ShotFlowError("已有一个待接收的截图会话；请先在博客里完成接收或取消", "too_many_pending");
  }

  const tileMetas = [];
  const preparedTiles = [];
  let totalBytes = 0;
  for (let index = 0; index < tiles.length; index += 1) {
    const tile = tiles[index];
    const bytes = tile.bytes instanceof Uint8Array ? tile.bytes : new Uint8Array(tile.bytes);
    totalBytes += bytes.byteLength;
    if (totalBytes > 20 * 1024 * 1024) {
      throw new ShotFlowError("截图总大小超过 20 MiB 上限，请缩小截取范围", "size_limit");
    }
    const sha256 = await sha256Hex(bytes);
    tileMetas.push({
      index,
      mime: tile.mime,
      bytes: bytes.byteLength,
      sha256,
      width: tile.width ?? 0,
      height: tile.height ?? 0,
      scrollX: tile.scrollX ?? 0,
      scrollY: tile.scrollY ?? 0,
      imageCandidates: tile.imageCandidates,
      imageCandidateOverflow: tile.imageCandidateOverflow ?? 0,
    });
    preparedTiles.push({ bytes, index });
  }

  const nonce = api.createNonce(16);
  let record;
  try {
    record = buildShotRecord({
      nonce,
      mode: input.mode,
      sourceUrl: input.sourceUrl ?? "",
      titleCandidate: input.titleCandidate ?? "",
      capturedAt: now,
      dpr: input.dpr ?? 1,
      viewportWidth: input.viewportWidth ?? 0,
      viewportHeight: input.viewportHeight ?? 0,
      coveredTop: input.coveredTop ?? 0,
      coveredBottom: input.coveredBottom ?? 0,
      truncated: input.truncated ?? false,
      selection: input.selection,
      warnings: input.warnings ?? [],
      tiles: tileMetas,
      createdAt: now,
      expiresAt: now + SHOT_TTL_MS,
      targetOrigin,
    });
  } catch (cause) {
    if (cause instanceof ShotProtocolError) throw new ShotFlowError(cause.message, cause.code);
    throw cause;
  }

  let blogTab;
  let stage = "storage";
  try {
    for (const tile of preparedTiles) {
      await api.tileStore.put(nonce, tile.index, tile.bytes);
    }
    await api.storage.set({ [`shot:${nonce}`]: record });
    await api.storage.set({ "shot:pending": [...pending, nonce] });
    stage = "tab";
    blogTab = await api.openTab(`${targetOrigin}/blog#shot=${nonce}&ext=${api.extensionId}&kind=${SHOT_KIND}`);
    if (blogTab?.id == null) throw new Error("无法绑定目标标签页");
    const bound = { ...record, targetTabId: blogTab.id };
    await api.storage.set({ [`shot:${nonce}`]: bound });
    // 生产适配器先创建 about:blank，再绑定 tab ID，最后导航。
    // 因而博客页从出现的第一刻起就只能在目标 tab 消费截图。
    await api.activateTab?.(blogTab, `${targetOrigin}/blog#shot=${nonce}&ext=${api.extensionId}&kind=${SHOT_KIND}`);
  } catch {
    await api.tileStore.deleteNonce(nonce).catch(() => undefined);
    await api.storage.remove(`shot:${nonce}`).catch(() => undefined);
    await api.storage.set({ "shot:pending": pending }).catch(() => undefined);
    if (blogTab?.id != null) await api.closeTab?.(blogTab.id).catch(() => undefined);
    if (stage === "storage") {
      throw new ShotFlowError("截图暂存失败，可能是浏览器存储空间不足；已清理本次图片，请缩小范围后重试", "storage_failed");
    }
    throw new ShotFlowError("无法打开博客页面，请检查博客是否在运行后重试", "tab_open_failed");
  }
  return { nonce, tabId: blogTab.id };
}

/**
 * “仅保存图片”路径：与 saveScreenshotSession 相同的校验与暂存（tile 进
 * IndexedDB、元数据进 storage.session），但不打开博客页、不占用待接收名额。
 * tile 由 offscreen 文档拼接下载后清理；失败时保留到 TTL 过期为止。
 */
export async function storeLocalShot(api, input) {
  if (!input || typeof input !== "object") throw new ShotFlowError("请求无效", "bad_input");
  const { targetOrigin, tiles } = input;
  // 仅保存图片与博客无关：不校验博客地址，博客未启动也能保存
  if (!Array.isArray(tiles) || tiles.length === 0) {
    throw new ShotFlowError("没有可保存的截图", "no_tiles");
  }

  const now = Date.now();
  const tileMetas = [];
  const preparedTiles = [];
  let totalBytes = 0;
  for (let index = 0; index < tiles.length; index += 1) {
    const tile = tiles[index];
    const bytes = tile.bytes instanceof Uint8Array ? tile.bytes : new Uint8Array(tile.bytes);
    totalBytes += bytes.byteLength;
    if (totalBytes > 20 * 1024 * 1024) {
      throw new ShotFlowError("截图总大小超过 20 MiB 上限，请缩小截取范围", "size_limit");
    }
    const sha256 = await sha256Hex(bytes);
    tileMetas.push({
      index,
      mime: tile.mime,
      bytes: bytes.byteLength,
      sha256,
      width: tile.width ?? 0,
      height: tile.height ?? 0,
      scrollX: tile.scrollX ?? 0,
      scrollY: tile.scrollY ?? 0,
    });
    preparedTiles.push({ bytes, index });
  }

  const nonce = api.createNonce(16);
  let record;
  try {
    record = buildShotRecord({
      nonce,
      mode: input.mode,
      sourceUrl: input.sourceUrl ?? "",
      titleCandidate: input.titleCandidate ?? "",
      capturedAt: now,
      dpr: input.dpr ?? 1,
      viewportWidth: input.viewportWidth ?? 0,
      viewportHeight: input.viewportHeight ?? 0,
      coveredTop: input.coveredTop ?? 0,
      coveredBottom: input.coveredBottom ?? 0,
      truncated: input.truncated ?? false,
      selection: input.selection,
      warnings: input.warnings ?? [],
      tiles: tileMetas,
      createdAt: now,
      expiresAt: now + SHOT_TTL_MS,
      targetOrigin: targetOrigin ?? "",
    });
  } catch (cause) {
    if (cause instanceof ShotProtocolError) throw new ShotFlowError(cause.message, cause.code);
    throw cause;
  }
  record = { ...record, localSave: true, targetTabId: input.targetTabId ?? 0 };
  try {
    for (const tile of preparedTiles) {
      await api.tileStore.put(nonce, tile.index, tile.bytes);
    }
    await api.storage.set({ [`shot:${nonce}`]: record });
  } catch {
    await api.tileStore.deleteNonce(nonce).catch(() => undefined);
    await api.storage.remove(`shot:${nonce}`).catch(() => undefined);
    throw new ShotFlowError("截图暂存失败，可能是浏览器存储空间不足；已清理本次图片，请缩小范围后重试", "storage_failed");
  }
  return { nonce };
}

async function removePending(api, nonce) {
  const stored = (await api.storage.get("shot:pending")) ?? {};
  const ids = Array.isArray(stored["shot:pending"]) ? stored["shot:pending"] : [];
  await api.storage.set({ "shot:pending": ids.filter((item) => item !== nonce) });
}

/** worker 侧统一入口：get-meta / get-tile-chunk / ack / cancel。 */
export async function handleScreenshotMessage(api, message, sender, options = {}) {
  const validate = options.validate ?? validateShotRecordAccess;
  if (!message || typeof message !== "object") {
    return { ok: false, code: "bad_message", detail: "消息格式不正确" };
  }
  const nonce = typeof message.nonce === "string" ? message.nonce : "";
  if (!/^[0-9a-f]{32}$/.test(nonce)) {
    return { ok: false, code: "bad_nonce", detail: "截图交接凭据格式不正确" };
  }
  // ack 在任何 await 之前同步认领：并发双消费只有一次成功（失败路径释放）
  const claimKey = `ack:${nonce}`;
  const claimed = message.type === SHOT_ACK && typeof api.claimNonce === "function" ? api.claimNonce(claimKey) : true;
  if (!claimed) {
    return { ok: false, code: "replayed", detail: "该截图已接收过，请从扩展重新发送" };
  }
  try {
    const result = await dispatchScreenshotMessage(api, message, sender, options, validate, nonce);
    if (!result.ok && message.type === SHOT_ACK && typeof api.releaseNonce === "function") {
      api.releaseNonce(claimKey);
    }
    return result;
  } catch (cause) {
    if (claimed && typeof api.releaseNonce === "function") api.releaseNonce(claimKey);
    throw cause;
  }
}

async function dispatchScreenshotMessage(api, message, sender, options, validate, nonce) {
  const key = `shot:${nonce}`;
  const stored = (await api.storage.get(key)) ?? {};
  const record = stored[key] ?? null;
  const verdict = validate(message, record, sender, { now: options.now ? options.now() : Date.now() });
  if (!verdict.ok) {
    if (record && verdict.code === "expired") {
      await api.tileStore.deleteNonce(nonce);
      await api.storage.remove(key);
      await removePending(api, nonce);
    }
    return { ok: false, code: verdict.code, detail: verdict.detail };
  }
  const live = verdict.record;
  if (!live || !Array.isArray(live.tiles) || live.tiles.length === 0) {
    return { ok: false, code: "bad_record", detail: "扩展暂存的截图会话不完整；请重新加载扩展后重试" };
  }

  switch (message.type) {
    case SHOT_GET_META:
      api.log?.("shot meta", { nonce: nonce.slice(0, 6) });
      return { ok: true, meta: shotMeta(live) };

    case SHOT_GET_TILE: {
      const tileCheck = validateShotTileIndex(message.tileIndex, live.tiles.length);
      if (!tileCheck.ok) return { ok: false, code: tileCheck.code, detail: tileCheck.detail };
      const tileMeta = live.tiles[message.tileIndex];
      const bytes = await api.tileStore.get(nonce, message.tileIndex);
      if (!bytes) {
        return { ok: false, code: "tile_missing", detail: "截图分片已丢失，请从扩展重新发送" };
      }
      if (bytes.byteLength !== tileMeta.bytes) {
        return { ok: false, code: "size_mismatch", detail: "截图分片大小与声明不符，请从扩展重新发送" };
      }
      const chunkIndex = message.chunkIndex ?? 0;
      let tileChunk;
      try {
        tileChunk = tileChunkBase64(bytes, chunkIndex);
      } catch (cause) {
        if (cause instanceof ShotProtocolError) return { ok: false, code: cause.code, detail: cause.message };
        throw cause;
      }
      return {
        ok: true,
        tileIndex: message.tileIndex,
        chunkIndex,
        chunkCount: tileChunk.chunkCount,
        chunk: tileChunk.chunk,
      };
    }

    case SHOT_ACK: {
      // 原子消费：清空 IndexedDB 图片，只保留不含内容的 tombstone。
      await api.tileStore.deleteNonce(nonce);
      const consumed = { ...live, tiles: live.tiles.map((tile) => ({ ...tile, bytes: 0 })), consumed: true };
      await api.storage.set({ [key]: consumed });
      await removePending(api, nonce);
      api.log?.("shot ack", { nonce: nonce.slice(0, 6) });
      return { ok: true };
    }

    case SHOT_CANCEL: {
      await api.tileStore.deleteNonce(nonce);
      await api.storage.remove(key);
      await removePending(api, nonce);
      api.log?.("shot cancel", { nonce: nonce.slice(0, 6) });
      return { ok: true };
    }

    default:
      return { ok: false, code: "wrong_type", detail: "不支持的消息类型" };
  }
}

/** 启动/打开 popup/过期时清理：删除过期会话的 Blob 与记录。 */
export async function purgeExpiredShots(api, now = Date.now()) {
  const stored = (await api.storage.get("shot:pending")) ?? {};
  const ids = Array.isArray(stored["shot:pending"]) ? stored["shot:pending"] : [];
  for (const id of ids) {
    const key = `shot:${id}`;
    const record = ((await api.storage.get(key)) ?? {})[key];
    if (!record || record.consumed || Number(record.expiresAt) <= now) {
      await api.tileStore.deleteNonce(id);
      await api.storage.remove(key);
      await removePending(api, id);
    }
  }
}

export { SHOT_PROTOCOL_VERSION, SHOT_KIND, chunkCountFor };
