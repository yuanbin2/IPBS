/**
 * 长截图滚动容器判定：与 content script 共用的纯函数，不依赖 DOM，
 * 可在 Node 单测（tests/scroll-root.test.js）。
 *
 * 经典脚本环境（content script 注入）挂到 globalThis.__BlogShotScrollRoot；
 * Node 测试环境走 CommonJS 导出。注入顺序：本文件先于 shot-content.js。
 */
(() => {
  /**
   * 判定滚动模式。返回 -1 表示窗口模式（content script 里 scrollRoot = null），
   * 否则返回选中容器在 ancestors 中的下标。
   *
   * 判定优先级：
   * 1. 窗口本身可滚（scrollingElement.scrollHeight > innerHeight + 16）→ 一律窗口模式。
   *    即使链上存在更小的可滚容器（如 <pre> 代码块）也不让它们抢 root——
   *    窗口模式覆盖绝大多数常规网页，这是面试鸭文章页「滚不动」缺陷的修复点。
   * 2. 窗口不可滚（SPA 内滚布局）→ 沿命中链找滚动容器，但加尺寸护栏：
   *    clientHeight ≥ 200 且 ≥ 0.5 × innerHeight，杜绝代码块/评论框这类小容器；
   *    命中多个取 clientHeight 最大者（贴近视口的主容器）。
   * 3. 链上没有合格容器 → 仍返回窗口模式（-1）。取舍：页面此时其实无处可滚，
   *    与其把监听挂在一个小容器上采出碎片，不如按窗口模式采集，宁可整段不可采
   *    也不采错坐标空间。
   */
  function resolveScrollMode({ scrollingElementScrollHeight, innerHeight, ancestors }) {
    if (scrollingElementScrollHeight > innerHeight + 16) return -1;
    let best = -1;
    for (let index = 0; index < ancestors.length; index += 1) {
      const node = ancestors[index];
      if (!/(auto|scroll|overlay)/.test(node.overflowY)) continue;
      if (node.scrollHeight <= node.clientHeight + 16) continue;
      if (node.clientHeight < 200 || node.clientHeight < innerHeight * 0.5) continue;
      if (best < 0 || node.clientHeight > ancestors[best].clientHeight) best = index;
    }
    return best;
  }

  const api = { resolveScrollMode };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else globalThis.__BlogShotScrollRoot = api;
})();
