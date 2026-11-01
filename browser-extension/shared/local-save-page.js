/**
 * “仅保存图片”的页面侧执行逻辑：读截图会话、拼长图、存下载目录、回传结果。
 *
 * 两个入口共用：offscreen-stitch.html（首选，无感）与 stitch-page.html
 * （兜底，新开一个扩展标签页）。必须放在有 DOM 的扩展上下文里执行——
 * service worker 没有 canvas，也无法持有 Blob。
 *
 * 结果经 chrome.runtime.sendMessage 回传给 worker（页面 → worker 一定已就绪；
 * 反向先 connect/sendMessage 会因页面尚未执行而丢消息）。
 */
import { computeStitchPlan, stitchShotTiles } from "./longshot-stitch.js";

const TILE_DB = "blog-webclip";
const TILE_STORE = "shot-tiles";
const MAX_LOCAL_STITCH_TILES = 200;

function openTileDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(TILE_DB, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(TILE_STORE)) request.result.createObjectStore(TILE_STORE);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("indexeddb open failed"));
  });
}

async function readTile(key) {
  const db = await openTileDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(TILE_STORE, "readonly");
    const request = tx.objectStore(TILE_STORE).get(String(key));
    request.onsuccess = () => resolve(request.result ?? null);
    request.onerror = () => reject(request.error ?? new Error("indexeddb get failed"));
  });
}

async function deleteNonce(nonce) {
  const db = await openTileDb();
  await new Promise((resolve, reject) => {
    const tx = db.transaction(TILE_STORE, "readwrite");
    const store = tx.objectStore(TILE_STORE);
    for (let index = 0; index < MAX_LOCAL_STITCH_TILES; index += 1) store.delete(`${nonce}:${index}`);
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error ?? new Error("indexeddb delete failed"));
  });
}

async function cleanupSession(nonce) {
  await deleteNonce(nonce).catch(() => undefined);
  await chrome.storage.session.remove(`shot:${nonce}`).catch(() => undefined);
  const stored = await chrome.storage.session.get("shot:pending").catch(() => ({}));
  const ids = Array.isArray(stored["shot:pending"]) ? stored["shot:pending"] : [];
  if (ids.includes(nonce)) {
    await chrome.storage.session.set({ "shot:pending": ids.filter((item) => item !== nonce) }).catch(() => undefined);
  }
}

function timestampName() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `long-screenshot-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.png`;
}

async function stitchAndDownload(nonce) {
  if (!/^[0-9a-f]{32}$/.test(nonce)) throw new Error("截图会话标识无效");
  const stored = await chrome.storage.session.get(`shot:${nonce}`);
  const record = stored[`shot:${nonce}`];
  if (!record || record.consumed || !Array.isArray(record.tiles)) {
    throw new Error("截图会话不存在或已过期，请重新截取");
  }
  const plan = computeStitchPlan(record);
  const adapter = {
    createCanvas: (width, height) => {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      return canvas;
    },
    loadTile: (index) => readTile(`${nonce}:${index}`),
    decode: async (bytes) => createImageBitmap(new Blob([bytes], { type: "image/jpeg" })),
    drawImage: (context, image, placement) => {
      context.drawImage(image, placement.sx, placement.sy, placement.sw, placement.sh,
        placement.dx, placement.dy, placement.dw, placement.dh);
      image.close?.();
    },
    toBlob: (canvas, mime) => new Promise((resolve, reject) => {
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("长图编码失败"))), mime);
    }),
  };
  const blob = await stitchShotTiles(plan, adapter);
  const fileName = timestampName();
  const url = URL.createObjectURL(blob);
  let downloadId;
  try {
    downloadId = await chrome.downloads.download({ url, filename: fileName, saveAs: false });
    if (downloadId === undefined) throw new Error("浏览器拒绝了下载请求");
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }
  await cleanupSession(nonce);
  return { fileName, width: plan.width, height: plan.height };
}

/**
 * 入口。targetTabId 是采集页（HUD 所在标签页）：拼接结果由本页面直接通知它，
 * 不依赖 service worker 存活——MV3 worker 空闲会被回收，等待链会断。
 */
export function startLocalSavePage({ isOffscreen, targetTabId }) {
  const nonce = new URLSearchParams(location.search).get("nonce") ?? "";
  const tabId = Number(new URLSearchParams(location.search).get("targetTabId") ?? "") || targetTabId;
  const finishHud = (ok, note) => {
    if (!Number.isFinite(tabId) || tabId <= 0) return;
    // 目标标签页的 HUD 就是用户看的收尾：成败都直达，worker 不在场也能显示
    chrome.tabs.sendMessage(tabId, { type: "blog.shot.finish", ok, note }).catch(() => undefined);
  };
  void chrome.runtime.sendMessage({ type: "blog.shot.local-stitch-ready", nonce }).catch(() => {});

  void (async () => {
    try {
      const result = await stitchAndDownload(nonce);
      finishHud(true, `长图已保存到下载目录：${result.fileName}（${result.width}×${result.height}）`);
      await chrome.runtime.sendMessage({ type: "blog.shot.local-stitch-result", nonce, ok: true, ...result });
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : String(cause);
      // 失败时保留会话（TTL 内仍可在博客页消费或重新拼接），只上报原因
      finishHud(false, `拼接保存失败：${detail}`);
      await chrome.runtime.sendMessage({ type: "blog.shot.local-stitch-result", nonce, ok: false, detail });
    } finally {
      setTimeout(() => {
        if (isOffscreen) chrome.offscreen?.closeDocument?.().catch(() => undefined);
        else window.close();
      }, 1200);
    }
  })();
}
