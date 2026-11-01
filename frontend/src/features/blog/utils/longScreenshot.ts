/** 长页截图：只在浏览器内裁去选区外的页面，并按页面滚动坐标拼接。 */
export interface LongShotSelection { left: number; right: number; top: number; bottom: number }
export interface LongShotTile {
  index?: number;
  file: File;
  width: number;
  height: number;
  scrollX: number;
  scrollY: number;
  coveredCssHeight?: number;
  imageCandidates?: Array<{ key?: string; x: number; y: number; width: number; height: number;
    fullX?: number; fullY?: number; fullWidth?: number; fullHeight?: number; priority?: number; kind?: "code" }>;
}

export interface VerifiedCandidateOverlap { firstTile: number; firstCandidate: number; secondTile: number; secondCandidate: number }

function overlapKey(firstTile: number, firstCandidate: number, secondTile: number, secondCandidate: number): string {
  const a = `${firstTile}:${firstCandidate}`;
  const b = `${secondTile}:${secondCandidate}`;
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

/** Different DOM keys are joined only after comparing pixels both tiles captured in their overlap. */
export async function verifyCandidatePixelOverlaps(tiles: LongShotTile[]): Promise<VerifiedCandidateOverlap[]> {
  const verified: VerifiedCandidateOverlap[] = [];
  const bitmaps = new Map<number, ImageBitmap>();
  const inspectedGeometry = new Set<string>();
  try {
    for (let ai = 0; ai < tiles.length; ai += 1) {
      const aTile = tiles[ai]!;
      const aCss = aTile.coveredCssHeight ?? 0;
      if (aCss <= 0) continue;
      for (let bi = ai + 1; bi < tiles.length; bi += 1) {
        const bTile = tiles[bi]!;
        const bCss = bTile.coveredCssHeight ?? 0;
        if (bCss <= 0) continue;
        for (let ac = 0; ac < (aTile.imageCandidates?.length ?? 0); ac += 1) {
          const a = aTile.imageCandidates![ac]!;
          if (a.fullX === undefined || a.fullY === undefined || a.fullWidth === undefined || a.fullHeight === undefined) continue;
          for (let bc = 0; bc < (bTile.imageCandidates?.length ?? 0); bc += 1) {
            const b = bTile.imageCandidates![bc]!;
            if (a.key && b.key && a.key === b.key) continue;
            if (b.fullX === undefined || b.fullY === undefined || b.fullWidth === undefined || b.fullHeight === undefined ||
                Math.abs(a.fullX - b.fullX) > 0.012 || Math.abs(a.fullWidth - b.fullWidth) > 0.012 ||
                Math.abs(a.fullY - b.fullY) > 2 || Math.abs(a.fullHeight - b.fullHeight) > 2) continue;
            const geometryKey = `${ai}:${bi}:${a.fullX.toFixed(3)}:${a.fullY}:${a.fullWidth.toFixed(3)}:${a.fullHeight}`;
            if (inspectedGeometry.has(geometryKey)) continue;
            inspectedGeometry.add(geometryKey);
            const x0 = Math.max(a.x, b.x);
            const x1 = Math.min(a.x + a.width, b.x + b.width);
            const y0 = Math.max(aTile.scrollY + a.y * aCss, bTile.scrollY + b.y * bCss);
            const y1 = Math.min(aTile.scrollY + (a.y + a.height) * aCss, bTile.scrollY + (b.y + b.height) * bCss);
            if (x1 - x0 < 0.02 || y1 - y0 < 2) continue;
            let aBitmap: ImageBitmap;
            let bBitmap: ImageBitmap;
            try {
              aBitmap = bitmaps.get(ai) ?? await createImageBitmap(aTile.file);
              bBitmap = bitmaps.get(bi) ?? await createImageBitmap(bTile.file);
            } catch {
              continue;
            }
            bitmaps.set(ai, aBitmap);
            bitmaps.set(bi, bBitmap);
            const sample = (bitmap: ImageBitmap, tile: LongShotTile, cssHeight: number) => {
              const canvas = document.createElement("canvas");
              canvas.width = 8; canvas.height = 8;
              const context = canvas.getContext("2d", { willReadFrequently: true });
              if (!context) return null;
              const sx = Math.floor(x0 * bitmap.width);
              const sr = Math.ceil(x1 * bitmap.width);
              const sy = Math.floor(((y0 - tile.scrollY) / cssHeight) * bitmap.height);
              const sb = Math.ceil(((y1 - tile.scrollY) / cssHeight) * bitmap.height);
              context.drawImage(bitmap, sx, sy, Math.max(1, sr - sx), Math.max(1, sb - sy), 0, 0, 8, 8);
              return context.getImageData(0, 0, 8, 8).data;
            };
            const pa = sample(aBitmap, aTile, aCss);
            const pb = sample(bBitmap, bTile, bCss);
            if (!pa || !pb) continue;
            let near = 0;
            for (let p = 0; p < pa.length; p += 4) {
              const delta = Math.abs(pa[p]! - pb[p]!) + Math.abs(pa[p + 1]! - pb[p + 1]!) + Math.abs(pa[p + 2]! - pb[p + 2]!);
              if (delta <= 36) near += 1;
            }
            if (near >= 56) {
              verified.push({ firstTile: aTile.index ?? ai, firstCandidate: ac,
                secondTile: bTile.index ?? bi, secondCandidate: bc });
              if (verified.length >= 96) return verified;
            }
          }
        }
      }
    }
  } finally {
    for (const bitmap of bitmaps.values()) bitmap.close();
  }
  return verified;
}

const MAX_COMPOSITE_SIDE = 20_000;
const MAX_COMPOSITE_PIXELS = 30_000_000;

function canvasBlob(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob(
    (blob) => blob ? resolve(blob) : reject(new Error("截图拼接编码失败，请缩小范围后重试")), type, quality,
  ));
}

export async function cropLongShotTiles(
  tiles: LongShotTile[], selection: LongShotSelection, viewportHeight: number,
): Promise<LongShotTile[]> {
  if (viewportHeight <= 0 || selection.right <= selection.left || selection.bottom <= selection.top) {
    throw new Error("长截图选择范围无效");
  }
  const cropped: LongShotTile[] = [];
  for (const tile of tiles) {
    const bitmap = await createImageBitmap(tile.file);
    try {
      const start = Math.max(selection.top, tile.scrollY);
      const end = Math.min(selection.bottom, tile.scrollY + viewportHeight);
      if (end <= start) continue;
      const x = Math.max(0, Math.floor(selection.left * bitmap.width));
      const right = Math.min(bitmap.width, Math.ceil(selection.right * bitmap.width));
      const y = Math.max(0, Math.floor(((start - tile.scrollY) / viewportHeight) * bitmap.height));
      const bottom = Math.min(bitmap.height, Math.ceil(((end - tile.scrollY) / viewportHeight) * bitmap.height));
      const width = right - x;
      const height = bottom - y;
        // 选区内的薄片也可能是跨屏图片的唯一证据，不能按常规图片尺寸过滤。
        if (width < 1 || height < 1) continue;
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("浏览器无法裁剪截图");
      context.drawImage(bitmap, x, y, width, height, 0, 0, width, height);
      const blob = await canvasBlob(canvas, "image/png");
      const candidates = (tile.imageCandidates ?? []).flatMap((candidate) => {
        const cx = candidate.x * bitmap.width;
        const cy = candidate.y * bitmap.height;
        const cRight = (candidate.x + candidate.width) * bitmap.width;
        const cBottom = (candidate.y + candidate.height) * bitmap.height;
        const left = Math.max(x, cx);
        const top = Math.max(y, cy);
        const clippedRight = Math.min(right, cRight);
        const clippedBottom = Math.min(bottom, cBottom);
        if (clippedRight - left < 1 || clippedBottom - top < 1) return [];
        return [{ ...(candidate.key ? { key: candidate.key } : {}), x: (left - x) / width, y: (top - y) / height,
          width: (clippedRight - left) / width, height: (clippedBottom - top) / height,
          ...(candidate.fullY !== undefined ? { fullY: candidate.fullY, fullHeight: candidate.fullHeight,
            fullX: candidate.fullX === undefined ? undefined : (candidate.fullX * bitmap.width - x) / width,
            fullWidth: candidate.fullWidth === undefined ? undefined : candidate.fullWidth * bitmap.width / width } : {}),
          ...(candidate.priority !== undefined ? { priority: candidate.priority } : {}),
          ...(candidate.kind !== undefined ? { kind: candidate.kind } : {}) }];
      });
      cropped.push({ file: new File([blob], `long-shot-${cropped.length + 1}.png`, { type: "image/png" }),
        width, height, scrollX: 0, scrollY: start, coveredCssHeight: end - start, imageCandidates: candidates });
    } finally {
      bitmap.close();
    }
  }
  if (!cropped.length) throw new Error("选择范围没有覆盖任何截图，请重新截取");
  return cropped;
}

/** 跨屏图片在拼接长图上的合并候选框（同一 key 的多个视口片段合成一个）。 */
export interface StitchedCandidate {
  key: string;
  /** 在拼接长图上的归一化矩形（0..1，长边对应所选纵向范围）。 */
  x: number;
  y: number;
  width: number;
  height: number;
  /** 首次出现的 tile 序号，用于估算插图插入位置。 */
  tileIndex: number;
  /** 首次出现 tile 内的设备像素中心 y，供插入位置启发式使用。 */
  anchorY: number;
  origin?: "dom" | "pixels";
  confidence?: number;
  coverage?: "complete" | "partial" | "gap";
  /** 代码块候选（扩展 DOM 识别），校对区用独立样式与标签展示。 */
  kind?: "code";
  fragments?: Array<{ tileIndex: number; y: number; height: number }>;
}

/**
 * 把逐视口采集的图片候选按稳定 key 合并成拼接长图上的候选框。
 * 同一张网页图片跨屏出现在两个视口时只产生一个覆盖整图的候选，
 * 用户不再需要逐段手工拼图；无 key 的候选无法跨屏对应，忽略。
 */
export function mergeCrossTileCandidates(
  tiles: Array<{
    index: number;
    scrollY: number;
    height: number;
    coveredCssHeight?: number;
    imageCandidates?: LongShotTile["imageCandidates"];
  }>,
  selection: { top: number; bottom: number },
  viewportCssHeight?: number,
  verifiedOverlaps: VerifiedCandidateOverlap[] = [],
): StitchedCandidate[] {
  const span = selection.bottom - selection.top;
  if (!tiles.length || span <= 0) return [];
  const grouped: Array<{
    key: string; x: number; y: number; right: number; bottom: number; fullRect: boolean;
    tileIndex: number; anchorY: number; kind?: "code";
    fragments: Array<{ tileIndex: number; candidateIndex: number; y: number; bottom: number }>;
    clippedBySelection: boolean;
  }> = [];
  for (const tile of tiles) {
    const cssHeight = tile.coveredCssHeight ?? viewportCssHeight ?? 0;
    if (!cssHeight) continue;
    for (let candidateIndex = 0; candidateIndex < (tile.imageCandidates?.length ?? 0); candidateIndex += 1) {
      const candidate = tile.imageCandidates![candidateIndex]!;
      const top = candidate.fullY !== undefined && candidate.fullHeight !== undefined
        ? (candidate.fullY - selection.top) / span
        : (tile.scrollY + candidate.y * cssHeight - selection.top) / span;
      const bottom = candidate.fullY !== undefined && candidate.fullHeight !== undefined
        ? (candidate.fullY + candidate.fullHeight - selection.top) / span
        : (tile.scrollY + (candidate.y + candidate.height) * cssHeight - selection.top) / span;
      const x = candidate.fullX ?? candidate.x;
      const right = x + (candidate.fullWidth ?? candidate.width);
      const fullRect = candidate.fullY !== undefined && candidate.fullHeight !== undefined;
      const fragmentTop = (tile.scrollY + candidate.y * cssHeight - selection.top) / span;
      const fragmentBottom = (tile.scrollY + (candidate.y + candidate.height) * cssHeight - selection.top) / span;
      const existing = grouped.find((item) => Math.abs(item.x - x) < 0.025 && Math.abs(item.right - right) < 0.025 &&
        (fullRect && item.fullRect
          ? Math.abs(item.y - top) < 0.03 && Math.abs(item.bottom - bottom) < 0.03 &&
            (candidate.key === item.key || item.fragments.some((part) => fragmentTop < part.bottom && fragmentBottom > part.y &&
              verifiedOverlaps.some((pair) => overlapKey(part.tileIndex, part.candidateIndex, tile.index, candidateIndex) ===
                overlapKey(pair.firstTile, pair.firstCandidate, pair.secondTile, pair.secondCandidate))))
          : Boolean(candidate.key && item.key === candidate.key && item.fragments.some((part) => fragmentTop <= part.bottom + 0.004 && fragmentBottom >= part.y - 0.004))));
      const item = existing ?? {
        key: candidate.key ?? `fragment-${tile.index}-${grouped.length}`,
        x, y: top, right, bottom, fullRect, clippedBySelection: Boolean(fullRect &&
          (candidate.fullY! < selection.top || candidate.fullY! + candidate.fullHeight! > selection.bottom)), tileIndex: tile.index,
        anchorY: (candidate.y + candidate.height / 2) * tile.height, fragments: [],
        ...(candidate.kind !== undefined ? { kind: candidate.kind } : {}),
      };
      if (!existing) grouped.push(item);
      // Full geometry can suggest its extent, but only captured pixels count as coverage.
      item.fragments.push({ tileIndex: tile.index, candidateIndex, y: Math.max(0, fragmentTop), bottom: Math.min(1, fragmentBottom) });
      if (!fullRect) {
        item.x = Math.min(item.x, x); item.y = Math.min(item.y, fragmentTop);
        item.right = Math.max(item.right, right); item.bottom = Math.max(item.bottom, fragmentBottom);
      }
    }
  }
  const merged: StitchedCandidate[] = [];
  for (const item of grouped) {
    const x = Math.max(0, Math.min(1, item.x));
    const right = Math.max(0, Math.min(1, item.right));
    const y = Math.max(0, Math.min(1, item.y));
    const bottom = Math.max(0, Math.min(1, item.bottom));
    if (right - x <= 0 || bottom - y <= 0) continue;
    const intervals = item.fragments.slice().sort((a, b) => a.y - b.y);
    let covered = 0; let end = -1; let gap = false;
    for (const part of intervals) {
      if (part.bottom <= part.y) continue;
      if (end >= 0 && part.y > end + 0.004) gap = true;
      const start = Math.max(end, part.y);
      covered += Math.max(0, part.bottom - start);
      end = Math.max(end, part.bottom);
    }
    const coverage = gap ? "gap" : (item.clippedBySelection || !item.fullRect || covered + 0.004 < bottom - y ? "partial" : "complete");
    merged.push({ key: item.key, x, y, width: right - x, height: bottom - y,
      tileIndex: item.tileIndex, anchorY: item.anchorY, origin: "dom", confidence: item.fullRect ? 0.92 : 0.58,
      coverage, ...(item.kind !== undefined ? { kind: item.kind } : {}),
      fragments: intervals.map(({ tileIndex, y, bottom: partBottom }) => ({ tileIndex, y, height: partBottom - y })) });
  }
  return merged.sort((a, b) => a.y - b.y || a.x - b.x);
}

export async function stitchLongShotTiles(
  tiles: LongShotTile[], selection: LongShotSelection, viewportHeight: number,
): Promise<File> {
  if (!tiles.length || viewportHeight <= 0) throw new Error("没有可拼接的截图");
  const pixelsPerCssY = tiles[0].height / (tiles[0].coveredCssHeight || viewportHeight);
  const rawWidth = tiles[0].width;
  const rawHeight = (selection.bottom - selection.top) * pixelsPerCssY;
  const scale = Math.min(1, MAX_COMPOSITE_SIDE / rawWidth, MAX_COMPOSITE_SIDE / rawHeight,
    Math.sqrt(MAX_COMPOSITE_PIXELS / (rawWidth * rawHeight)));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(rawWidth * scale));
  canvas.height = Math.max(1, Math.round(rawHeight * scale));
  const context = canvas.getContext("2d");
  if (!context) throw new Error("浏览器无法创建长截图画布");
  context.fillStyle = "#fff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  for (const tile of tiles) {
    const bitmap = await createImageBitmap(tile.file);
    try {
      const y = Math.round((tile.scrollY - selection.top) * pixelsPerCssY * scale);
      context.drawImage(bitmap, 0, y, canvas.width, Math.round(bitmap.height * scale));
    } finally {
      bitmap.close();
    }
  }
  const blob = await canvasBlob(canvas, "image/jpeg", 0.92);
  return new File([blob], "long-screenshot.jpg", { type: "image/jpeg" });
}

/** Rebuild a selected stitched-figure crop from the uncapped, cropped source tiles. */
export async function cropFromOriginalTiles(
  tiles: LongShotTile[],
  selection: LongShotSelection,
  rect: { x: number; y: number; width: number; height: number },
  viewportHeight: number,
): Promise<File> {
  if (!tiles.length || viewportHeight <= 0 || rect.width <= 0 || rect.height <= 0) throw new Error("配图裁剪范围无效");
  const first = tiles[0]!;
  const density = first.height / (first.coveredCssHeight || viewportHeight);
  const pageTop = selection.top + rect.y * (selection.bottom - selection.top);
  const pageBottom = selection.top + (rect.y + rect.height) * (selection.bottom - selection.top);
  const pixelLeft = Math.floor(rect.x * first.width);
  const pixelRight = Math.ceil((rect.x + rect.width) * first.width);
  const outputWidth = pixelRight - pixelLeft;
  const outputHeight = Math.ceil((pageBottom - pageTop) * density);
  if (outputWidth < 1 || outputHeight < 1 || outputWidth * outputHeight > 20_000_000) {
    throw new Error("原始分辨率配图超过 20MP 内存上限；请缩小裁剪框后重试");
  }
  const pieces = tiles.map((tile) => ({ tile, top: Math.max(pageTop, tile.scrollY),
    bottom: Math.min(pageBottom, tile.scrollY + (tile.coveredCssHeight ?? viewportHeight)) }))
    .filter((piece) => piece.bottom > piece.top).sort((a, b) => a.top - b.top);
  let coveredTo = pageTop;
  for (const piece of pieces) {
    if (piece.top > coveredTo + 1 / density) throw new Error("配图跨屏采集存在缺口，无法生成完整裁图。请重新截取该区域，或返回校对后手动框选已覆盖部分。");
    coveredTo = Math.max(coveredTo, piece.bottom);
  }
  if (coveredTo < pageBottom - 1 / density) throw new Error("配图底部未被截图覆盖。请补截后重试，或手动框选已覆盖部分。");
  const canvas = document.createElement("canvas");
  canvas.width = outputWidth;
  canvas.height = outputHeight;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("浏览器无法重组原始截图裁剪");
  for (const { tile, top, bottom } of pieces) {
    const bitmap = await createImageBitmap(tile.file);
    try {
      const tileDensity = bitmap.height / (tile.coveredCssHeight ?? viewportHeight);
      const sourceY = Math.max(0, Math.floor((top - tile.scrollY) * tileDensity));
      const sourceBottom = Math.min(bitmap.height, Math.ceil((bottom - tile.scrollY) * tileDensity));
      const tileScaleX = bitmap.width / first.width;
      const sourceLeft = Math.max(0, Math.floor(pixelLeft * tileScaleX));
      const sourceRight = Math.min(bitmap.width, Math.ceil(pixelRight * tileScaleX));
      const destY = Math.round((top - pageTop) * density);
      const destHeight = Math.min(outputHeight - destY, Math.round((bottom - top) * density));
      context.drawImage(bitmap, sourceLeft, sourceY, sourceRight - sourceLeft, sourceBottom - sourceY,
        0, destY, outputWidth, destHeight);
    } finally { bitmap.close(); }
  }
  const blob = await canvasBlob(canvas, "image/png");
  return new File([blob], "screenshot-figure.png", { type: "image/png" });
}
