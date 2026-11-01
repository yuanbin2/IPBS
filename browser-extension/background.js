/**
 * service worker：处理 v2 通用网页剪藏与 screenshot-v1 截图交接分块消费。
 * 旧的 v1 力扣交接协议已于 2026-10-07 随「力扣导入」功能一并移除。
 *
 * B-045 截图边界：图片 Blob 只存扩展 IndexedDB（15 分钟 TTL）；
 * storage.session 只存 nonce/元数据；ack 原子消费并清理；
 * 不读取 Cookie/隐藏接口，不在后台自动采集——一切由用户点击触发。
 */

import { handleWebClipMessage } from "./shared/clip-flow.js";
import { validateWebRecordAccess, DEFAULT_TARGET_ORIGINS } from "./shared/protocol.js";
import { dropPendingShots, handleScreenshotMessage, purgeExpiredShots, saveScreenshotSession, storeLocalShot, ShotFlowError } from "./shared/screenshot-flow.js";
import {
  MAX_SHOT_TILES,
  MAX_SHOT_PAGE_HEIGHT_CSS,
  SHOT_SESSION_TIMEOUT_MS,
  nextManualShotY,
  ShotProtocolError,
  sameShotPageLocation,
  validateShotRecordAccess,
} from "./shared/shot-protocol.js";

/** 同一 worker 实例内已消费 nonce：并发双消费只有一次成功。 */
const consumedNonces = new Set();
/** screenshot-v1 ack 的同步认领表：在任何 await 之前抢锁，避免并发双 ACK。 */
const shotAckClaims = new Set();

const shotClaim = {
  claimNonce: (key) => {
    if (shotAckClaims.has(key)) return false;
    shotAckClaims.add(key);
    return true;
  },
  releaseNonce: (key) => {
    shotAckClaims.delete(key);
  },
};

function fail(code, detail) {
  return { ok: false, code, detail };
}


/* ---------------- 截图 tile 的 IndexedDB 暂存 ---------------- */

function createTileStore(dbName, storeName) {
  let dbPromise = null;
  function open() {
    if (!dbPromise) {
      dbPromise = new Promise((resolve, reject) => {
        const request = indexedDB.open(dbName, 1);
        request.onupgradeneeded = () => {
          if (!request.result.objectStoreNames.contains(storeName)) request.result.createObjectStore(storeName);
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error ?? new Error("indexeddb open failed"));
      });
    }
    return dbPromise;
  }
  const requestAsPromise = (request) =>
    new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error ?? new Error("indexeddb request failed"));
    });
  return {
    async put(nonce, index, bytes) {
      const db = await open();
      const tx = db.transaction(storeName, "readwrite");
      return requestAsPromise(tx.objectStore(storeName).put(bytes, `${nonce}:${index}`));
    },
    async get(nonce, index) {
      const db = await open();
      const tx = db.transaction(storeName, "readonly");
      const result = await requestAsPromise(tx.objectStore(storeName).get(`${nonce}:${index}`));
      return result ?? null;
    },
    async deleteNonce(nonce) {
      const db = await open();
      const tx = db.transaction(storeName, "readwrite");
      const store = tx.objectStore(storeName);
      for (let index = 0; index < MAX_SHOT_TILES; index += 1) store.delete(`${nonce}:${index}`);
      await new Promise((resolve, reject) => {
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error ?? new Error("indexeddb delete failed"));
      });
    },
  };
}

const tileStore = createTileStore("blog-webclip", "shot-tiles");
// 测试钩子：Playwright 侧载用例从 worker 全局读取 tileStore，验证真实 IndexedDB 行为。
// service worker 的 globalThis 对网页脚本不可达，不扩大任何页面侧攻击面。
globalThis.__shotTileStore = tileStore;
globalThis.__shotDebug = { saveScreenshotSession, storeLocalShot, finalizeLocalSave, handleScreenshotMessage, purgeExpiredShots, shotApi,
  cropScrollViewport, previewNewSlice, runLongPageCapture };

function shotApi() {
  return {
    extensionId: chrome.runtime.id,
    allowedOrigins: DEFAULT_TARGET_ORIGINS,
    createNonce: (size) => {
      const bytes = crypto.getRandomValues(new Uint8Array(size));
      return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
    },
    storage: chrome.storage.session,
    tileStore,
    openTab: () => chrome.tabs.create({ url: "about:blank", active: false }),
    activateTab: (tab, url) => chrome.tabs.update(tab.id, { url, active: true }),
    closeTab: (tabId) => chrome.tabs.remove(tabId),
    log: (...args) => console.debug("[blog-shot]", ...args),
  };
}

/* ---------------- 截图采集（仅用户点击后执行） ---------------- */

function dataUrlToBytes(dataUrl) {
  const base64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function bytesToDataUrl(bytes, mime = "image/jpeg") {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  return `data:${mime};base64,${btoa(binary)}`;
}

/** 只保留用户框的上下边界；框从屏幕顶部开始时也必须裁掉底部遮挡物。 */
async function cropScrollViewport(bytes, plan) {
  if (!plan.captureTop && plan.viewportHeight >= plan.screenHeight - 1)
    return { bytes, width: Math.round(plan.viewportWidth * plan.dpr), height: Math.round(plan.viewportHeight * plan.dpr) };
  const bitmap = await createImageBitmap(new Blob([bytes], { type: "image/jpeg" }));
  try {
    const scale = bitmap.height / plan.screenHeight;
    const top = Math.max(0, Math.round(plan.captureTop * scale));
    const height = Math.min(bitmap.height - top, Math.round(plan.viewportHeight * scale));
    if (height < 80) throw new ShotProtocolError("所选滚动区域不可见，请重新框选", "bad_viewport");
    const canvas = new OffscreenCanvas(bitmap.width, height);
    canvas.getContext("2d").drawImage(bitmap, 0, top, bitmap.width, height, 0, 0, bitmap.width, height);
    const blob = await canvas.convertToBlob({ type: "image/jpeg", quality: 0.92 });
    return { bytes: new Uint8Array(await blob.arrayBuffer()), width: canvas.width, height: canvas.height };
  } finally {
    bitmap.close();
  }
}

/** 预览只传新覆盖的窄条缩略图；完整原图仍只放在扩展 IndexedDB。 */
async function previewNewSlice(tileBytes, selection, captureY, previousBottom, viewportHeight) {
  const start = Math.max(selection.top, previousBottom, captureY);
  const end = captureY + viewportHeight;
  if (end - start < 4) return null;
  const bitmap = await createImageBitmap(new Blob([tileBytes], { type: "image/jpeg" }));
  try {
    const x = Math.round(selection.left * bitmap.width);
    const width = Math.round((selection.right - selection.left) * bitmap.width);
    const y = Math.round((start - captureY) / viewportHeight * bitmap.height);
    const height = Math.min(bitmap.height - y, Math.round((end - start) / viewportHeight * bitmap.height));
    if (width < 20 || height < 4) return null;
    const previewWidth = 170;
    const previewHeight = Math.max(1, Math.round(height * previewWidth / width));
    const canvas = new OffscreenCanvas(previewWidth, previewHeight);
    canvas.getContext("2d").drawImage(bitmap, x, y, width, height, 0, 0, previewWidth, previewHeight);
    const blob = await canvas.convertToBlob({ type: "image/jpeg", quality: 0.64 });
    return bytesToDataUrl(new Uint8Array(await blob.arrayBuffer()));
  } finally {
    bitmap.close();
  }
}

async function injectShotContent(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["shared/scroll-root.js", "shared/shot-content.js"] });
}

/** 内容脚本消息统一超时：页面冻结/消息丢失时把挂起变成可见错误，而不是无限等待。 */
async function sendToTab(tabId, message) {
  // scroll-to 最坏 3 次重试 × 3 秒稳定等待，放宽到 15 秒；其余 8 秒。
  const timeoutMs = message.type === "blog.shot.scroll-to" ? 15000 : 8000;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new ShotProtocolError("页面响应超时（标签页可能已休眠），请重新截取", "tab_timeout"));
    }, timeoutMs);
    try {
      chrome.tabs.sendMessage(tabId, message, (response) => {
        clearTimeout(timer);
        const error = chrome.runtime.lastError?.message;
        if (error) reject(new ShotProtocolError(error, "send_failed"));
        else resolve(response);
      });
    } catch (cause) {
      clearTimeout(timer);
      reject(cause instanceof Error ? cause : new ShotProtocolError(String(cause), "send_failed"));
    }
  });
}

async function ensureTabStable(tabId, expectedUrl) {
  const tab = await chrome.tabs.get(tabId);
  if (tab.discarded) {
    throw new ShotProtocolError("采集标签页已被浏览器休眠，长截图已停止", "tab_changed");
  }
  // captureVisibleTab 抓的是窗口当前可见标签页，不在前台就停止，避免截到别的内容。
  if (!tab.active) {
    throw new ShotProtocolError("采集标签页已不在前台，长截图已停止", "tab_changed");
  }
  // 只比较 origin+pathname：滚动时页面自己 replaceState 改 query/锚点不算导航。
  if (!sameShotPageLocation(expectedUrl, tab.url)) {
    throw new ShotProtocolError("目标页面已导航到其他地址，长截图已停止", "tab_changed");
  }
  return tab;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

let activeCapture = null;

function abortActiveCapture(note) {
  if (!activeCapture) return;
  activeCapture.cancelled = true;
  activeCapture.abortNote = note ?? "已取消";
}

/**
 * 截图名额互斥：存在活跃会话时，先自愈失效会话（5 分钟超时或原标签页已
 * 关闭的僵尸会话直接释放），仅对真正在跑的会话引导用户回原页面取消。
 */
async function ensureNoActiveCapture() {
  if (!activeCapture) return;
  const expired = activeCapture.expiresAt && Date.now() > activeCapture.expiresAt;
  let tabGone = false;
  try {
    await chrome.tabs.get(activeCapture.tabId);
  } catch {
    tabGone = true;
  }
  if (expired || tabGone) {
    abortActiveCapture("已自动结束失效的旧截图会话");
    activeCapture = null;
    return;
  }
  throw new ShotProtocolError("已有一个截图会话在进行：请回到原页面的小窗点「完成」或「取消」", "capture_busy");
}

/** 把 Chrome 内部注入/连接错误翻译成用户能读懂的具体原因。 */
function describeCaptureCause(cause) {
  const raw = cause instanceof Error ? cause.message : String(cause);
  if (/Cannot access contents of|cannot be scripted|extension has not been invoked|not allowed|restricted/i.test(raw)) {
    return "该页面禁止扩展访问（浏览器设置页、应用商店、PDF 查看器或浏览器登录页等），请换普通网页截取";
  }
  if (/No tab with id|tab was closed|Tab was closed/i.test(raw)) {
    return "目标标签页已关闭或已刷新，请回到页面重新截取";
  }
  if (/frame with URL|was blocked|blocked from/i.test(raw)) {
    return "该页面的安全策略阻止了扩展注入，请换普通网页截取";
  }
  return raw;
}
/**
 * 长页采集（PixPin 式手动滚动）：用户框选宽度和起点后自己滚动页面，
 * worker 在用户滚动停顿时逐屏采集，仅在用户点“完成”后按每张
 * tile 的真实滚动坐标在博客页拼接成一张长图。
 */
async function runLongPageCapture(message) {
  await ensureNoActiveCapture();
  const saveLocal = message.saveMode === true;
  const capture = { cancelled: false, abortNote: "", tabId: message.target.tabId, saveLocal };
  activeCapture = capture;
  const target = message.target;
  // 新采集即放弃旧 pending：名额被上一轮会话占住时不至于卡 15 分钟。
  await dropPendingShots(shotApi()).catch(() => undefined);
  try {
    await injectShotContent(target.tabId);
    const geoResponse = await sendToTab(target.tabId, { type: "blog.shot.geometry" });
    if (!geoResponse?.ok) throw new ShotProtocolError("无法读取页面几何信息", "geometry_failed");
    await sendToTab(target.tabId, {
      type: "blog.shot.show-planner",
      saveMode: saveLocal,
      pageHeight: geoResponse.geometry.pageHeight,
      viewportHeight: geoResponse.geometry.viewportHeight,
      originScrollX: geoResponse.geometry.scrollX,
      originScrollY: geoResponse.geometry.scrollY,
    });
  } catch (cause) {
    activeCapture = null;
    console.warn("[博客剪藏] 截图会话启动失败:", cause);
    throw new ShotProtocolError(describeCaptureCause(cause), "inject_failed");
  }

  const handlePlanReady = async (plan) => {
    const viewportHeight = plan.viewportHeight;
    const selection = plan.selection;
    if (!selection || !Number.isFinite(selection.left) || !Number.isFinite(selection.right) ||
        selection.left < 0 || selection.right > 1 || (selection.right - selection.left) * viewportWidthOf(plan) < 120 ||
        !Number.isFinite(selection.top) || selection.top < 0) {
      activeCapture = null;
      await sendToTab(target.tabId, {
        type: "blog.shot.finish",
        ok: false,
        note: "长截图宽度或范围无效，请重新选择",
      }).catch(() => undefined);
      return;
    }
    const startedAt = Date.now();
    const tiles = [];
    let capturedBytes = 0;
    let lastCaptureY = null;
    let pumping = false;
    let finalized = false;
    let finishRequested = false;
    let desiredY = Number.isFinite(plan.initialScrollY) ? plan.initialScrollY : selection.top;
    let firstCaptured = false;
    let captureStopped = false;
    let interrupted = null;
    const manualWarnings = [];

    /** 到底/超限/异常只暂停采集；只有用户明确点“完成”才保存并打开博客。 */
    const stopCapture = async (note) => {
      if (captureStopped || finalized || capture.cancelled) return;
      captureStopped = true;
      if (note) interrupted = note;
      await sendToTab(target.tabId, {
        type: "blog.shot.show-manual-status", ready: true,
        status: `${note ? `${note} · ` : ""}已截 ${tiles.length} 屏，请点“完成”${saveLocal ? "保存图片" : "发送到博客"}，或点“取消”放弃`,
      }).catch(() => undefined);
    };

    /** 收尾：按已截 tile 生成会话并打开博客校对页。 */
    const finalize = async (reason) => {
      // 防回归：任何自动到底/达限/超时路径都没有提交权。
      if (!finishRequested || finalized) return;
      finalized = true;
      try {
        if (capture.cancelled) return;
        if (!tiles.length) {
          await sendToTab(target.tabId, {
            type: "blog.shot.finish",
            ok: false,
            note: reason === "cancelled" ? "已取消。" : "没有截取到任何视口，请重试。",
          }).catch(() => undefined);
          return;
        }
        const overHeight = lastCaptureY + viewportHeight - selection.top > MAX_SHOT_PAGE_HEIGHT_CSS;
        const truncated = overHeight || Boolean(interrupted) || manualWarnings.length > 0;
        const warnings = [...manualWarnings];
        if (overHeight) warnings.push("超出高度上限，仅截取部分范围");
        if (interrupted) warnings.push(interrupted);
        const sessionInput = {
          targetOrigin: message.targetOrigin,
          mode: "longpage",
          sourceUrl: target.url,
          titleCandidate: target.title,
          dpr: plan.dpr,
          viewportWidth: viewportWidthOf(plan),
          viewportHeight,
          selection: {
            ...selection,
            bottom: Math.min(lastCaptureY + viewportHeight, selection.top + MAX_SHOT_PAGE_HEIGHT_CSS),
          },
          coveredTop: tiles[0].scrollY,
          coveredBottom: lastCaptureY + viewportHeight,
          truncated,
          warnings,
          tiles,
        };
        if (saveLocal) {
          const outcome = await finalizeLocalSave(target, sessionInput);
          // 拼接页会直接通知 HUD；这里只在连页面都没发起时兜底告知
          if (outcome.note) {
            await sendToTab(target.tabId, {
              type: "blog.shot.finish", ok: false, note: outcome.note,
            }).catch(() => undefined);
          }
          return;
        }
        let saved = false;
        let saveErrorText = "";
        for (let attempt = 0; attempt < 2 && !saved; attempt += 1) {
          try {
            await saveScreenshotSession(shotApi(), sessionInput);
            saved = true;
          } catch (cause) {
            saveErrorText = cause instanceof Error ? cause.message : String(cause);
            // 上一次的待接收会话占着唯一名额时，用户的新采集取代它，清空后重试一次。
            if (attempt === 0 && cause instanceof ShotFlowError && cause.code === "too_many_pending") {
              await dropPendingShots(shotApi()).catch(() => undefined);
              continue;
            }
            break;
          }
        }
        if (!saved) {
          await sendToTab(target.tabId, {
            type: "blog.shot.finish",
            ok: false,
            note: `拼接保存失败：${saveErrorText}`,
          }).catch(() => undefined);
          return;
        }
        await sendToTab(target.tabId, {
          type: "blog.shot.finish",
          ok: true,
          note: truncated
            ? `已截取 ${tiles.length} 个视口（未覆盖完整选择范围）。已打开博客，请核对覆盖范围。`
            : `已截取 ${tiles.length} 个视口，正在打开博客…`,
        }).catch(() => undefined);
      } catch (cause) {
        await sendToTab(target.tabId, {
          type: "blog.shot.finish", ok: false,
          note: `截图收尾失败：${cause instanceof Error ? cause.message : String(cause)}`,
        }).catch(() => undefined);
      } finally {
        if (activeCapture === capture) activeCapture = null;
      }
    };

    /** 在当前视口位置采集一张 tile；与上一张几乎重复时跳过。 */
    const captureOnce = async () => {
      await ensureTabStable(target.tabId, target.url);
      try {
        for (let attempt = 0; attempt < 3; attempt += 1) {
          if (capture.cancelled) return false;
          const prepared = await sendToTab(target.tabId, { type: "blog.shot.prepare-capture" });
          if (!prepared?.ok) throw new ShotProtocolError("页面无法准备采集，请重试", "capture_failed");
          const captureY = Number(prepared.position?.scrollY) || 0;
          if (lastCaptureY != null && Math.abs(captureY - lastCaptureY) < 8) return false;
          const dataUrl = await chrome.tabs.captureVisibleTab(target.windowId, { format: "jpeg", quality: 92 });
          const after = await sendToTab(target.tabId, { type: "blog.shot.geometry" });
          if (after?.ok && (Math.abs(after.geometry.viewportWidth - viewportWidthOf(plan)) > 1 ||
              Math.abs(after.geometry.viewportHeight - viewportHeight) > 1 ||
              Math.abs(after.geometry.captureTop - (plan.captureTop ?? 0)) > 1 ||
              Math.abs(after.geometry.screenHeight - (plan.screenHeight ?? viewportHeight)) > 1 ||
              Math.abs(after.geometry.dpr - plan.dpr) > 0.01)) {
            throw new ShotProtocolError("采集期间窗口尺寸或缩放改变，已保留已截部分", "viewport_changed");
          }
          if (!after?.ok || Math.abs(after.geometry.scrollY - captureY) > 2) {
            // 动画/惯性滚动期间坐标已变，绝不能把这张图按旧坐标拼接。
            await sleep(180);
            continue;
          }
          if (capture.cancelled) return false;
          const cropped = await cropScrollViewport(dataUrlToBytes(dataUrl), plan);
          const bytes = cropped.bytes;
          if (capturedBytes + bytes.byteLength > 20 * 1024 * 1024) {
            manualWarnings.push("已达 20MiB 上限，仅保留已截部分");
            return false;
          }
          const previousBottom = lastCaptureY == null ? selection.top : lastCaptureY + viewportHeight;
          capturedBytes += bytes.byteLength;
          tiles.push({
            bytes,
            mime: "image/jpeg",
            width: cropped.width,
            height: cropped.height,
            scrollX: plan.originScrollX ?? 0,
            scrollY: captureY,
            imageCandidates: prepared.position.imageCandidates,
            imageCandidateOverflow: prepared.position.imageCandidateOverflow,
          });
          lastCaptureY = captureY;
          try {
            const previewDataUrl = await previewNewSlice(bytes, selection, captureY, previousBottom, viewportHeight);
            if (previewDataUrl) await sendToTab(target.tabId, {
              type: "blog.shot.show-manual-status",
              status: `已截 ${tiles.length} 屏 · 下滑继续，完成后点“完成”`,
              previewDataUrl,
            });
          } catch {
            // 缩略图是辅助反馈；生成失败不影响已经采集的原图。
          }
          return true;
        }
        throw new ShotProtocolError("页面持续滚动，已停止采集并保留已截部分；请停稳后重新截取", "scroll_unstable");
      } finally {
        // 重复帧、字节上限和异常也必须恢复 HUD 与浮动导航。
        await sendToTab(target.tabId, {
          type: "blog.shot.show-manual-status",
          status: `已截 ${tiles.length} 屏 · 停稳后继续滚动，或点“完成”`,
          ready: firstCaptured,
        }).catch(() => undefined);
      }
    };

    /** 采集泵：滚动停顿事件触发；快速滚动时按 0.85 视口自动补拍，避免拼接空洞。 */
    const pump = async () => {
      if (pumping || !firstCaptured || finalized || capture.cancelled) return;
      pumping = true;
      let stalled = false;
      try {
        for (;;) {
          if (finalized || capture.cancelled || captureStopped) break;
          if (Date.now() - startedAt > SHOT_SESSION_TIMEOUT_MS) {
            await stopCapture("已达 5 分钟采集上限");
            break;
          }
          if (tiles.length >= MAX_SHOT_TILES) {
            await stopCapture(`已达 ${MAX_SHOT_TILES} 屏上限`);
            break;
          }
          const maxCaptureY = selection.top + MAX_SHOT_PAGE_HEIGHT_CSS - viewportHeight;
          if (lastCaptureY != null && lastCaptureY >= maxCaptureY - 2) {
            if (desiredY > lastCaptureY + 8) await stopCapture(`已达 ${MAX_SHOT_PAGE_HEIGHT_CSS}px 高度上限`);
            break;
          }
          if (lastCaptureY != null && desiredY <= lastCaptureY + 8) break;
          const nextY = nextManualShotY(lastCaptureY, desiredY, viewportHeight, selection.top);
          if (nextY == null) break;
          // 保留用户真正滚到的位置；逐屏追赶时的程序滚动不更新 desiredY。
          await sendToTab(target.tabId, {
            type: "blog.shot.show-manual-status", ready: true,
            status: `正在补拍至 ${Math.round(desiredY)}px · 请暂缓滚动（已截 ${tiles.length} 屏）`,
          }).catch(() => undefined);
          const moved = await sendToTab(target.tabId, { type: "blog.shot.scroll-to", y: nextY });
          if (!moved?.ok || Math.abs(moved.actual - nextY) > 2) {
            throw new ShotProtocolError("页面阻止了定位，已停止并保留已截部分", "scroll_blocked");
          }
          let captured = await captureOnce();
          if (!captured) {
            // 静默失败（多为滚动定位未生效）先短暂重试两次；仍失败则明确结束
            // 会话并释放名额——绝不留下无提示卡死的僵尸会话阻断后续截图。
            for (let retry = 0; retry < 2 && !captured && !capture.cancelled && !captureStopped; retry += 1) {
              await sleep(400);
              captured = await captureOnce();
            }
          }
          if (!captured) {
            if (manualWarnings.length) {
              await stopCapture(manualWarnings.at(-1));
            } else {
              capture.cancelled = true;
              if (activeCapture === capture) activeCapture = null;
              await sendToTab(target.tabId, {
                type: "blog.shot.finish", ok: false,
                note: `已自动结束：页面滚动定位不稳定，已截 ${tiles.length} 屏未能继续（未保存）。请重新截取。`,
              }).catch(() => undefined);
            }
            break;
          }
          await sendToTab(target.tabId, {
            type: "blog.shot.show-manual-status",
            status: `已截 ${tiles.length} 屏 · 已覆盖约 ${Math.max(0, Math.round(lastCaptureY + viewportHeight - selection.top))}px · 继续滚动，完成后点“完成”`,
          }).catch(() => undefined);
          await sleep(250);
        }
        if (!finalized && !capture.cancelled && finishRequested) await finalize("user");
      } catch (cause) {
        await stopCapture(cause instanceof Error ? cause.message : "采集失败");
      } finally {
        pumping = false;
      }
      // 唯一的补调度：只在泵退出瞬间确实收到更远的用户终点时运行。
      if (!stalled && !captureStopped && !finalized && !capture.cancelled && lastCaptureY != null && desiredY > lastCaptureY + 8) {
        queueMicrotask(() => { void pump(); });
      }
    };

    capture.onRootRetargeted = () => {
      // 内容脚本自动纠正了滚动容器：此前 tile 的坐标空间可能不对，标记需人工核对
      // （manualWarnings 非空会让 finalize 把 truncated 置真）。
      manualWarnings.push("滚动容器已自动纠正，请关注拼接结果连续性");
    };
    capture.onScrollIdle = (scrollY) => {
      if (captureStopped) return;
      if (Number.isFinite(scrollY)) desiredY = Math.max(desiredY, scrollY);
      void pump();
    };
    capture.onManualFinish = (scrollY) => {
      if (Number.isFinite(scrollY)) desiredY = Math.max(desiredY, scrollY);
      finishRequested = true;
      void pump();
    };
    capture.onTimeout = () => { void stopCapture("已达 5 分钟采集上限"); };
    capture.expiresAt = startedAt + SHOT_SESSION_TIMEOUT_MS;

    // 第一屏保持用户框选时的视口，按选中框的上边缘裁剪；无需强行把起点滚到容器顶部。
    try {
      await ensureTabStable(target.tabId, target.url);
      const firstY = Number.isFinite(plan.initialScrollY) ? plan.initialScrollY : selection.top;
      const moved = await sendToTab(target.tabId, { type: "blog.shot.scroll-to", y: firstY });
      if (!moved?.ok || Math.abs(moved.actual - firstY) > 2) {
        throw new ShotProtocolError("页面无法定位到所选起点，请重新框选", "scroll_blocked");
      }
      await captureOnce();
      if (lastCaptureY != null && Math.abs(lastCaptureY - firstY) > 2) {
        throw new ShotProtocolError("第一屏采集时页面发生移动，请停稳后重新截取", "scroll_unstable");
      }
    } catch (cause) {
      if (capture.cancelled) return;
      if (activeCapture === capture) activeCapture = null;
      await sendToTab(target.tabId, {
        type: "blog.shot.finish",
        ok: false,
        note: cause instanceof Error ? cause.message : "长截图失败",
      }).catch(() => undefined);
      return;
    }
    if (capture.cancelled) return;
    if (!tiles.length) {
      if (activeCapture === capture) activeCapture = null;
      await sendToTab(target.tabId, { type: "blog.shot.finish", ok: false, note: "第一屏采集失败，请重试。" }).catch(() => undefined);
      return;
    }
    firstCaptured = true;
    await sendToTab(target.tabId, {
      type: "blog.shot.show-manual-status",
      status: "已截 1 屏 · 自己向下滚动页面；确认截够后点“完成”",
    }).catch(() => undefined);
    if (desiredY > lastCaptureY + 8 || finishRequested) void pump();
  };

  activeCapture.onPlanReady = handlePlanReady;
  return { ok: true, detail: "已在页面上显示采集面板：框选宽度和起点后，自己滚动页面即可逐屏采集" };
}

function viewportWidthOf(plan) {
  return Number(plan.viewportWidth) || 0;
}

/** 当前屏/手动区域：立即截取当前视口一张。 */
/** “仅保存图片”：拼接下载指定会话。优先用 offscreen 文档（无感）；
 *  某些环境（如 headless）offscreen 创建成功却不执行脚本，此时改开一个
 *  扩展标签页完成。结果由页面直接通知 HUD 标签页并回传 worker，
 *  因此这里只做短等待：MV3 worker 空闲即回收，长等待链不可靠。 */
async function stitchLocalShot(nonce, targetTabId) {
  const quickOutcome = new Promise((resolve) => {
    const timer = setTimeout(() => {
      if (pendingLocalStitch.get(nonce) === settle) pendingLocalStitch.delete(nonce);
      resolve(null);
    }, 8_000);
    const settle = (message) => {
      clearTimeout(timer);
      pendingLocalStitch.delete(nonce);
      resolve(message);
    };
    pendingLocalStitch.set(nonce, settle);
  });

  try {
    if (await chrome.offscreen.hasDocument?.()) {
      await chrome.offscreen.closeDocument().catch(() => undefined);
    }
    await chrome.offscreen.createDocument({
      url: `offscreen-stitch.html?nonce=${encodeURIComponent(nonce)}&targetTabId=${encodeURIComponent(String(targetTabId ?? 0))}`,
      reasons: ["BLOBS"],
      justification: "拼接长截图并保存到下载目录",
    });
  } catch {
    // offscreen 不可用时直接走标签页兜底
  }

  const offscreenOutcome = await quickOutcome;
  if (offscreenOutcome?.ok) return offscreenOutcome;
  if (offscreenOutcome && !offscreenOutcome.ok) {
    throw new Error(offscreenOutcome.detail ?? "拼接保存失败");
  }

  // 8 秒内没有回传：判定 offscreen 在此环境不执行，改开扩展标签页。
  // 页面会自行通知 HUD 并回传结果，这里不再长等（worker 可能被回收）。
  await chrome.offscreen.closeDocument?.().catch(() => undefined);
  await chrome.tabs.create({
    url: `${chrome.runtime.getURL("stitch-page.html")}?nonce=${encodeURIComponent(nonce)}&targetTabId=${encodeURIComponent(String(targetTabId ?? 0))}`,
    // 后台标签页在部分环境下会被延迟加载/挂起；前台创建并在完成后自动关闭
    active: true,
  }).catch((cause) => {
    throw new Error(`无法打开保存页面：${cause instanceof Error ? cause.message : String(cause)}`);
  });
  return null;
}

/** 采集收尾的本地保存分支：暂存→发起拼接下载；HUD 收尾由拼接页直接通知。 */
async function finalizeLocalSave(target, sessionInput) {
  const targetTabId = Number(target?.tabId) || 0;
  const { nonce } = await storeLocalShot(shotApi(), { ...sessionInput, targetTabId });
  const outcome = await stitchLocalShot(nonce, targetTabId);
  if (outcome?.ok) return { ok: true, note: outcome.fileName };
  return { ok: true, note: "" };
}

const pendingLocalStitch = new Map();

async function captureCurrentViewport(message) {
  await ensureNoActiveCapture();
  const target = message.target;
  const saveLocal = message.saveMode === true;
  await dropPendingShots(shotApi()).catch(() => undefined);
  await injectShotContent(target.tabId);
  const geoResponse = await sendToTab(target.tabId, { type: "blog.shot.geometry" });
  if (!geoResponse?.ok) throw new ShotProtocolError("无法读取页面几何信息", "geometry_failed");
  const geometry = geoResponse.geometry;
  await ensureTabStable(target.tabId, target.url);
  const prepared = await sendToTab(target.tabId, { type: "blog.shot.prepare-capture" });
  if (!prepared?.ok || Math.abs(Number(prepared.position?.scrollY) - geometry.scrollY) > 2) {
    throw new ShotProtocolError("页面滚动位置已变化，请重新截取", "tab_changed");
  }
  const dataUrl = await chrome.tabs.captureVisibleTab(target.windowId, { format: "jpeg", quality: 92 });
  const bytes = dataUrlToBytes(dataUrl);
  const sessionInput = {
    targetOrigin: message.targetOrigin,
    mode: message.mode === "region" ? "region" : "screen",
    sourceUrl: target.url,
    titleCandidate: target.title,
    dpr: geometry.dpr,
    viewportWidth: geometry.viewportWidth,
    viewportHeight: geometry.viewportHeight,
    coveredTop: geometry.scrollY,
    coveredBottom: geometry.scrollY + geometry.viewportHeight,
    truncated: false,
    warnings: message.mode === "region" ? ["区域裁剪在博客校对页进行"] : [],
    tiles: [
      {
        bytes,
        mime: "image/jpeg",
        width: Math.round(geometry.viewportWidth * geometry.dpr),
        height: Math.round(geometry.viewportHeight * geometry.dpr),
        scrollX: geometry.scrollX,
        scrollY: geometry.scrollY,
        imageCandidates: prepared.position.imageCandidates,
        imageCandidateOverflow: prepared.position.imageCandidateOverflow,
      },
    ],
  };
  if (saveLocal) {
    const outcome = await finalizeLocalSave(target, sessionInput);
    await sendToTab(target.tabId, { type: "blog.shot.finish", ok: outcome.ok, note: outcome.note }).catch(() => undefined);
    await sendToTab(target.tabId, { type: "blog.shot.hide" }).catch(() => undefined);
    if (!outcome.ok) throw new Error(outcome.note);
    return { ok: true };
  }
  await saveScreenshotSession(shotApi(), sessionInput);
  await sendToTab(target.tabId, { type: "blog.shot.hide" }).catch(() => undefined);
  return { ok: true };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message.type !== "string" || !message.type.startsWith("blog.shot.")) return;
  (async () => {
    try {
      if (message.type === "blog.shot.capture") {
        sendResponse(await captureCurrentViewport(message));
        return;
      }
      if (message.type === "blog.shot.capture-longpage") {
        sendResponse(await runLongPageCapture(message));
        return;
      }
      if (message.type === "blog.shot.plan-ready") {
        if (activeCapture?.onPlanReady && sender.tab?.id === activeCapture.tabId) {
          void activeCapture.onPlanReady({
            startY: message.startY,
            endY: message.endY,
            viewportHeight: message.viewportHeight ?? activeCapture.lastViewportHeight ?? 0,
            viewportWidth: message.viewportWidth ?? 0,
            screenHeight: message.screenHeight,
            captureTop: message.captureTop,
            initialScrollY: message.initialScrollY,
            dpr: message.dpr ?? 1,
            originScrollX: message.originScrollX,
            originScrollY: message.originScrollY,
            selection: message.selection,
          }).catch(async (cause) => {
            activeCapture = null;
            await sendToTab(sender.tab?.id ?? message.tabId, {
              type: "blog.shot.finish", ok: false,
              note: cause instanceof Error ? cause.message : "截图初始化失败",
            }).catch(() => undefined);
          });
          sendResponse({ ok: true });
        } else {
          sendResponse(fail("no_session", "没有进行中的采集会话"));
        }
        return;
      }
      if (message.type === "blog.shot.capture-cancelled") {
        if (sender.tab?.id !== activeCapture?.tabId) {
          sendResponse(fail("wrong_tab", "截图会话不属于此标签页"));
          return;
        }
        abortActiveCapture("已取消");
        // 手动模式下没有 finalize 兜底，取消后立即释放会话。
        activeCapture = null;
        sendResponse({ ok: true });
        return;
      }
      if (message.type === "blog.shot.scroll-idle") {
        if (activeCapture?.onScrollIdle && sender.tab?.id === activeCapture.tabId) {
          activeCapture.onScrollIdle(Number(message.scrollY));
        }
        sendResponse({ ok: true });
        return;
      }
      if (message.type === "blog.shot.root-retargeted") {
        if (activeCapture?.onRootRetargeted && sender.tab?.id === activeCapture.tabId) {
          activeCapture.onRootRetargeted();
        }
        sendResponse({ ok: true });
        return;
      }
      if (message.type === "blog.shot.manual-finish") {
        if (activeCapture?.onManualFinish && sender.tab?.id === activeCapture.tabId) {
          activeCapture.onManualFinish(Number(message.scrollY));
          sendResponse({ ok: true });
        } else {
          sendResponse(fail("no_session", "没有进行中的采集会话"));
        }
        return;
      }
      if (message.type === "blog.shot.local-stitch-result" || message.type === "blog.shot.local-stitch-ready") {
        const nonce = typeof message.nonce === "string" ? message.nonce : "";
        const isReady = message.type === "blog.shot.local-stitch-ready";
        const pending = pendingLocalStitch.get(isReady ? `${nonce}:ready` : nonce);
        if (pending) pending(message);
        sendResponse({ ok: true });
        return;
      }
      if (message.type === "blog.shot.status") {
        if (sender.tab?.id !== activeCapture?.tabId) {
          sendResponse({ ok: true, active: false });
          return;
        }
        if (activeCapture?.expiresAt && Date.now() > activeCapture.expiresAt) {
          activeCapture.onTimeout?.();
        }
        sendResponse({ ok: true, active: Boolean(activeCapture && !activeCapture.cancelled) });
        return;
      }
      if (message.type === "blog.shot.plan-cancelled") {
        if (sender.tab?.id === activeCapture?.tabId) activeCapture = null;
        sendResponse({ ok: true });
        return;
      }
      if (message.type === "blog.shot.purge") {
        await purgeExpiredShots(shotApi());
        sendResponse({ ok: true });
        return;
      }
      sendResponse(fail("wrong_type", "不支持的消息类型"));
    } catch (cause) {
      const detail = describeCaptureCause(cause);
      console.warn("[博客剪藏] 截图失败:", cause);
      sendResponse(fail("capture_failed", detail));
    }
  })();
  return true;
});

/* ---------------- 博客页消费（screenshot-v1 / webclip v2） ---------------- */

chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  const type = message?.type;
  if (typeof type === "string" && type.startsWith("blog.screenshot.")) {
    handleScreenshotMessage(
      {
        storage: chrome.storage.session,
        tileStore,
        ...shotClaim,
        log: (...args) => console.debug("[blog-shot]", ...args),
      },
      message,
      sender,
      { validate: validateShotRecordAccess },
    )
      .then((result) => sendResponse(result))
      .catch((error) => {
        const phase = {
          "blog.screenshot.get-meta": "读取截图元数据",
          "blog.screenshot.get-tile-chunk": "传输截图分片",
          "blog.screenshot.ack": "确认接收截图",
          "blog.screenshot.cancel": "取消截图交接",
        }[type] ?? "处理截图请求";
        const errorName = error instanceof Error && /^(TypeError|RangeError|QuotaExceededError|Error)$/.test(error.name)
          ? error.name : "Error";
        console.error("[blog-shot] failed", { phase, error });
        sendResponse(fail("internal", `扩展后台${phase}失败（${errorName}）；请重新加载扩展后重试`));
      });
    return true;
  }

  if (typeof type === "string" && type.startsWith("blog.webclip.")) {
    handleWebClipMessage(
      {
        storage: chrome.storage.session,
        consumedNonces,
        now: () => Date.now(),
        log: (...args) => console.debug("[blog-webclip]", ...args),
      },
      message,
      sender,
      { validate: validateWebRecordAccess },
    )
      .then((result) => sendResponse(result))
      .catch((error) => {
        const phase = {
          "blog.webclip.get-meta": "读取元数据",
          "blog.webclip.get-chunk": "传输正文",
          "blog.webclip.ack": "确认接收",
          "blog.webclip.cancel": "取消交接",
        }[type] ?? "处理请求";
        const errorName = error instanceof Error && /^(TypeError|RangeError|QuotaExceededError|Error)$/.test(error.name)
          ? error.name : "Error";
        console.error("[blog-webclip] failed", { phase, error });
        sendResponse(fail("internal", `扩展后台${phase}失败（${errorName}）；请重新加载扩展后重试，并查看扩展后台 Console 的首条错误`));
      });
    return true;
  }

  sendResponse(fail("wrong_type", "不支持的消息类型"));
  return true;
});

chrome.runtime.onInstalled.addListener((details) => {
  console.debug("[blog-webclip] extension installed/updated", details.reason);
  void purgeExpiredShots(shotApi());
});

chrome.runtime.onStartup.addListener(() => {
  // IndexedDB 可能跨浏览器重启保留，启动时按 TTL 清理
  void purgeExpiredShots(shotApi());
});
