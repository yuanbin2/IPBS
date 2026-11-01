/**
 * 通用网页剪藏 popup。核心流程在 shared/clip-flow.js，抽取在 shared/extract.js；
 * 本文件只做 DOM 与 chrome.* 适配。只用点击后的临时 activeTab 权限。
 */

import { prepareWebClip, WebClipFlowError } from "./shared/clip-flow.js";
import { DEFAULT_TARGET_ORIGINS, utf8ByteLength } from "./shared/protocol.js";

const els = {
  scopeButtons: [...document.querySelectorAll(".scope-btn:not(.shot-btn):not(.save-btn)")],
  saveButtons: [...document.querySelectorAll(".save-btn")],
  shotButtons: [...document.querySelectorAll(".shot-btn")],
  targetButtons: [...document.querySelectorAll(".target-btn")],
  extract: document.getElementById("extract-button"),
  send: document.getElementById("send-button"),
  retry: document.getElementById("retry-button"),
  manual: document.getElementById("manual-save"),
  result: document.getElementById("result"),
  title: document.getElementById("title-input"),
  source: document.getElementById("source-input"),
  url: document.getElementById("url-input"),
  site: document.getElementById("site-input"),
  origin: document.getElementById("target-origin"),
  shotOrigin: document.getElementById("shot-origin"),
  stats: document.getElementById("stats"),
  warnings: document.getElementById("warnings"),
  preview: document.getElementById("preview-text"),
  feedback: document.getElementById("feedback"),
};

let captureMode = "article";
let saveLocal = true; // 默认仅保存图片：这是与博客无关的独立功能
let captureTarget = "private_note";
let extraction = null;
let activeTab = null;

function setFeedback(text, kind) {
  els.feedback.textContent = text ?? "";
  els.feedback.className = `feedback ${kind ?? ""}`;
}

function rememberOrigin(origin) {
  chrome.storage.local.set({ lastTargetOrigin: origin });
}

function isExtensionUrl(url) {
  return typeof url === "string" && url.startsWith("chrome-extension://");
}

/** executeScript / sendMessage 在未授予 activeTab 时可能永不返回：统一超时兜底。 */
function withTimeout(promise, ms) {
  return Promise.race([promise, new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), ms))]);
}

/** 注入自包含经典脚本，再在同一隔离世界调用；不能单独序列化模块函数。 */
async function captureTab(tabId, mode) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["shared/extract-core.js"] });
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: (captureMode) => {
      const extractor = globalThis.__BLOG_WEBCLIP_EXTRACT__;
      if (!extractor) return { ok: false, code: "extract_unavailable", detail: "网页抽取器未加载，请重新加载扩展" };
      return extractor.extractFromDocument(document, captureMode);
    },
    args: [mode],
  });
  return result?.result ?? null;
}

/** 当前活跃的非扩展标签页。 */
async function queryActiveTab() {
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (active && !isExtensionUrl(active.url)) return active;
  return null;
}

function fillOriginOptions(select) {
  select.innerHTML = "";
  for (const origin of DEFAULT_TARGET_ORIGINS) {
    const option = document.createElement("option");
    option.value = origin;
    option.textContent = origin;
    select.append(option);
  }
}

function populateOrigins() {
  fillOriginOptions(els.origin);
  fillOriginOptions(els.shotOrigin);
  chrome.storage.local
    .get(["lastTargetOrigin"])
    .then((stored) => {
      const origin = stored?.lastTargetOrigin;
      if (origin && DEFAULT_TARGET_ORIGINS.includes(origin)) {
        els.origin.value = origin;
        els.shotOrigin.value = origin;
      }
    })
    .catch(() => undefined);
}

els.origin.addEventListener("change", () => {
  if (!els.manual.hidden) els.manual.href = `${els.origin.value}/blog`;
});

function selectScope(mode) {
  captureMode = mode;
  for (const button of els.scopeButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  }
}

function selectSaveTarget(local) {
  saveLocal = local;
  for (const button of els.saveButtons) {
    button.setAttribute("aria-pressed", String((button.dataset.saveTarget === "local") === local));
  }
  // 仅保存图片与博客完全无关：不要求选博客地址，也不读取剪藏设置
  const originRow = document.getElementById("origin-row");
  if (originRow) originRow.hidden = local;
  const hint = document.getElementById("save-mode-hint");
  if (hint) {
    hint.textContent = local
      ? "长图会拼接成一张图片保存到下载目录，不打开博客、不需要博客地址、不上传任何像素；截图只在扩展本地暂存，保存后立即清理。"
      : "截图会发送到博客，在浏览器本地 OCR 后由你校对写入笔记/草稿；请选择博客地址。";
  }
}

function selectTarget(target) {
  captureTarget = target;
  for (const button of els.targetButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.target === target));
  }
  const note = captureTarget === "article_draft"
    ? "将创建未提交的博客草稿；只有你之后主动提交才会进入审核。"
    : "将创建仅本人可见的私有笔记；不会公开、不会进入知识索引。";
  setFeedback(note, "");
}

for (const button of els.scopeButtons) {
  button.addEventListener("click", () => selectScope(button.dataset.mode));
}
for (const button of els.targetButtons) {
  button.addEventListener("click", () => selectTarget(button.dataset.target));
}
for (const button of els.saveButtons) {
  button.addEventListener("click", () => {
    selectSaveTarget(button.dataset.saveTarget === "local");
    void chrome.storage.local.set({ shotSaveLocal: saveLocal });
  });
}
chrome.storage.local.get("shotSaveLocal").then((stored) => {
  selectSaveTarget(stored.shotSaveLocal === true);
}).catch(() => undefined);

const WARNING_LABELS = {
  IMAGE_REMOTE: "张远程图片：站内确认后才会尝试保存到本站（失败不影响文字）",
  IMAGE_NEEDS_MANUAL: "张图片需要你手动上传（懒加载/blob/防盗链/需登录）",
  NO_ARTICLE_BODY: "未识别到明确正文，已按整页降级抽取，请核对",
  FULL_PAGE_MODE: "整页模式可能包含导航等噪声，请删掉多余区块",
};

function renderWarnings(warnings) {
  els.warnings.innerHTML = "";
  for (const warning of warnings ?? []) {
    const label = WARNING_LABELS[warning.code] ?? warning.code;
    const item = document.createElement("p");
    item.className = "warning";
    item.textContent = `${warning.count} ${label}`;
    els.warnings.append(item);
  }
}

/** 用户点击“读取并预览”后才执行抽取。 */
async function extract() {
  els.extract.disabled = true;
  els.send.disabled = true;
  extraction = null;
  els.retry.hidden = true;
  setFeedback("正在读取当前标签页…", "");
  try {
    activeTab = await withTimeout(queryActiveTab(), 5000);
    if (!activeTab?.id || !/^https?:\/\//i.test(activeTab.url ?? "")) {
      // 只处理用户当前标签页；扩展页或受限页不退回去读取其他标签页。
      els.result.hidden = false;
      els.url.value = "";
      els.title.value = "";
      els.site.value = "";
      els.manual.hidden = false;
      els.manual.href = `${els.origin.value}/blog`;
      setFeedback("无法读取当前标签页；请用浏览器另存为 HTML，再到博客写作页手动导入。", "error");
      return;
    }
    extraction = await withTimeout(captureTab(activeTab.id, captureMode), 8000);
    if (!extraction?.ok) {
      throw new WebClipFlowError(extraction?.detail ?? "抽取失败", extraction?.code ?? "extract_failed");
    }
    els.title.value = extraction.titleCandidate ?? "";
    els.url.value = extraction.canonicalUrl ?? activeTab.url ?? "";
    els.site.value = extraction.siteCandidate ?? "";
    els.source.value = "";
    els.preview.textContent = extraction.markdown ?? "";
    els.stats.textContent = `约 ${(extraction.markdown ?? "").length} 字符 · 正文 HTML ${Math.round((extraction.htmlBytes ?? 0) / 1024)} KiB`;
    renderWarnings(extraction.warnings);
    els.result.hidden = false;
    els.send.disabled = false;
    els.manual.hidden = false;
    els.manual.href = `${els.origin.value}/blog`;
    setFeedback("预览已生成；请核对标题、来源和范围后送到博客。站内会再次校验与选择区块。", "ok");
  } catch (error) {
  // 抽取失败时只提供手动 HTML 导入入口，不伪造空正文交接。
    els.result.hidden = false;
    const detail = error instanceof Error && error.message === "timeout"
      ? "读取当前标签页超时；请重试或另存为 HTML 后在博客手动导入"
      : error instanceof Error ? error.message : "抽取失败";
    setFeedback(`${detail}`, "error");
    els.manual.hidden = false;
    els.manual.href = `${els.origin.value}/blog`;
    els.retry.hidden = false;
  } finally {
    els.extract.disabled = false;
  }
}

async function send() {
  if (!extraction?.ok) {
    setFeedback("请先成功读取并预览网页；受限页面可手动保存 HTML 后在博客里导入。", "error");
    return;
  }
  els.send.disabled = true;
  els.retry.hidden = true;
  const note = els.source.value;
  if (utf8ByteLength(note) > 300) {
    setFeedback("来源说明过长", "error");
    els.send.disabled = false;
    return;
  }
  const targetOrigin = els.origin.value;
  rememberOrigin(targetOrigin);
  setFeedback("正在打开博客…", "");
  try {
    await prepareWebClip(
      {
        extensionId: chrome.runtime.id,
        allowedOrigins: DEFAULT_TARGET_ORIGINS,
        getActiveTab: async () => activeTab,
        extract: async (tabId, mode) => {
          if (extraction && mode === captureMode) return extraction;
          return captureTab(tabId, mode);
        },
        createNonce: (size) => {
          const bytes = crypto.getRandomValues(new Uint8Array(size));
          return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
        },
        storage: chrome.storage.session,
        openTab: (url) => chrome.tabs.create({ url }),
        log: (...args) => console.debug("[blog-webclip]", ...args),
      },
      {
        targetOrigin,
        captureTarget,
        captureMode,
        ownNote: note,
        sourceUrl: els.url.value,
        titleCandidate: els.title.value,
        siteCandidate: els.site.value,
      },
    );
    setFeedback(
      captureTarget === "article_draft"
        ? "已打开博客草稿流程；请在导入预览里核对后应用。"
        : "已打开博客；请在预览里核对后保存为私有笔记。",
      "ok",
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : "发送失败";
    setFeedback(detail, "error");
    els.send.disabled = false;
    els.retry.hidden = false;
  }
}

els.extract.addEventListener("click", () => void extract());
els.send.addEventListener("click", () => void send());
els.retry.addEventListener("click", () => void extract());
selectScope("article");
selectTarget("private_note");
populateOrigins();

/* ---------------- B-045 截图识别 ---------------- */

const SHOT_MODE_HINTS = {
  screen: "将截取当前可见视口；到博客页本地识别、校对后保存。",
  region: "先截取当前视口；到博客校对页再框选需要的区域（也可用来裁掉隐私内容）。",
  longpage: "在正文拖出完整截图框（四条边均生效）；框内下滑自动拼接，小窗实时预览，点“完成”才打开博客。",
};

for (const button of els.shotButtons) {
  button.addEventListener("click", () => void captureShot(button.dataset.shotMode));
}

/** 用户点击后才采集；只用点击授予的 activeTab，不读取其他标签页。 */
async function captureShot(mode) {
  setFeedback(SHOT_MODE_HINTS[mode] ?? "正在截取…", "");
  for (const button of els.shotButtons) button.disabled = true;
  try {
    const tab = await withTimeout(queryActiveTab(), 5000);
    if (!tab?.id || !/^https?:\/\//i.test(tab.url ?? "")) {
      setFeedback("请在普通网页上使用截图识别；浏览器设置页等受限页面无法截取。", "error");
      return;
    }
    const response = await withTimeout(
      new Promise((resolve) => {
        chrome.runtime.sendMessage(
          {
            type: mode === "longpage" ? "blog.shot.capture-longpage" : "blog.shot.capture",
            mode,
            saveMode: saveLocal,
            // 仅保存图片不经过博客：不带 targetOrigin，博客未启动也能保存
            ...(saveLocal ? {} : { targetOrigin: els.shotOrigin.value }),
            target: { tabId: tab.id, windowId: tab.windowId, url: tab.url, title: tab.title ?? "" },
          },
          (result) => resolve(result ?? { ok: false, code: "no_response", detail: "扩展后台无响应，请重新加载扩展" }),
        );
      }),
      10000,
    );
    if (!response?.ok) {
      setFeedback(response?.detail ?? "截图失败，请重试", "error");
      return;
    }
    if (!saveLocal) rememberOrigin(els.shotOrigin.value);
    if (saveLocal) {
      setFeedback(mode === "longpage"
        ? "已在网页显示采集面板：正文拖框后自动截第一屏；继续向下滚动，截够后点“完成”，长图直接保存到下载目录。"
        : "已拼接保存到下载目录，没有打开博客。", "ok");
    } else if (mode === "longpage") {
      setFeedback("已在网页显示采集面板：正文拖框后自动截第一屏；继续向下滚动，查看小窗预览，截够后点“完成”。", "ok");
    } else {
      setFeedback("已截取当前视口并打开博客；请在校对页核对后识别。", "ok");
    }
  } catch (error) {
    // 非超时异常显示后台给出的具体原因，不再笼统地报「截图失败」。
    setFeedback(error instanceof Error
      ? (error.message === "timeout" ? "读取标签页超时，请重试" : `截图失败：${error.message}`)
      : "截图失败，请重试", "error");
  } finally {
    for (const button of els.shotButtons) button.disabled = false;
  }
}

// 打开 popup 时清理过期截图会话（IndexedDB 可能跨重启保留）
chrome.runtime.sendMessage({ type: "blog.shot.purge" }).catch(() => undefined);
