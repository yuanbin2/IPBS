/**
 * Browser-local image-region suggestions for screenshots without DOM metadata.
 * The source is scanned in bounded native-resolution tiles; this is a proposal
 * mechanism, not an image classifier.
 */
export interface PixelCandidate {
  key: string;
  x: number;
  y: number;
  width: number;
  height: number;
  confidence: number;
  origin: "pixels";
  tileIndex?: number;
  coverage?: "complete" | "partial";
}

export interface PixelScanTile {
  file: File;
  index?: number;
  scrollY: number;
  coveredCssHeight: number;
}

type PixelRect = { x: number; y: number; right: number; bottom: number; score: number; colorCells: number; segmentX: number };

const CELL = 8;
const SEGMENT_WIDTH = 1024;
const SEGMENT_HEIGHT = 512;
const SEGMENT_OVERLAP = 192;
const MAX_RESULTS = 48;
const MAX_SCAN_PIXELS = 30_000_000;

function yieldToBrowser(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function overlapsText(rect: PixelRect, boxes: Array<{ x: number; y: number; width: number; height: number }>): number {
  const area = Math.max(1, (rect.right - rect.x) * (rect.bottom - rect.y));
  // OCR boxes overlap each other in some engines, so cap their summed area.
  const covered = boxes.reduce((sum, box) => {
    const w = Math.max(0, Math.min(rect.right, box.x + box.width) - Math.max(rect.x, box.x));
    const h = Math.max(0, Math.min(rect.bottom, box.y + box.height) - Math.max(rect.y, box.y));
    return sum + w * h;
  }, 0);
  return Math.min(1, covered / area);
}

function mergeRects(rects: PixelRect[]): PixelRect[] {
  const merged: PixelRect[] = [];
  for (const rect of rects.sort((a, b) => b.score - a.score)) {
    let match = merged.find((item) => {
      const iw = Math.max(0, Math.min(item.right, rect.right) - Math.max(item.x, rect.x));
      const ih = Math.max(0, Math.min(item.bottom, rect.bottom) - Math.max(item.y, rect.y));
      const minArea = Math.min((item.right - item.x) * (item.bottom - item.y), (rect.right - rect.x) * (rect.bottom - rect.y));
      const xOverlap = iw / Math.max(1, Math.min(item.right - item.x, rect.right - rect.x));
      // Keep distinct figures apart inside one vertical scan lane. Relax horizontal
      // overlap only when different native-resolution scan lanes overlap each other.
      const sameLane = item.segmentX === rect.segmentX;
      const verticalOverlap = ih / Math.max(1, Math.min(item.bottom - item.y, rect.bottom - rect.y));
      const widthRatio = Math.max(item.right - item.x, rect.right - rect.x) / Math.max(1, Math.min(item.right - item.x, rect.right - rect.x));
      const centerShift = Math.abs((item.x + item.right - rect.x - rect.right) / 2);
      if (sameLane && verticalOverlap >= 0.65 && widthRatio > 1.25 && centerShift > Math.max(item.right - item.x, rect.right - rect.x) * 0.18) return false;
      return xOverlap >= (sameLane ? 0.66 : 0.15) && iw * ih / Math.max(1, minArea) >= 0.2;
    });
    if (!match) merged.push({ ...rect });
    else {
      match.x = Math.min(match.x, rect.x);
      match.y = Math.min(match.y, rect.y);
      match.right = Math.max(match.right, rect.right);
      match.bottom = Math.max(match.bottom, rect.bottom);
      match.score = Math.max(match.score, rect.score);
      match.colorCells += rect.colorCells;
    }
  }
  const area = (rect: PixelRect) => (rect.right - rect.x) * (rect.bottom - rect.y);
  const composites = new Set<number>();
  merged.forEach((rect, index) => {
    const rectWidth = rect.right - rect.x;
    const siblings = merged.filter((candidate, candidateIndex) => {
      if (candidateIndex === index || area(candidate) >= area(rect) * 0.82) return false;
      const inside = Math.max(0, Math.min(rect.right, candidate.right) - Math.max(rect.x, candidate.x)) *
        Math.max(0, Math.min(rect.bottom, candidate.bottom) - Math.max(rect.y, candidate.y)) / Math.max(1, area(candidate));
      return inside >= 0.82;
    }).sort((a, b) => (a.x + a.right) - (b.x + b.right));
    const containsTwoSiblings = siblings.some((first, siblingIndex) => {
      const second = siblings[siblingIndex + 1];
      if (!second) return false;
      const vertical = Math.max(0, Math.min(first.bottom, second.bottom) - Math.max(first.y, second.y)) /
        Math.max(1, Math.min(first.bottom - first.y, second.bottom - second.y));
      const centerDistance = Math.abs((first.x + first.right) / 2 - (second.x + second.right) / 2);
      return vertical >= 0.65 && centerDistance >= rectWidth * 0.28;
    });
    if (containsTwoSiblings) composites.add(index);
  });
  const nonComposites = merged.filter((_rect, index) => !composites.has(index));
  return nonComposites.filter((rect, index) => {
    const rectWidth = rect.right - rect.x;
    const rectHeight = rect.bottom - rect.y;
    return !nonComposites.some((other, otherIndex) => {
      if (otherIndex === index || area(other) <= area(rect) * 1.25) return false;
      const iw = Math.max(0, Math.min(rect.right, other.right) - Math.max(rect.x, other.x));
      const ih = Math.max(0, Math.min(rect.bottom, other.bottom) - Math.max(rect.y, other.y));
      const contained = iw * ih / Math.max(1, area(rect)) >= 0.88;
      const vertical = ih / Math.max(1, Math.min(rectHeight, other.bottom - other.y));
      const horizontal = iw / Math.max(1, Math.min(rectWidth, other.right - other.x));
      return contained && vertical >= 0.72 && horizontal >= 0.75;
    });
  });
}

/** Scan source pixels in small 2D chunks so very tall images never become one huge canvas. */
async function scanNativeFile(
  file: File,
  textBoxes: Array<{ x: number; y: number; width: number; height: number }> = [],
  signal?: AbortSignal,
): Promise<{ rects: PixelRect[]; width: number; height: number }> {
  if (signal?.aborted) return { rects: [], width: 0, height: 0 };
  const bitmap = await createImageBitmap(file);
  const width = bitmap.width;
  const height = bitmap.height;
  try {
    if (!width || !height || width * height > MAX_SCAN_PIXELS) throw new Error("截图超过像素候选检测上限，请缩小后重试");
    const allRects: PixelRect[] = [];
    const stepX = SEGMENT_WIDTH - SEGMENT_OVERLAP;
    const stepY = SEGMENT_HEIGHT - SEGMENT_OVERLAP;
    for (let top = 0; top < height; top += stepY) {
      const segmentHeight = Math.min(SEGMENT_HEIGHT, height - top);
      for (let left = 0; left < width; left += stepX) {
        if (signal?.aborted) return { rects: [], width, height };
        const segmentWidth = Math.min(SEGMENT_WIDTH, width - left);
        const canvas = document.createElement("canvas");
        canvas.width = segmentWidth;
        canvas.height = segmentHeight;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        if (!context) throw new Error("浏览器无法扫描截图像素");
        context.drawImage(bitmap, left, top, segmentWidth, segmentHeight, 0, 0, segmentWidth, segmentHeight);
        const pixels = context.getImageData(0, 0, segmentWidth, segmentHeight).data;
        const columns = Math.ceil(segmentWidth / CELL);
        const rows = Math.ceil(segmentHeight / CELL);
        const active = new Uint8Array(columns * rows);
        const chromatic = new Uint8Array(columns * rows);
        const edge = new Uint8Array(columns * rows);
        const sampleCount = new Uint16Array(columns * rows);
        const lumaSum = new Float32Array(columns * rows);
        const lumaSquare = new Float32Array(columns * rows);
        const colorCount = new Uint16Array(columns * rows);
        const edgeCount = new Uint16Array(columns * rows);
        const occupiedCount = new Uint16Array(columns * rows);

        // Native-resolution samples; each cell summarizes a small 8×8 patch.
        for (let sy = 0; sy < segmentHeight; sy += 1) {
          if (signal?.aborted) return { rects: [], width, height };
          for (let sx = 0; sx < segmentWidth; sx += 1) {
            const offset = (sy * segmentWidth + sx) * 4;
            const r = pixels[offset]!; const g = pixels[offset + 1]!; const b = pixels[offset + 2]!;
            const lum = (r * 0.299 + g * 0.587 + b * 0.114) / 255;
            const color = Math.max(r, g, b) - Math.min(r, g, b);
            const ci = Math.floor(sy / CELL) * columns + Math.floor(sx / CELL);
            const localX = sx % CELL; const localY = sy % CELL;
            sampleCount[ci] += 1;
            lumaSum[ci] += lum;
            lumaSquare[ci] += lum * lum;
            if (lum < 0.982 || color > 8) occupiedCount[ci] += 1;
            if (color > 13) colorCount[ci] += 1;
            if (localX > 0) {
              const previous = ((sy * segmentWidth + sx - 1) * 4);
              const pl = (pixels[previous]! * 0.299 + pixels[previous + 1]! * 0.587 + pixels[previous + 2]! * 0.114) / 255;
              if (Math.abs(lum - pl) > 0.045) edgeCount[ci] += 1;
            }
            if (localY > 0) {
              const previous = (((sy - 1) * segmentWidth + sx) * 4);
              const pl = (pixels[previous]! * 0.299 + pixels[previous + 1]! * 0.587 + pixels[previous + 2]! * 0.114) / 255;
              if (Math.abs(lum - pl) > 0.045) edgeCount[ci] += 1;
            }
          }
        }
        for (let i = 0; i < active.length; i += 1) {
          const samples = Math.max(1, sampleCount[i]!);
          const ink = occupiedCount[i]! / samples;
          const color = colorCount[i]! / samples;
          const edgeRate = edgeCount[i]! / samples;
          const mean = lumaSum[i]! / samples;
          const variance = Math.max(0, lumaSquare[i]! / samples - mean * mean);
          chromatic[i] = color >= 0.018 ? 1 : 0;
          edge[i] = edgeRate >= 0.025 ? 1 : 0;
          // Keep pale image pixels and fine line art while rejecting isolated antialiasing.
          active[i] = ink >= 0.012 && (color >= 0.012 || edgeRate >= 0.018 || variance >= 0.00012) ? 1 : 0;
        }

        // Long vertical edges are often the only visible evidence for a white/pale
        // illustration while scanning the middle of a tall image. Preserve that 2D
        // rectangle evidence per band so adjacent bands can be merged afterward.
        const verticalRuns: Array<{ x: number; y0: number; y1: number }> = [];
        for (let cx = 0; cx < columns; cx += 1) {
          let runStart = -1;
          let best: { y0: number; y1: number } | null = null;
          for (let cy = 0; cy <= rows; cy += 1) {
            const isEdge = cy < rows && edge[cy * columns + cx] === 1;
            if (isEdge && runStart < 0) runStart = cy;
            if (!isEdge && runStart >= 0) {
              if (!best || cy - runStart > best.y1 - best.y0) best = { y0: runStart, y1: cy };
              runStart = -1;
            }
          }
          if (best && best.y1 - best.y0 >= Math.max(6, Math.round(rows * 0.5))) verticalRuns.push({ x: cx, ...best });
        }
        const boundaryRects: PixelRect[] = [];
        for (let ai = 0; ai < verticalRuns.length; ai += 1) for (let bi = ai + 1; bi < verticalRuns.length; bi += 1) {
          const a = verticalRuns[ai]!; const b = verticalRuns[bi]!;
          const leftCell = Math.min(a.x, b.x); const rightCell = Math.max(a.x, b.x);
          const overlapTop = Math.max(a.y0, b.y0); const overlapBottom = Math.min(a.y1, b.y1);
          if ((rightCell - leftCell) * CELL < Math.max(112, segmentWidth * 0.22) ||
              (overlapBottom - overlapTop) < Math.max(6, Math.round(rows * 0.45))) continue;
          const x = left + leftCell * CELL;
          const y = top + overlapTop * CELL;
          const right = Math.min(width, left + (rightCell + 1) * CELL);
          const bottom = Math.min(height, top + overlapBottom * CELL);
          if ((right - x) * (bottom - y) < 3_000) continue;
          if (!boundaryRects.some((item) => Math.abs(item.x - x) < CELL && Math.abs(item.right - right) < CELL &&
              Math.abs(item.y - y) < CELL && Math.abs(item.bottom - bottom) < CELL)) {
            boundaryRects.push({ x, y, right, bottom, score: 0.58, colorCells: 0, segmentX: left });
          }
        }
        allRects.push(...boundaryRects.sort((a, b) =>
          (b.right - b.x) * (b.bottom - b.y) - (a.right - a.x) * (a.bottom - a.y)).slice(0, 8));

        const visited = new Uint8Array(active.length);
        const boxes: PixelRect[] = [];
        for (let seed = 0; seed < active.length; seed += 1) {
          if (!active[seed] || visited[seed]) continue;
          const queue = [seed]; visited[seed] = 1;
          let minX = columns; let maxX = -1; let minY = rows; let maxY = -1;
          let cells = 0; let colorCells = 0; let edgeCells = 0;
          for (let q = 0; q < queue.length; q += 1) {
            const current = queue[q]!;
            const cx = current % columns; const cy = Math.floor(current / columns);
            minX = Math.min(minX, cx); maxX = Math.max(maxX, cx);
            minY = Math.min(minY, cy); maxY = Math.max(maxY, cy);
            cells += 1; colorCells += chromatic[current]!; edgeCells += edge[current]!;
            // 8-connectivity joins chart lines and nearby pale elements without a row-only band.
            for (let dy = -1; dy <= 1; dy += 1) for (let dx = -1; dx <= 1; dx += 1) {
              const nx = cx + dx; const ny = cy + dy;
              if (nx < 0 || nx >= columns || ny < 0 || ny >= rows) continue;
              const next = ny * columns + nx;
              if (active[next] && !visited[next]) { visited[next] = 1; queue.push(next); }
            }
          }
          const cellWidth = maxX - minX + 1; const cellHeight = maxY - minY + 1;
          const rawW = Math.min(segmentWidth, (cellWidth * CELL) + CELL);
          const rawH = Math.min(segmentHeight, (cellHeight * CELL) + CELL);
          const x = left + minX * CELL; const y = top + minY * CELL;
          if (rawW < 56 || rawH < 44 || rawW * rawH < 3_000 || cells < 8) continue;
          const box: PixelRect = { x, y, right: Math.min(width, x + rawW), bottom: Math.min(height, y + rawH),
            score: 0, colorCells, segmentX: left };
          const areaCells = cellWidth * cellHeight;
          const fill = cells / areaCells;
          const colorRatio = colorCells / Math.max(1, cells);
          const edgeRatio = edgeCells / Math.max(1, cells);
          const textRatio = overlapsText(box, textBoxes.map((item) => ({ x: item.x * width, y: item.y * height,
            width: item.width * width, height: item.height * height })));
          const aspect = rawW / rawH;
          const hasColor = colorRatio >= 0.035;
          const has2dStructure = (rawH >= 72 && rawW >= 72 && fill >= 0.025 && edgeRatio >= 0.18) ||
            (rawH >= 96 && rawW >= 96 && fill < 0.35 && edgeRatio >= 0.1);
          const lineArtBoundary = rawH >= 72 && rawW >= 72 && fill < 0.24 && edgeRatio >= 0.24;
          if (!(hasColor || has2dStructure || lineArtBoundary)) continue;
          // Broad, shallow bands are usually emphasized text or separators, not figures.
          if (aspect > 5 && rawH < 72) continue;
          // OCR is supporting evidence: text-only blocks are suppressed, while colorful or
          // strongly bounded figures with labels remain candidates.
          if (textRatio > 0.32 && !hasColor && !lineArtBoundary) continue;
          if (textRatio > 0.7 && !hasColor) continue;
          // Very wide, OCR-heavy paragraphs are not image suggestions.
          if (aspect > 4.2 && textRatio > 0.12 && !hasColor) continue;
          box.score = Math.min(0.62, 0.25 + colorRatio * 0.55 + Math.min(0.16, edgeRatio * 0.12) + (lineArtBoundary ? 0.1 : 0));
          boxes.push(box);
        }
        allRects.push(...boxes.sort((a, b) => b.score - a.score ||
          ((b.right - b.x) * (b.bottom - b.y) - (a.right - a.x) * (a.bottom - a.y))).slice(0, 8));
        if (left + segmentWidth >= width) break;
        await yieldToBrowser();
      }
      if (top + SEGMENT_HEIGHT >= height) break;
    }
    return { rects: mergeRects(allRects), width, height };
  } finally {
    bitmap.close();
  }
}

export async function detectPixelImageCandidates(
  file: File,
  textBoxes: Array<{ x: number; y: number; width: number; height: number }> = [],
  signal?: AbortSignal,
): Promise<PixelCandidate[]> {
  const scanned = await scanNativeFile(file, textBoxes, signal);
  if (signal?.aborted || !scanned.width || !scanned.height) return [];
  return scanned.rects
    .sort((a, b) => b.score - a.score)
    .slice(0, MAX_RESULTS)
    .sort((a, b) => a.y - b.y || a.x - b.x)
    .map((rect, index) => ({ key: `pixels-${Math.round(rect.x)}-${Math.round(rect.y)}-${index}`,
      x: rect.x / scanned.width, y: rect.y / scanned.height,
      width: (rect.right - rect.x) / scanned.width, height: (rect.bottom - rect.y) / scanned.height,
      confidence: rect.score, origin: "pixels" as const }));
}

/** Scan original screenshot tiles and map candidates to one uncapped long-image coordinate space. */
export async function detectPixelImageCandidatesAcrossTiles(
  tiles: PixelScanTile[],
  selection: { left: number; right: number; top: number; bottom: number },
  viewportHeight: number,
  textBoxes: Array<{ x: number; y: number; width: number; height: number }> = [],
  signal?: AbortSignal,
): Promise<PixelCandidate[]> {
  const span = selection.bottom - selection.top;
  if (signal?.aborted || span <= 0 || viewportHeight <= 0) return [];
  const candidates: Array<PixelCandidate & { segment: number }> = [];
  for (let ti = 0; ti < tiles.length; ti += 1) {
    const tile = tiles[ti]!;
    if (signal?.aborted) return [];
    const { rects, width, height } = await scanNativeFile(tile.file, [], signal);
    if (!width || !height) continue;
    const cssHeight = tile.coveredCssHeight || viewportHeight;
    for (const rect of rects) {
      const pageTop = tile.scrollY + rect.y / height * cssHeight;
      const pageBottom = tile.scrollY + rect.bottom / height * cssHeight;
      const y0 = Math.max(selection.top, pageTop);
      const y1 = Math.min(selection.bottom, pageBottom);
      if (y1 <= y0) continue;
      const candidate: PixelCandidate & { segment: number } = {
        key: `pixels-t${tile.index ?? ti}-${Math.round(rect.x)}-${Math.round(y0)}`,
        x: rect.x / width,
        y: (y0 - selection.top) / span,
        width: (rect.right - rect.x) / width,
        height: (y1 - y0) / span,
        confidence: rect.score,
        origin: "pixels",
        tileIndex: tile.index ?? ti,
        coverage: y0 > pageTop + 1 || y1 < pageBottom - 1 ? "partial" : "complete",
        segment: ti,
      };
      candidates.push(candidate);
    }
    await yieldToBrowser();
  }
  // Merge only geometrically overlapping fragments from different captured tiles.
  const merged: Array<PixelCandidate & { segment: number; segments: Set<number> }> = [];
  for (const candidate of candidates.sort((a, b) => b.confidence - a.confidence)) {
    const match = merged.find((item) => {
      if (item.segments.has(candidate.segment)) return false;
      const xOverlap = Math.max(0, Math.min(item.x + item.width, candidate.x + candidate.width) - Math.max(item.x, candidate.x));
      const yOverlap = Math.max(0, Math.min(item.y + item.height, candidate.y + candidate.height) - Math.max(item.y, candidate.y));
      const minW = Math.min(item.width, candidate.width);
      const minH = Math.min(item.height, candidate.height);
      return xOverlap / Math.max(1e-9, minW) >= 0.7 && yOverlap / Math.max(1e-9, minH) >= 0.18;
    });
    if (!match) merged.push({ ...candidate, segments: new Set([candidate.segment]) });
    else {
      const right = Math.max(match.x + match.width, candidate.x + candidate.width);
      const bottom = Math.max(match.y + match.height, candidate.y + candidate.height);
      match.x = Math.min(match.x, candidate.x); match.y = Math.min(match.y, candidate.y);
      match.width = right - match.x; match.height = bottom - match.y;
      match.confidence = Math.max(match.confidence, candidate.confidence);
      match.coverage = match.coverage === "partial" || candidate.coverage === "partial" ? "partial" : "complete";
      match.segments.add(candidate.segment);
    }
  }
  // OCR reduces prose false positives by overlap, but an image containing text is kept
  // whenever its visual proposal has independent color/boundary evidence.
  const filtered = merged.filter((candidate) => {
    const overlap = overlapsText({ x: candidate.x, y: candidate.y, right: candidate.x + candidate.width,
      bottom: candidate.y + candidate.height, score: candidate.confidence, colorCells: 0, segmentX: 0 }, textBoxes);
    return overlap <= 0.55 || candidate.confidence >= 0.55;
  });
  return filtered.slice(0, MAX_RESULTS).sort((a, b) => a.y - b.y || a.x - b.x)
    .map(({ segments: _segments, segment: _segment, ...candidate }, index) => ({ ...candidate, key: `${candidate.key}-${index}` }));
}
