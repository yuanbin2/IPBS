/**
 * B-045 截图采集 content script：经典脚本，经 chrome.scripting 按需注入。
 * 只负责：几何测量、滚动、恢复位置、显示本扩展自己的覆盖层 UI。
 * 不读取页面正文、Cookie 或任何站点数据；覆盖层用 Shadow DOM 隔离样式。
 */
(() => {
  if (window.__BLOG_SHOT_CONTENT__) return;

  const OVERLAY_HOST_ID = "__blog_shot_overlay_host__";
  const WIDTH_PICKER_ID = "__blog_shot_width_picker__";
  let originalScroll = { x: 0, y: 0 };
  let selectedBand = null;
  let scrollRoot = null;
  let originalRootScroll = 0;
  const hiddenNavigation = [];
  const imageKeys = new WeakMap();
  let nextImageKey = 1;
  let manualActive = null;
  let manualScrollHandler = null;
  let manualKeyHandler = null;
  let manualDebounceTimer = 0;
  let manualWatchdogTimer = 0;
  let programmaticScroll = false;
  let manualRootBaseline = null;
  let manualRootMoved = false;
  let overlayCleanupTimer = 0;

  const { resolveScrollMode } = globalThis.__BlogShotScrollRoot;

  function removeManualListeners() {
    if (manualScrollHandler) {
      // 监听恒挂 window 捕获阶段（改绑只换 scrollRoot 变量，不动挂载点），摘除需带 capture。
      window.removeEventListener("scroll", manualScrollHandler, { capture: true });
      manualScrollHandler = null;
    }
    manualRootBaseline = null;
    manualRootMoved = false;
    if (manualKeyHandler) {
      window.removeEventListener("keydown", manualKeyHandler);
      manualKeyHandler = null;
    }
    if (manualDebounceTimer) {
      window.clearTimeout(manualDebounceTimer);
      manualDebounceTimer = 0;
    }
    if (manualWatchdogTimer) {
      window.clearInterval(manualWatchdogTimer);
      manualWatchdogTimer = 0;
    }
    manualActive = null;
  }

  /** PixPin 式手动滚动：滚动停顿 ~450ms 后通知 worker 采集当前屏。 */
  function scheduleManualIdle() {
    if (!manualActive || manualActive.finishing || programmaticScroll) return;
    if (manualDebounceTimer) window.clearTimeout(manualDebounceTimer);
    manualDebounceTimer = window.setTimeout(() => {
      manualDebounceTimer = 0;
      if (!manualActive || manualActive.finishing || programmaticScroll) return;
      chrome.runtime.sendMessage({ type: "blog.shot.scroll-idle", scrollY: scrollPosition() }).catch(() => undefined);
    }, 450);
  }

  async function notifyManual(message) {
    try {
      const response = await chrome.runtime.sendMessage(message);
      if (response?.ok === false && manualActive) {
        api.finish({ ok: false, note: response.detail ?? "截图会话已中断，请重新截取。" });
      }
    } catch {
      if (manualActive) api.finish({ ok: false, note: "扩展后台失去连接，请重新截取。" });
    }
  }

  /** 迷你 HUD 可拖动：按住非按钮区域拖动，避免遮住要截取的内容。 */
  function enableHudDrag(host, panel) {
    panel.addEventListener("pointerdown", (event) => {
      if (event.target.closest("button")) return;
      const rect = host.getBoundingClientRect();
      const offsetX = event.clientX - rect.left;
      const offsetY = event.clientY - rect.top;
      host.style.right = "auto";
      host.style.bottom = "auto";
      const move = (e) => {
        const x = Math.max(0, Math.min(window.innerWidth - rect.width, e.clientX - offsetX));
        const y = Math.max(0, Math.min(window.innerHeight - 40, e.clientY - offsetY));
        host.style.left = `${x}px`;
        host.style.top = `${y}px`;
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      event.preventDefault();
    });
  }

  function stableImageKey(image) {
    const source = image.currentSrc || image.src;
    const old = imageKeys.get(image);
    if (old?.source === source) return old.key;
    const key = String(nextImageKey++);
    imageKeys.set(image, { source, key });
    return key;
  }

  /** 代码块稳定 key：WeakMap 与图片共用机制，跨视口采集保持同一 key 以便跨屏合并。 */
  function stableCodeKey(block) {
    const old = imageKeys.get(block);
    if (old) return old.key;
    const key = `code-${String(nextImageKey++)}`;
    imageKeys.set(block, { source: "code", key });
    return key;
  }

  function restoreNavigation() {
    for (const [element, visibility] of hiddenNavigation.splice(0)) element.style.visibility = visibility;
  }

  function scrollPosition() {
    const physical = scrollRoot ? scrollRoot.scrollTop : window.scrollY;
    if (!selectedBand) return physical;
    return physical + selectedBand.top - scrollViewport().top;
  }

  function scrollViewport() {
    if (!scrollRoot) return { top: 0, bottom: window.innerHeight };
    const rect = scrollRoot.getBoundingClientRect();
    const top = Math.max(0, rect.top + scrollRoot.clientTop);
    return { top, bottom: Math.min(window.innerHeight, rect.top + scrollRoot.clientTop + scrollRoot.clientHeight) };
  }

  function findScrollRoot(clientX, clientY) {
    // 框选层盖住网页；hit test 时临时穿透它，找到正文的滚动容器。
    const picker = document.getElementById(WIDTH_PICKER_ID);
    if (picker) picker.style.pointerEvents = "none";
    let element = document.elementFromPoint(clientX, clientY);
    if (picker) picker.style.pointerEvents = "";
    // 判定交给纯函数 resolveScrollMode：窗口可滚时优先窗口模式（防止 <pre> 代码块
    // 这类小可滚容器抢 root），窗口不可滚时按尺寸护栏选贴近视口的主容器。
    const ancestors = [];
    const elements = [];
    for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
      if (node === document.body && document.scrollingElement !== document.body) continue;
      const style = getComputedStyle(node);
      ancestors.push({ clientHeight: node.clientHeight, scrollHeight: node.scrollHeight, overflowY: style.overflowY });
      elements.push(node);
    }
    const picked = resolveScrollMode({
      scrollingElementScrollHeight: document.scrollingElement.scrollHeight,
      innerHeight: window.innerHeight,
      ancestors,
    });
    return picked >= 0 ? elements[picked] : null;
  }

  function hideFloatingNavigation() {
    if (!selectedBand) return;
    for (const element of document.querySelectorAll("header, nav, [role='navigation']")) {
      if (element.closest(`#${OVERLAY_HOST_ID}`)) continue;
      const style = getComputedStyle(element);
      if (style.position !== "fixed" && style.position !== "sticky") continue;
      const rect = element.getBoundingClientRect();
      if (rect.right <= selectedBand.left || rect.left >= selectedBand.right ||
          rect.bottom <= selectedBand.top || rect.top >= selectedBand.bottom) continue;
      hiddenNavigation.push([element, element.style.visibility]);
      element.style.visibility = "hidden";
    }
  }

  function removeOverlay() {
    if (overlayCleanupTimer) {
      window.clearTimeout(overlayCleanupTimer);
      overlayCleanupTimer = 0;
    }
    document.getElementById(OVERLAY_HOST_ID)?.remove();
    document.getElementById(WIDTH_PICKER_ID)?.remove();
    restoreNavigation();
    selectedBand = null;
  }

  /**
   * 等待滚动真正稳定：位置连续 180ms 不变，或到 3s 截止。
   * 平滑滚动（scroll-behavior:smooth）、滚动劫持库（Lenis 等）的动画
   * 可能超过任何固定时限，按"位置稳定"判断而不是按时间猜。
   */
  function waitForScrollSettle(timeoutMs = 3000) {
    return new Promise((resolve) => {
      let last = scrollPosition();
      let stableSince = Date.now();
      const deadline = Date.now() + timeoutMs;
      const timer = window.setInterval(() => {
        const now = scrollPosition();
        if (now !== last) {
          last = now;
          stableSince = Date.now();
        }
        if (Date.now() - stableSince >= 180 || Date.now() >= deadline) {
          window.clearInterval(timer);
          resolve(scrollPosition());
        }
      }, 100);
    });
  }

  /** 只读取当前截屏相交的已加载 <img> 几何，不读取图片 URL 或页面正文。 */
  function insideFloatingChrome(image) {
    if (image.closest("header, nav, [role='navigation'], aside, [role='complementary']")) return true;
    for (let element = image; element && element !== document.documentElement; element = element.parentElement) {
      const position = getComputedStyle(element).position;
      if (position === "fixed" || position === "sticky") return true;
    }
    return false;
  }

  /** 代码块（<pre>）候选：DOM 级精确识别，OCR 会把代码打乱，代码块按原图保留。 */
  function visibleCodeCandidates(viewport, viewportHeight) {
    return Array.from(document.querySelectorAll("pre"))
      .map((block) => {
        if (insideFloatingChrome(block)) return null;
        const style = getComputedStyle(block);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0 ||
            style.position === "fixed" || style.position === "sticky") return null;
        const rect = block.getBoundingClientRect();
        const x = Math.max(selectedBand?.left ?? 0, rect.left);
        const y = Math.max(viewport.top, rect.top);
        const right = Math.min(selectedBand?.right ?? window.innerWidth, rect.right);
        const bottom = Math.min(viewport.bottom, rect.bottom);
        // 过小的 pre 多是行内样式残留；代码块至少要有可读宽度。
        if (right - x < 80 || bottom - y < 24) return null;
        const pageTop = scrollPosition() + rect.top - viewport.top;
        return {
          key: stableCodeKey(block),
          x: x / window.innerWidth,
          y: (y - viewport.top) / viewportHeight,
          width: (right - x) / window.innerWidth,
          height: (bottom - y) / viewportHeight,
          fullX: Math.max(0, Math.min(1, rect.left / window.innerWidth)),
          fullY: Math.max(0, Math.min(30_000, pageTop)),
          fullWidth: Math.max(0, Math.min(1, rect.width / window.innerWidth)),
          fullHeight: Math.max(0, Math.min(30_000, rect.height)),
          // 代码块永远按完整可见对待（不受图标/悬浮逻辑降级），智能确认会自动接受。
          priority: 2,
          kind: "code",
        };
      })
      .filter(Boolean);
  }

  function visibleImageCandidates() {
    const viewport = selectedBand
      ? { top: selectedBand.top, bottom: selectedBand.bottom }
      : scrollViewport();
    const viewportHeight = viewport.bottom - viewport.top;
    const candidates = Array.from(document.images)
      .filter((image) => image.complete && image.naturalWidth >= 80 && image.naturalHeight >= 60)
      .map((image) => {
        if (insideFloatingChrome(image)) return null;
        const style = getComputedStyle(image);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0 ||
            style.position === "fixed" || style.position === "sticky") return null;
        const rect = image.getBoundingClientRect();
        const x = Math.max(selectedBand?.left ?? 0, rect.left);
        const y = Math.max(viewport.top, rect.top);
        const right = Math.min(selectedBand?.right ?? window.innerWidth, rect.right);
        const bottom = Math.min(viewport.bottom, rect.bottom);
        // 允许长图在视口边缘露出的薄片进入候选；仅过滤几乎没有像素的接触。
        if (right - x < 12 || bottom - y < 2) return null;
        const area = Math.max(1, (rect.width || 0) * (rect.height || 0));
        const chrome = insideFloatingChrome(image);
        const likelyIcon = rect.width < 48 || rect.height < 36 || area < 2_400;
        const pageTop = scrollPosition() + rect.top - viewport.top;
        return {
          key: stableImageKey(image),
          x: x / window.innerWidth,
          y: (y - viewport.top) / viewportHeight,
          width: (right - x) / window.innerWidth,
          height: (bottom - y) / viewportHeight,
          // 完整元素矩形与实际截图片段分开；全部为有界数字，不传 DOM/URL。
          fullX: Math.max(0, Math.min(1, rect.left / window.innerWidth)),
          fullY: Math.max(0, Math.min(30_000, pageTop)),
          fullWidth: Math.max(0, Math.min(1, rect.width / window.innerWidth)),
          fullHeight: Math.max(0, Math.min(30_000, rect.height)),
          priority: chrome || likelyIcon ? 0 : (bottom - y < 60 ? 1 : 2),
        };
      })
      .filter(Boolean)
      .sort((a, b) => b.priority - a.priority || a.y - b.y || a.x - b.x);
    // 代码块候选与图片候选合并；与图片矩形高度重叠的代码框（罕见）跳过，避免双份候选。
    const codeCandidates = visibleCodeCandidates(viewport, viewportHeight)
      .filter((code) => !candidates.some((image) => {
        const overlapX = Math.max(0, Math.min(image.x + image.width, code.x + code.width) - Math.max(image.x, code.x));
        const overlapY = Math.max(0, Math.min(image.y + image.height, code.y + code.height) - Math.max(image.y, code.y));
        return overlapX * overlapY / Math.max(1e-9, code.width * code.height) >= 0.5;
      }));
    // 每屏候选上限（图片+代码块）：与 shot-protocol.normalizeImageCandidates、站点接收端同一契约。
    const merged = [...candidates, ...codeCandidates]
      .sort((a, b) => b.priority - a.priority || a.y - b.y || a.x - b.x);
    return { items: merged.slice(0, 60), omitted: Math.max(0, merged.length - 60) };
  }

  /**
   * 一次拖框确定长图的固定截取窗口。拖框后的上下左右边界均生效；
   * 用户在框内滚动时，只采集这个矩形里的新内容。
   */
  function pickWidth(onSelected) {
    document.getElementById(WIDTH_PICKER_ID)?.remove();
    const picker = document.createElement("div");
    picker.id = WIDTH_PICKER_ID;
    picker.style.cssText = "position:fixed;inset:0;z-index:2147483646;cursor:crosshair;background:rgba(0,0,0,.30);touch-action:none;user-select:none;";
    // 框选期间隐藏扩展面板：面板浮在 picker 之上会挡住要选的正文区域。
    const overlayHost = document.getElementById(OVERLAY_HOST_ID);
    const wasVisible = overlayHost ? overlayHost.style.visibility : "";
    if (overlayHost) overlayHost.style.visibility = "hidden";
    const hint = document.createElement("div");
    hint.textContent = "在网页正文上拖出完整截图框：上下左右边界都会保留（Esc 取消）";
    hint.style.cssText = "position:absolute;left:16px;bottom:16px;padding:8px 12px;border-radius:6px;background:#fff;color:#1f2328;font:13px system-ui,sans-serif;";
    const band = document.createElement("div");
    band.style.cssText = "display:none;position:absolute;border:2px solid #1f6f54;background:rgba(255,255,255,.22);pointer-events:none;box-sizing:border-box;";
    picker.append(band, hint);
    document.documentElement.append(picker);
    let startX = null;
    let startClientY = null;
    const cleanup = () => {
      picker.remove();
      window.removeEventListener("keydown", onKey);
      if (overlayHost) overlayHost.style.visibility = wasVisible;
    };
    const onKey = (event) => { if (event.key === "Escape") cleanup(); };
    window.addEventListener("keydown", onKey);
    picker.addEventListener("pointerdown", (event) => {
      startX = event.clientX;
      startClientY = event.clientY;
      picker.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    picker.addEventListener("pointermove", (event) => {
      if (startX === null) return;
      const left = Math.max(0, Math.min(startX, event.clientX));
      const right = Math.min(window.innerWidth, Math.max(startX, event.clientX));
      const top = Math.max(0, Math.min(startClientY, event.clientY));
      const bottom = Math.min(window.innerHeight, Math.max(startClientY, event.clientY));
      band.style.display = "block";
      band.style.left = `${left}px`;
      band.style.width = `${right - left}px`;
      band.style.top = `${top}px`;
      band.style.height = `${bottom - top}px`;
    });
    picker.addEventListener("pointerup", (event) => {
      if (startX === null) return;
      const left = Math.max(0, Math.min(startX, event.clientX));
      const right = Math.min(window.innerWidth, Math.max(startX, event.clientX));
      const topClient = Math.min(startClientY, event.clientY);
      const bottomClient = Math.max(startClientY, event.clientY);
      const middleClient = (startClientY + event.clientY) / 2;
      startX = null;
      startClientY = null;
      if (right - left < 120 || bottomClient - topClient < 120) {
        hint.textContent = "截图框宽和高都至少 120px，请重新拖框";
        band.style.display = "none";
        return;
      }
      // 正文上可能覆盖按钮/卡片；先从框上缘命中滚动容器，再尝试中心与下缘。
      const hitX = (left + right) / 2;
      const root = findScrollRoot(hitX, Math.min(window.innerHeight - 1, topClient + 10))
        ?? findScrollRoot(hitX, Math.min(window.innerHeight - 1, Math.max(0, middleClient)))
        ?? findScrollRoot(hitX, Math.min(window.innerHeight - 1, bottomClient - 10));
      cleanup();
      onSelected({ left, right, topClient, bottomClient, root });
    });
  }

  function ensureOverlay() {
    let host = document.getElementById(OVERLAY_HOST_ID);
    if (host) return host.shadowRoot;
    host = document.createElement("div");
    host.id = OVERLAY_HOST_ID;
    host.style.cssText = "position:fixed;top:12px;right:12px;z-index:2147483647;";
    const shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = `
      .panel { all: initial; display:block; font: 13px/1.5 system-ui, sans-serif; color:#1f2328;
               background:#ffffff; border:1px solid #d0d7de; border-radius:8px; padding:12px 14px;
               width: 300px; box-shadow: 0 4px 16px rgba(0,0,0,.15); }
      .panel h3 { all:initial; display:block; font: 700 13px/1.4 system-ui, sans-serif; margin:0 0 6px; }
      .panel p { all:initial; display:block; margin:4px 0; font: 12px/1.5 system-ui, sans-serif; }
      .panel .muted { color:#57606a; }
      .panel button { all:initial; display:inline-block; cursor:pointer; margin:6px 6px 0 0; padding:5px 12px;
                      border:1px solid #d0d7de; border-radius:6px; font: 600 12px/1.4 system-ui, sans-serif; background:#f6f8fa; }
      .panel button.primary { background:#1f6f54; border-color:#1f6f54; color:#fff; }
      .panel button:disabled { opacity:.5; cursor:default; }
      .panel .progress { height:6px; background:#eaeef2; border-radius:3px; margin-top:8px; overflow:hidden; }
      .panel .progress > i { display:block; height:100%; background:#1f6f54; transition: width .2s; }
      .band-guide { position:fixed;border:2px dashed #1f6f54;box-sizing:border-box;
                     background:rgba(31,111,84,.06);pointer-events:none; }
      .panel.compact { width: 240px; padding: 8px 10px; opacity: .94; cursor: grab; }
      .panel.compact h3 { font: 700 12px/1.3 system-ui, sans-serif; margin: 0 0 2px; }
      .panel.compact p { margin: 2px 0; font: 11px/1.4 system-ui, sans-serif; }
      .shot-preview { width: 170px; max-height: 230px; min-height: 36px; margin: 7px auto;
                      overflow-y: auto; background: #f4f6f5; border: 1px solid #d0d7de;
                      border-radius: 5px; overscroll-behavior: contain; }
      .shot-preview:empty::before { content: "截图预览将在这里逐段出现"; display:block;
                                     padding: 8px; color:#57606a; font: 11px/1.4 system-ui,sans-serif; }
      .shot-preview img { display:block; width:100%; height:auto; margin:0; }
    `;
    const panel = document.createElement("div");
    panel.className = "panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "博客长截图采集");
    shadow.append(style, panel);
    document.documentElement.append(host);
    return shadow;
  }

  function renderPanel(html) {
    const shadow = ensureOverlay();
    document.getElementById(OVERLAY_HOST_ID).style.visibility = "visible";
    shadow.querySelector(".panel").innerHTML = html;
    return shadow.querySelector(".panel");
  }

  const api = {
    /** 当前几何信息；不读取任何页面文本内容。 */
    geometry() {
      const doc = document.documentElement;
      const viewport = selectedBand
        ? { top: selectedBand.top, bottom: selectedBand.bottom }
        : scrollViewport();
      return {
        pageHeight: scrollRoot?.scrollHeight ?? Math.max(doc.scrollHeight, document.body?.scrollHeight ?? 0),
        viewportWidth: window.innerWidth,
        viewportHeight: viewport.bottom - viewport.top,
        screenHeight: window.innerHeight,
        captureTop: viewport.top,
        scrollX: window.scrollX,
        scrollY: scrollPosition(),
        dpr: window.devicePixelRatio || 1,
        url: location.href,
        title: document.title.slice(0, 200),
      };
    },

    /** 长页模式第一步：确认面板。startY/endY 由用户滚动后点击按钮确定。 */
    showPlanner(info) {
      // 上一次 MV3 worker 失联后重开时，清掉旧 HUD/监听器和旧选区。
      removeManualListeners();
      removeOverlay();
      scrollRoot = null;
      originalScroll = { x: info.originScrollX ?? window.scrollX, y: info.originScrollY ?? window.scrollY };
      selectedBand = null;
      const panel = renderPanel(`
        <h3>${info.saveMode ? "长截图 · 保存图片到本机" : "博客长截图"}</h3>
        <p class="muted">在正文上框选完整截图区域，四条边都是截图边界。滚动后只拼接框内的新内容。</p>
        <p>当前测得页面高度：<b data-shot="page-height">${info.pageHeight}px</b>（滚动加载后可能增长） · 视口 <b data-shot="viewport">${info.viewportHeight}px</b></p>
        <p class="muted">1. 点击按钮在正文内拖一个框；松开鼠标自动截第一屏；<br>2. 自己向下滚动所框正文，小窗实时显示已截内容；<br>3. 截够后点小窗“完成”，${info.saveMode ? "长图会保存到下载目录，不会打开博客。" : "才会打开博客。"}</p>
        <p data-shot="width" class="muted">截图区域：尚未选择</p>
        <p data-shot="range" class="muted">已选范围：尚未设置</p>
        <button type="button" data-shot="pick-width" class="primary">框选截图区域</button>
        <button type="button" data-shot="cancel">取消</button>
        <p class="muted">上限：30 个视口 / 约 30000px / 20MiB。</p>
      `);
      let startY = null;
      const startCapture = () => {
        if (!selectedBand) return;
        const geo = api.geometry();
        api.beginManualHud({ startY: Math.max(0, startY ?? 0) });
        void notifyManual({
          type: "blog.shot.plan-ready",
          startY: Math.max(0, startY ?? 0),
          initialScrollY: geo.scrollY,
          endY: geo.pageHeight,
          viewportWidth: geo.viewportWidth,
          viewportHeight: geo.viewportHeight,
          screenHeight: geo.screenHeight,
          dpr: geo.dpr,
          captureTop: geo.captureTop,
          originScrollY: originalScroll.y,
          originScrollX: originalScroll.x,
          selection: {
            left: selectedBand.left / window.innerWidth,
            right: selectedBand.right / window.innerWidth,
            top: Math.max(0, startY ?? 0),
            bottom: geo.pageHeight,
          },
        });
      };
      panel.querySelector('[data-shot="pick-width"]').addEventListener("click", () => pickWidth((band) => {
        scrollRoot = band.root;
        originalRootScroll = scrollRoot?.scrollTop ?? 0;
        const viewport = scrollViewport();
        const top = Math.max(band.topClient, viewport.top);
        const bottom = Math.min(band.bottomClient, viewport.bottom);
        if (bottom - top < 120) {
          scrollRoot = null;
          panel.querySelector('[data-shot="range"]').textContent = "截图框需在正文滚动区域内且至少高 120px，请重新框选";
          return;
        }
        selectedBand = { left: band.left, right: band.right, top, bottom };
        startY = Math.max(0, Math.round(scrollPosition()));
        panel.querySelector('[data-shot="width"]').textContent = `截图框：${Math.round(band.right - band.left)} × ${Math.round(bottom - top)}px`;
        panel.querySelector('[data-shot="range"]').textContent = `框内起点 ${Math.round(startY)}px，${scrollRoot ? "正文容器" : "页面"}滚动；完成后点“完成”`;
        const guide = ensureOverlay().querySelector(".band-guide") ?? document.createElement("div");
        guide.className = "band-guide";
        guide.style.left = `${band.left}px`;
        guide.style.width = `${band.right - band.left}px`;
        guide.style.top = `${top}px`;
        guide.style.height = `${bottom - top}px`;
        ensureOverlay().append(guide);
        startCapture();
      }));
      panel.querySelector('[data-shot="cancel"]').addEventListener("click", () => {
        removeOverlay();
        api.restore();
        window.__BLOG_SHOT_CONTENT__.notifyWorker({ type: "blog.shot.plan-cancelled" });
      });
    },

    showProgress({ current, total, note }) {
      restoreNavigation();
      const shadow = ensureOverlay();
      document.getElementById(OVERLAY_HOST_ID).style.visibility = "visible";
      const panel = shadow.querySelector(".panel");
      const percent = total ? Math.min(100, Math.round(((current ?? 0) / total) * 100)) : 30;
      panel.innerHTML = `
        <h3>博客长截图</h3>
        <p data-shot="status"></p>
        <div class="progress"><i style="width:${percent}%"></i></div>
        <p class="muted">请保持本标签页在前台，不要手动滚动。</p>
        <button type="button" data-shot="cancel">取消</button>
      `;
      panel.querySelector('[data-shot="status"]').textContent = `${note ?? ""}${total ? `（${current}/${total}）` : ""}`;
      panel.querySelector('[data-shot="cancel"]').addEventListener("click", () => {
        window.__BLOG_SHOT_CONTENT__.notifyWorker({ type: "blog.shot.capture-cancelled" });
      });
    },

    finish({ ok, note }) {
      removeManualListeners();
      const shadow = ensureOverlay();
      document.getElementById(OVERLAY_HOST_ID).style.visibility = "visible";
      const panel = shadow.querySelector(".panel");
      panel.innerHTML = ok ? "<h3>博客长截图</h3><p></p>" :
        '<h3>博客长截图失败</h3><p></p><button type="button" data-shot="dismiss">关闭提示</button>';
      panel.querySelector("p").textContent = note ?? (ok ? "已完成，正在打开博客…" : "已停止。");
      if (ok) overlayCleanupTimer = window.setTimeout(removeOverlay, 4000);
      else panel.querySelector('[data-shot="dismiss"]').addEventListener("click", removeOverlay);
    },

    /** PixPin 式手动滚动模式：右下角迷你 HUD（可拖动），滚动即采集。 */
    beginManualHud({ startY }) {
      manualActive = { startY };
      const shadow = ensureOverlay();
      const host = document.getElementById(OVERLAY_HOST_ID);
      host.style.visibility = "visible";
      host.style.top = "auto";
      host.style.left = "auto";
      host.style.right = "12px";
      host.style.bottom = "12px";
      const panel = shadow.querySelector(".panel");
      panel.classList.add("compact");
      panel.innerHTML = `
        <h3>博客长截图 · 手动滚动</h3>
        <p data-shot="hud-status">正在截取第一屏…</p>
        <div class="shot-preview" data-shot="preview" aria-label="已截长图预览"></div>
        <button type="button" data-shot="manual-finish" class="primary">完成</button>
        <button type="button" data-shot="manual-cancel">取消</button>
      `;
      enableHudDrag(host, panel);
      panel.querySelector('[data-shot="manual-finish"]').disabled = true;
      panel.querySelector('[data-shot="manual-finish"]').addEventListener("click", () => {
        if (!manualActive || manualActive.finishing) return;
        manualActive.finishing = true;
        panel.querySelector('[data-shot="hud-status"]').textContent = "正在拼接并打开博客…";
        for (const button of panel.querySelectorAll("button")) button.disabled = true;
        notifyManual({ type: "blog.shot.manual-finish", scrollY: scrollPosition() });
      });
      panel.querySelector('[data-shot="manual-cancel"]').addEventListener("click", () => {
        removeManualListeners();
        removeOverlay();
        notifyManual({ type: "blog.shot.capture-cancelled" });
      });
      // scroll 事件不冒泡，但会出现在 window 的捕获阶段：全局捕获监听能听到
      // 任何容器的滚动，根治「监听挂错元素导致用户滚动时采集不动」的缺陷。
      manualRootBaseline = scrollPosition();
      manualRootMoved = false;
      manualScrollHandler = (event) => {
        if (!manualActive || programmaticScroll) return;
        const position = scrollPosition();
        if (manualRootBaseline == null) manualRootBaseline = position;
        if (position !== manualRootBaseline) manualRootMoved = true;
        // tracked root 从未滚动而事件来自别的元素：说明会话开始时 root 判定错了
        // （此时此前 tile 的坐标空间本来就不对），改绑到真正滚动的容器
        // （target 为 document 即窗口模式），并通知后台把截图标记为需人工核对。
        const target = event.target;
        if (!manualRootMoved && target && target !== scrollRoot) {
          const nextRoot = target.nodeType === 1 ? target : null;
          if ((nextRoot ?? null) !== scrollRoot) {
            scrollRoot = nextRoot;
            originalRootScroll = scrollRoot?.scrollTop ?? 0;
            manualRootBaseline = scrollPosition();
            manualRootMoved = false;
            chrome.runtime.sendMessage({ type: "blog.shot.root-retargeted" }).catch(() => undefined);
          }
        }
        scheduleManualIdle();
      };
      window.addEventListener("scroll", manualScrollHandler, { capture: true, passive: true });
      manualKeyHandler = (event) => {
        if (event.key === "Escape") panel.querySelector('[data-shot="manual-finish"]').click();
      };
      window.addEventListener("keydown", manualKeyHandler);
      // MV3 worker 可能在长时间暂停时重启；让 HUD 显示可恢复错误，避免永久等待。
      manualWatchdogTimer = window.setInterval(async () => {
        if (!manualActive) return;
        try {
          const response = await chrome.runtime.sendMessage({ type: "blog.shot.status" });
          if (manualActive && (!response?.ok || !response.active)) {
            api.finish({ ok: false, note: "截图会话已中断，请重新截取。" });
          }
        } catch {
          if (manualActive) api.finish({ ok: false, note: "扩展后台失去连接，请重新截取。" });
        }
      }, 5000);
    },

    showManualStatus({ status, ready = true, previewDataUrl }) {
      if (!manualActive) return;
      // 恢复被隐藏的导航悬浮元素，用户在两次采集之间看到的是正常页面。
      restoreNavigation();
      const shadow = ensureOverlay();
      document.getElementById(OVERLAY_HOST_ID).style.visibility = "visible";
      const statusEl = shadow.querySelector('[data-shot="hud-status"]');
      if (statusEl) statusEl.textContent = status;
      if (typeof previewDataUrl === "string" && previewDataUrl.startsWith("data:image/jpeg;base64,")) {
        const preview = shadow.querySelector('[data-shot="preview"]');
        if (preview) {
          const image = document.createElement("img");
          image.src = previewDataUrl;
          image.alt = `已截第 ${preview.children.length + 1} 段`;
          preview.append(image);
          preview.scrollTop = preview.scrollHeight;
        }
      }
      const finishButton = shadow.querySelector('[data-shot="manual-finish"]');
      if (finishButton && ready && !manualActive.finishing) finishButton.disabled = false;
    },

    async prepareCapture() {
      const overlay = document.getElementById(OVERLAY_HOST_ID);
      if (overlay) overlay.style.visibility = "hidden";
      hideFloatingNavigation();
      // 等待隐藏样式真正绘制，避免把本扩展的进度面板截进正文。
      // 注意：标签页被遮挡/最小化时 rAF 永不触发，必须加超时兜底，否则采集死等。
      await new Promise((resolve) => {
        let settled = false;
        const done = () => {
          if (settled) return;
          settled = true;
          window.clearTimeout(fallbackTimer);
          resolve(null);
        };
        const fallbackTimer = window.setTimeout(done, 120);
        requestAnimationFrame(() => requestAnimationFrame(done));
      });
      // 候选是辅助元数据：任何异常都降级为空候选，绝不能让整屏采集失败。
      let imageResult = { items: [], omitted: 0 };
      try {
        imageResult = visibleImageCandidates();
      } catch (cause) {
        console.warn("[博客剪藏] 图片/代码块候选采集失败，本屏继续截取：", cause);
      }
      return { scrollX: window.scrollX, scrollY: scrollPosition(), imageCandidates: imageResult.items,
        imageCandidateOverflow: imageResult.omitted };
    },

    restore() {
      restoreNavigation();
      const root = scrollRoot ?? document.documentElement;
      const previousBehavior = root.style.scrollBehavior;
      root.style.scrollBehavior = "auto";
      try {
        if (scrollRoot?.isConnected) scrollRoot.scrollTop = originalRootScroll;
        window.scrollTo(originalScroll.x, originalScroll.y);
      } finally {
        root.style.scrollBehavior = previousBehavior;
      }
    },

    async scrollTo(y) {
      // 中和页面的 CSS 平滑滚动：采集需要瞬时定位，不想要动画追赶。
      const root = scrollRoot ?? document.documentElement;
      const previousBehavior = root.style.scrollBehavior;
      root.style.scrollBehavior = "auto";
      programmaticScroll = true;
      if (manualDebounceTimer) {
        window.clearTimeout(manualDebounceTimer);
        manualDebounceTimer = 0;
      }
      try {
        let actual = scrollPosition();
        for (let attempt = 0; attempt < 3; attempt += 1) {
          const physicalY = selectedBand ? y - selectedBand.top + scrollViewport().top : y;
          if (scrollRoot) scrollRoot.scrollTo(0, physicalY);
          else window.scrollTo(0, physicalY);
          actual = await waitForScrollSettle();
          if (Math.abs(actual - y) <= 1) break;
        }
        return actual;
      } finally {
        programmaticScroll = false;
        root.style.scrollBehavior = previousBehavior;
      }
    },

    hide() {
      removeManualListeners();
      removeOverlay();
    },

    notifyWorker(message) {
      chrome.runtime.sendMessage(message).catch(() => undefined);
    },
  };

  window.__BLOG_SHOT_CONTENT__ = api;

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || typeof message.type !== "string" || !message.type.startsWith("blog.shot.")) return;
    (async () => {
      switch (message.type) {
        case "blog.shot.ping":
          sendResponse({ ok: true });
          break;
        case "blog.shot.geometry":
          sendResponse({ ok: true, geometry: api.geometry() });
          break;
        case "blog.shot.show-planner":
          api.showPlanner(message);
          sendResponse({ ok: true });
          break;
        case "blog.shot.show-progress":
          api.showProgress(message);
          sendResponse({ ok: true });
          break;
        case "blog.shot.show-manual-status":
          api.showManualStatus(message);
          sendResponse({ ok: true });
          break;
        case "blog.shot.scroll-to": {
          const actual = await api.scrollTo(message.y);
          sendResponse({ ok: true, actual });
          break;
        }
        case "blog.shot.prepare-capture":
          sendResponse({ ok: true, position: await api.prepareCapture() });
          break;
        case "blog.shot.restore":
          api.restore();
          sendResponse({ ok: true });
          break;
        case "blog.shot.finish":
          api.finish(message);
          sendResponse({ ok: true });
          break;
        case "blog.shot.hide":
          api.hide();
          sendResponse({ ok: true });
          break;
        default:
          sendResponse({ ok: false, code: "wrong_type" });
      }
    })();
    return true;
  });
})();
