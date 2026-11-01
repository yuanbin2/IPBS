/**
 * 聊天滚动稳定化的纯逻辑单测。
 *
 * 回归背景：MdPreview 异步渲染 markdown，nextTick 后立即滚动会停在半中间。
 * scrollWhenHeightSettles 逐帧比较 scrollHeight，稳定后再执行滚动。
 * rAF 注入为手动调度器，逐帧驱动，不依赖真实浏览器。

 * 运行：npm run test:unit
 */

import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_MAX_FRAMES,
  scrollWhenHeightSettles,
  type FrameScheduler,
} from "../src/features/chat/utils/scroll.ts";

interface ManualScheduler {
  schedule: FrameScheduler;
  /** 执行下一帧；height 不为 null 时先把容器 scrollHeight 改为该值。 */
  runFrame: (height?: number) => void;
  pending: () => number;
}

/** 手动帧调度器：rAF 只入队，由测试逐帧驱动。 */
function createManualScheduler(scroller: { scrollHeight: number }): ManualScheduler {
  const queue: Array<(time: number) => void> = [];
  const schedule: FrameScheduler = (callback) => {
    queue.push(callback);
    return queue.length;
  };
  return {
    schedule,
    pending: () => queue.length,
    runFrame: (height?: number) => {
      const callback = queue.shift();
      if (!callback) {
        throw new Error("没有待执行的帧");
      }
      if (height !== undefined) {
        scroller.scrollHeight = height;
      }
      callback(0);
    },
  };
}

function createFakeScroller(initialHeight: number) {
  return {
    scrollHeight: initialHeight,
    scrollTop: 0,
  } as unknown as HTMLElement;
}

test("scrollWhenHeightSettles：高度连续稳定后滚动到底部", async () => {
  const scroller = createFakeScroller(500);
  const scheduler = createManualScheduler(scroller);
  const pending = scrollWhenHeightSettles(scroller, { requestAnimationFrame: scheduler.schedule });

  // 帧序：首帧记录高度（稳定计数清零），第 2、3 帧连续不变后执行滚动。
  scheduler.runFrame();
  scheduler.runFrame();
  assert.equal(scroller.scrollTop, 0);
  scheduler.runFrame();

  assert.equal(await pending, true);
  assert.equal(scroller.scrollTop, 500);
});

test("scrollWhenHeightSettles：高度持续增长时按 maxFrames 兜底滚动", async () => {
  const scroller = createFakeScroller(100);
  const scheduler = createManualScheduler(scroller);
  const pending = scrollWhenHeightSettles(scroller, {
    requestAnimationFrame: scheduler.schedule,
    maxFrames: 5,
  });

  // 前 4 帧高度都在变化，永不满足稳定条件。
  scheduler.runFrame(100);
  scheduler.runFrame(300);
  scheduler.runFrame(500);
  scheduler.runFrame(700);
  assert.equal(scroller.scrollTop, 0, "未达到 maxFrames 前不应滚动");
  assert.equal(scheduler.pending(), 1);

  // 第 5 帧触发 maxFrames 兜底。
  scheduler.runFrame(900);
  assert.equal(await pending, true);
  assert.equal(scroller.scrollTop, 900);
});

test("scrollWhenHeightSettles：高度中途变化后重新计稳定帧数", async () => {
  const scroller = createFakeScroller(100);
  const scheduler = createManualScheduler(scroller);
  const pending = scrollWhenHeightSettles(scroller, { requestAnimationFrame: scheduler.schedule });

  scheduler.runFrame(100); // 首帧：记录 100，计数清零
  scheduler.runFrame(100); // 稳定 1 帧
  scheduler.runFrame(200); // 高度变化：计数重新清零
  scheduler.runFrame(200); // 稳定 1 帧
  scheduler.runFrame(200); // 稳定 2 帧 → 执行
  assert.equal(await pending, true);
  assert.equal(scroller.scrollTop, 200);
});

test("scrollWhenHeightSettles：支持自定义 action（锚点定位路径）", async () => {
  const scroller = createFakeScroller(800);
  const scheduler = createManualScheduler(scroller);
  const actions: number[] = [];
  const pending = scrollWhenHeightSettles(scroller, {
    requestAnimationFrame: scheduler.schedule,
    action: (element) => actions.push(element.scrollHeight),
  });

  scheduler.runFrame();
  scheduler.runFrame();
  scheduler.runFrame();

  assert.equal(await pending, true);
  assert.deepEqual(actions, [800]);
  assert.equal(scroller.scrollTop, 0, "默认的滚到底部动作不应执行");
});

test("scrollWhenHeightSettles：无容器时直接 resolve(false)", async () => {
  const scheduler = createManualScheduler(createFakeScroller(0));
  const result = await scrollWhenHeightSettles(null, { requestAnimationFrame: scheduler.schedule });
  assert.equal(result, false);
  assert.equal(scheduler.pending(), 0, "无容器时不应排入任何帧");
});

test("scrollWhenHeightSettles：默认配置为 30 帧上限、2 帧稳定", async () => {
  assert.equal(DEFAULT_MAX_FRAMES, 30);
});
