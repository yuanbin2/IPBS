/**
 * 聊天滚动稳定化工具。
 *
 * 背景：消息正文由 md-editor-v3 的 MdPreview 组件异步渲染 markdown，
 * Vue 的 nextTick 只保证 DOM 挂载，不保证预览器把容器 scrollHeight 撑到位；
 * 若在 nextTick 后立刻滚动，会停在半中间。
 *
 * 策略：用 rAF 逐帧比较容器 scrollHeight，连续 stableFrames 帧不变
 * （或达到 maxFrames 兜底上限）后认为高度已稳定，再执行滚动动作。
 * rAF 作为参数注入，方便在 Node 单测里手动驱动帧。
 */

/** 帧调度器签名：与 requestAnimationFrame 兼容（回调带时间戳）。 */
export type FrameScheduler = (callback: (time: number) => void) => unknown;

export interface HeightSettleOptions {
  /** 帧调度器；默认浏览器 requestAnimationFrame（Node 环境回退 setTimeout）。 */
  requestAnimationFrame?: FrameScheduler;
  /** 最多比较多少帧，超过后即使高度仍在变化也执行滚动（兜底）。 */
  maxFrames?: number;
  /** scrollHeight 连续不变多少帧才视为稳定。 */
  stableFrames?: number;
  /** 高度稳定后的滚动动作；默认滚到底部（scrollTop = scrollHeight）。 */
  action?: (scroller: HTMLElement) => void;
}

export const DEFAULT_MAX_FRAMES = 30;
export const DEFAULT_STABLE_FRAMES = 2;

const scrollToBottomAction = (scroller: HTMLElement) => {
  scroller.scrollTop = scroller.scrollHeight;
};

function defaultFrameScheduler(callback: (time: number) => void): unknown {
  if (typeof requestAnimationFrame === "function") {
    return requestAnimationFrame(callback);
  }
  return setTimeout(callback, 16);
}

/**
 * 等容器高度稳定后执行滚动。
 *
 * @param scroller 滚动容器；为空时直接 resolve(false)，不执行任何动作。
 * @param options 帧调度、稳定阈值与滚动动作配置。
 * @returns Promise<boolean>：true 表示已执行滚动动作，false 表示未执行（无容器）。
 */
export function scrollWhenHeightSettles(
  scroller: HTMLElement | null | undefined,
  options: HeightSettleOptions = {}
): Promise<boolean> {
  const schedule = options.requestAnimationFrame ?? defaultFrameScheduler;
  const maxFrames = options.maxFrames ?? DEFAULT_MAX_FRAMES;
  const stableFrames = options.stableFrames ?? DEFAULT_STABLE_FRAMES;
  const action = options.action ?? scrollToBottomAction;

  return new Promise((resolve) => {
    if (!scroller) {
      resolve(false);
      return;
    }

    let lastHeight = -1;
    let stableCount = 0;
    let frameCount = 0;

    const step = () => {
      frameCount += 1;
      const height = scroller.scrollHeight;
      if (height === lastHeight) {
        stableCount += 1;
      } else {
        stableCount = 0;
        lastHeight = height;
      }
      if (stableCount >= stableFrames || frameCount >= maxFrames) {
        action(scroller);
        resolve(true);
        return;
      }
      schedule(step);
    };

    schedule(step);
  });
}
