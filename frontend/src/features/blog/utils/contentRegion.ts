/**
 * 手动区域模式的主内容区域自动预填。
 *
 * 思路：把像素下采样成小格，统计每行/每列「非背景像素」密度（背景色取四角
 * 众数近似），找出密度最高的连续主区域，四周向外扩少量边距，输出归一化矩形。
 * 纯函数部分不依赖 DOM，便于在 Node 单元测试里用合成像素矩阵验证；
 * `detectContentRegionFromFile` 是浏览器侧的便捷封装（读取文件像素后再调用纯函数）。
 *
 * 分析失败（纯色图、全图噪声、内容过小等）返回 null，调用方回退到空选区 + 提示。
 */

export interface NormalizedRect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface RegionScanOptions {
  /** 下采样目标：长边的采样格数（默认 128，限制在 16–512）。 */
  samples?: number;
  /** 主区域四周向外保留的边距比例（相对整图边长，默认 0.03）。 */
  margin?: number;
  /** 行/列密度高于「峰值密度 × threshold」才视为主区域的一部分（默认 0.3）。 */
  threshold?: number;
}

const DEFAULT_SAMPLES = 128;
const DEFAULT_MARGIN = 0.03;
const DEFAULT_THRESHOLD = 0.3;
/** 与背景色的 RGB 欧氏距离低于该值的采样点视为背景（0–441 量纲）。 */
const BACKGROUND_DISTANCE = 48;
/** 主区域至少要占该维度的比例；低于它说明分析不可靠，宁可返回 null。 */
const MIN_REGION_RATIO = 0.2;
/** alpha 低于该值的像素按背景处理（透明区域不是内容）。 */
const OPAQUE_ALPHA = 16;

type Rgb = [number, number, number];

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function quantizeChannel(value: number): number {
  return Math.min(255, Math.round(value / 16) * 16);
}

/**
 * 背景色估计：四角各取约 5% 边长的小块，把颜色量化到 16 级/通道后取众数桶，
 * 桶内再取真实通道均值。全透明角块跳过；完全没有有效像素时回退白色。
 */
export function estimateBackgroundColor(
  data: Uint8ClampedArray | Uint8Array,
  width: number,
  height: number,
): Rgb {
  const patch = Math.max(1, Math.round(Math.min(width, height) * 0.05));
  const corners: Array<[number, number]> = [
    [0, 0],
    [Math.max(0, width - patch), 0],
    [0, Math.max(0, height - patch)],
    [Math.max(0, width - patch), Math.max(0, height - patch)],
  ];
  const buckets = new Map<string, { count: number; r: number; g: number; b: number }>();
  for (const [originX, originY] of corners) {
    for (let dy = 0; dy < patch; dy += 1) {
      for (let dx = 0; dx < patch; dx += 1) {
        const x = clamp(originX + dx, 0, width - 1);
        const y = clamp(originY + dy, 0, height - 1);
        const offset = (y * width + x) * 4;
        if (data[offset + 3]! < OPAQUE_ALPHA) continue;
        const key = `${quantizeChannel(data[offset]!)},${quantizeChannel(data[offset + 1]!)},${quantizeChannel(data[offset + 2]!)}`;
        const bucket = buckets.get(key) ?? { count: 0, r: 0, g: 0, b: 0 };
        bucket.count += 1;
        bucket.r += data[offset]!;
        bucket.g += data[offset + 1]!;
        bucket.b += data[offset + 2]!;
        buckets.set(key, bucket);
      }
    }
  }
  let best: { count: number; r: number; g: number; b: number } | null = null;
  for (const bucket of buckets.values()) {
    if (!best || bucket.count > best.count) best = bucket;
  }
  if (!best || best.count === 0) return [255, 255, 255];
  return [best.r / best.count, best.g / best.count, best.b / best.count];
}

/** typed array 最大值（避免对大数组使用 spread）。 */
function maxOf(values: Float64Array): number {
  let max = 0;
  for (let i = 0; i < values.length; i += 1) max = Math.max(max, values[i]!);
  return max;
}

/**
 * 在密度数组里找「高于 cutoff 的连续下标区间」中总和最大的一段。
 * 返回 [start, end)（end 不含）；整段数组都不达标时返回 null。
 */
function densestRun(density: Float64Array, total: number, cutoff: number): [number, number] | null {
  let best: [number, number] | null = null;
  let bestSum = -1;
  let start = -1;
  let sum = 0;
  for (let i = 0; i <= density.length; i += 1) {
    const active = i < density.length && density[i]! / total >= cutoff;
    if (active) {
      if (start < 0) {
        start = i;
        sum = 0;
      }
      sum += density[i]!;
    } else if (start >= 0) {
      if (sum > bestSum) {
        bestSum = sum;
        best = [start, i];
      }
      start = -1;
    }
  }
  return best;
}

/**
 * 主内容区域检测（纯函数）。
 *
 * @param data RGBA 像素（行优先，长度 ≥ width × height × 4）。
 * @param width 像素宽（≥ 8）。
 * @param height 像素高（≥ 8）。
 * @returns 归一化矩形（0–1，含少量外扩边距）；分析不可靠时返回 null。
 */
export function detectContentRegion(
  data: Uint8ClampedArray | Uint8Array,
  width: number,
  height: number,
  options: RegionScanOptions = {},
): NormalizedRect | null {
  const samples = clamp(Math.round(options.samples ?? DEFAULT_SAMPLES), 16, 512);
  const margin = clamp(options.margin ?? DEFAULT_MARGIN, 0, 0.2);
  const threshold = clamp(options.threshold ?? DEFAULT_THRESHOLD, 0.05, 0.95);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width < 8 || height < 8) return null;
  if (!data || data.length < width * height * 4) return null;

  const background = estimateBackgroundColor(data, width, height);
  // 下采样：每个格子取中心像素判定「是否非背景」。截图背景多为大片纯色，
  // 中心采样配合阈值足够稳，也保证纯函数的输出完全确定（便于测试）。
  const step = Math.max(1, Math.floor(Math.max(width, height) / samples));
  const cols = Math.max(1, Math.floor(width / step));
  const rows = Math.max(1, Math.floor(height / step));
  const columnDensity = new Float64Array(cols);
  const rowDensity = new Float64Array(rows);
  let activeCells = 0;
  for (let cy = 0; cy < rows; cy += 1) {
    for (let cx = 0; cx < cols; cx += 1) {
      const px = Math.min(width - 1, cx * step + (step >> 1));
      const py = Math.min(height - 1, cy * step + (step >> 1));
      const offset = (py * width + px) * 4;
      if (data[offset + 3]! < OPAQUE_ALPHA) continue;
      const dr = data[offset]! - background[0];
      const dg = data[offset + 1]! - background[1];
      const db = data[offset + 2]! - background[2];
      if (Math.sqrt(dr * dr + dg * dg + db * db) <= BACKGROUND_DISTANCE) continue;
      columnDensity[cx] += 1;
      rowDensity[cy] += 1;
      activeCells += 1;
    }
  }
  // 纯色图：没有任何非背景像素，无法定位主区域。
  if (activeCells === 0) return null;

  const columnCutoff = Math.max((maxOf(columnDensity) / rows) * threshold, 2 / rows);
  const rowCutoff = Math.max((maxOf(rowDensity) / cols) * threshold, 2 / cols);
  const xRange = densestRun(columnDensity, rows, columnCutoff);
  const yRange = densestRun(rowDensity, cols, rowCutoff);
  if (!xRange || !yRange) return null;
  const x0 = xRange[0] / cols;
  const x1 = xRange[1] / cols;
  const y0 = yRange[0] / rows;
  const y1 = yRange[1] / rows;
  if (x1 - x0 < MIN_REGION_RATIO || y1 - y0 < MIN_REGION_RATIO) return null;
  // 四周向外留少量边距，避免贴边裁掉内容边缘。
  return {
    x0: clamp(x0 - margin, 0, 1),
    y0: clamp(y0 - margin, 0, 1),
    x1: clamp(x1 + margin, 0, 1),
    y1: clamp(y1 + margin, 0, 1),
  };
}

/** 下采样读像素的上限边长：限制 getImageData 内存与耗时。 */
const READ_MAX_SIDE = 512;

/**
 * 浏览器侧便捷封装：从截图文件读取（必要时缩小后的）像素再检测主内容区域。
 * 任何一步失败（解码失败、canvas 不可用等）都返回 null，由调用方回退到手动画框。
 */
export async function detectContentRegionFromFile(
  file: File,
  options: RegionScanOptions = {},
): Promise<NormalizedRect | null> {
  let bitmap: ImageBitmap | null = null;
  try {
    bitmap = await createImageBitmap(file);
    const scale = Math.min(1, READ_MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return null;
    context.drawImage(bitmap, 0, 0, width, height);
    const image = context.getImageData(0, 0, width, height);
    return detectContentRegion(image.data, width, height, options);
  } catch {
    return null;
  } finally {
    bitmap?.close();
  }
}
