/**
 * 长截图本地保存的拼接几何：与博客页 stitchLongShotTiles 同一套数学，
 * 但不依赖 DOM——纯函数可在 Node 单测，canvas 通过 adapter 注入。
 *
 * 输入是截图会话记录（chrome.storage.session 里的 shot:<nonce>）：
 * { dpr, viewportWidth, viewportHeight, selection, coveredTop, coveredBottom,
 *   tiles: [{ index, scrollY, width, height, mime }] }
 * 每张 tile 都是整视口截图（设备像素），tile.scrollY 是页面 CSS 纵坐标。
 */

export const MAX_STITCH_SIDE = 20000;
export const MAX_STITCH_PIXELS = 30_000_000;

function clamp01(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.min(1, Math.max(0, n));
}

/**
 * 计算拼接画布尺寸与每张 tile 的绘制参数。
 * 抛错时 message 面向用户，可直接展示。
 */
export function computeStitchPlan(record) {
  if (!record || typeof record !== "object") throw new Error("截图会话不完整，请重新截取");
  const dpr = Number(record.dpr) > 0 ? Number(record.dpr) : 1;
  // shot 记录里视口是 viewport:{width,height}（buildShotRecord 的结构）
  const viewport = record.viewport ?? {};
  const viewportWidth = Number(record.viewportWidth ?? viewport.width) > 0 ? Number(record.viewportWidth ?? viewport.width) : 0;
  const viewportHeight = Number(record.viewportHeight ?? viewport.height) > 0 ? Number(record.viewportHeight ?? viewport.height) : 0;
  const tiles = Array.isArray(record.tiles) ? record.tiles.filter((tile) => tile && Number.isFinite(Number(tile.scrollY))) : [];
  if (!viewportWidth || !viewportHeight || tiles.length === 0) {
    throw new Error("截图会话缺少视口信息或截图分片，请重新截取");
  }

  const selection = record.selection && Number.isFinite(Number(record.selection.top)) ? record.selection : null;
  const covered = record.covered ?? {};
  const coveredTop = Math.round(Number(record.coveredTop ?? covered.top) || 0);
  const coveredBottom = Math.round(Number(record.coveredBottom ?? covered.bottom) || 0);
  const top = selection ? Math.round(Number(selection.top)) : coveredTop;
  if (!Number.isFinite(top)) throw new Error("截图范围无效，请重新截取");
  const left = selection ? clamp01(selection.left) : 0;
  const right = selection ? clamp01(selection.right) : 1;
  if (!(right > left)) throw new Error("截图区域宽度无效，请重新框选");
  const bottomCandidates = [coveredBottom || Infinity];
  if (selection && Number.isFinite(Number(selection.bottom))) bottomCandidates.push(Math.round(Number(selection.bottom)));
  const bottom = Math.round(Math.min(...bottomCandidates));
  if (!(bottom > top)) throw new Error("没有截取到有效内容，请重新截取");

  const sourceWidth = Math.round(viewportWidth * dpr);
  const sx = Math.round(left * viewportWidth * dpr);
  const sw = Math.max(1, Math.round((right - left) * viewportWidth * dpr));
  const rawHeight = Math.round((bottom - top) * dpr);
  if (rawHeight < 1) throw new Error("截图范围高度无效，请重新截取");

  const scale = Math.min(
    1,
    MAX_STITCH_SIDE / Math.max(sw, rawHeight),
    Math.sqrt(MAX_STITCH_PIXELS / (sw * rawHeight)),
  );
  const outWidth = Math.max(1, Math.round(sw * scale));
  const outHeight = Math.max(1, Math.round(rawHeight * scale));

  const ordered = [...tiles].sort((a, b) => Number(a.scrollY) - Number(b.scrollY));
  const placements = [];
  for (const tile of ordered) {
    const tileTopCss = Number(tile.scrollY);
    const tileHeightCss = Number(tile.height) / dpr;
    // 完全在截取范围外的 tile 跳过（首尾各留 1px 余量防浮点误差）
    if (tileTopCss + tileHeightCss <= top + 1 || tileTopCss >= bottom - 1) continue;
    placements.push({
      index: Number(tile.index),
      sx,
      sy: 0,
      sw,
      sh: Number(tile.height),
      dx: 0,
      dy: Math.round((tileTopCss - top) * dpr * scale),
      dw: outWidth,
      dh: Math.round(Number(tile.height) * scale),
    });
  }
  if (!placements.length) throw new Error("没有可拼接的截图分片，请重新截取");

  return { width: outWidth, height: outHeight, mime: "image/png", scale, placements };
}

/**
 * 按计划把 tiles 拼到一张画布上。adapter 注入 DOM 能力：
 * { createCanvas(w, h) → canvas, decode(bytes) → image-like,
 *   drawImage(ctx, image, sx, sy, sw, sh, dx, dy, dw, dh), toBlob(canvas, mime) → Promise<Blob> }
 */
export async function stitchShotTiles(plan, adapter) {
  if (!plan || !Array.isArray(plan.placements) || !plan.placements.length) {
    throw new Error("拼接计划为空，请重新截取");
  }
  const canvas = adapter.createCanvas(plan.width, plan.height);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("浏览器无法创建拼接画布");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, plan.width, plan.height);
  for (const placement of plan.placements) {
    const bytes = await adapter.loadTile(placement.index);
    if (!bytes) throw new Error("截图分片已丢失，请重新截取");
    const image = await adapter.decode(bytes);
    adapter.drawImage(context, image, placement);
  }
  return adapter.toBlob(canvas, plan.mime);
}
