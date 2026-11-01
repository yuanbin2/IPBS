<script setup lang="ts">
/**
 * B-045：截图 → 浏览器本地 OCR → Markdown 校对。
 * 图片只在浏览器本地处理；未确认前不上传、不落库。
 * 校对：左图右文；长截图先拼图，再只对最终长图调用一次 OCR。
 * 可改文字/类型/顺序、删噪声块；低置信度块显著标注；长页只显示已覆盖范围，不报“全文完成”。
 * Markdown 预览走与文章一致的 xss 清洗；保存动作由宿主决定（默认私有笔记）。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { MdPreview } from "md-editor-v3";
import xss from "xss";
import {
  assembleMarkdown,
  blockEditableText,
  collectBlockWarnings,
  dedupeBlocksAcrossTiles,
  inferBlocks,
  isProofreadWarning,
  isTextCoveredByRect,
  validateImageFile,
  type OcrBlock,
  type OcrBlockKind,
  type OcrLine,
} from "../utils/screenshotOcr";
import { ScreenshotOcrClient, type OcrProgress } from "../utils/screenshotOcrClient";
import { cropFromOriginalTiles, cropLongShotTiles, mergeCrossTileCandidates, stitchLongShotTiles, verifyCandidatePixelOverlaps,
  type VerifiedCandidateOverlap } from "../utils/longScreenshot";
import { detectPixelImageCandidates, detectPixelImageCandidatesAcrossTiles, type PixelCandidate } from "../utils/pixelImageCandidates";
import { detectContentRegionFromFile } from "../utils/contentRegion";

export interface ScreenshotTileInput {
  file: File;
  /** 图片像素宽高（设备像素）。 */
  width: number;
  height: number;
  /** 该视口在页面上的 CSS 位置（长页采集时来自扩展元数据）。 */
  scrollX: number;
  scrollY: number;
  coveredCssHeight?: number;
  /** 可见网页图片在视口里的归一化矩形；只作为待确认候选。 */
  imageCandidates?: Array<{ key?: string; x: number; y: number; width: number; height: number;
    fullX?: number; fullY?: number; fullWidth?: number; fullHeight?: number; priority?: number; kind?: "code" }>;
}

export interface ScreenshotJobInput {
  tiles: ScreenshotTileInput[];
  mode: "screen" | "region" | "longpage";
  sourceUrl: string;
  titleCandidate: string;
  capturedAt?: string;
  covered?: { top: number; bottom: number };
  truncated?: boolean;
  selection?: { left: number; right: number; top: number; bottom: number };
  viewport?: { width: number; height: number };
  warnings?: string[];
  /** 需要用户先裁剪（手动区域模式）。 */
  cropRequired?: boolean;
}

const props = defineProps<{
  modelValue: boolean;
  /** 扩展交接或本地选择的截图任务；打开对话框后自动识别。 */
  initialJob?: ScreenshotJobInput | null;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: boolean];
  /** 校对确认后把内容交给宿主（默认私有笔记，可选博客草稿；这里不落库）。 */
  applyContent: [payload: { title: string; content: string; target: "private_note" | "article_draft" }];
}>();

const saveTarget = ref<"private_note" | "article_draft">("private_note");

interface TileVM {
  index: number;
  url: string;
  width: number;
  height: number;
  scrollY: number;
  scrollX: number;
  coveredCssHeight?: number;
  label: string;
  imageCandidates: NonNullable<ScreenshotTileInput["imageCandidates"]>;
}

const tiles = ref<TileVM[]>([]);
const stitchedFile = ref<File | null>(null);
const stitchedUrl = ref("");
const stitchedSize = ref({ width: 0, height: 0 });
const stitchError = ref("");
const showTiles = ref(false);

interface EditableBlockVM {
  id: string;
  tileIndex: number;
  kind: OcrBlockKind;
  level: 2 | 3;
  text: string;
  warnings: string[];
  bbox: { x: number; y: number; width: number; height: number };
  lowConfidence: boolean;
}

interface UploadedFigureVM {
  url: string;
  target: "private_note" | "article_draft";
  file: File;
  block: EditableBlockVM;
  insertAt: number;
  /** 插入位置锚定块：OCR 流式追加/用户删块会让下标漂移，重发布时按 id 重新解析。 */
  anchorId: string | "end";
  sourceRect: { x: number; y: number; width: number; height: number };
  sourceTileIndex: number;
  sourceIsStitched: boolean;
  textPolicy: "image_only" | "both";
}

const step = ref<"select" | "crop" | "review">("select");
const busy = ref(false);
const progress = ref<OcrProgress | null>(null);
const progressNote = ref("");
const error = ref("");
const imageUrl = ref("");
const imageSize = ref({ width: 0, height: 0 });
const imageLabel = ref("");
const blocks = ref<EditableBlockVM[]>([]);
// Keep raw worker rows (text, native-pixel bbox, confidence) during this dialog
// session so diagnostics do not have to infer them back from grouped Markdown.
const rawOcrLines = ref<OcrLine[]>([]);
const selectedBlockId = ref("");
const edited = ref(false);
const lastRunMs = ref(0);
const fileInput = ref<HTMLInputElement | null>(null);
const imagePane = ref<HTMLDivElement | null>(null);
const blocksPane = ref<HTMLDivElement | null>(null);
const previewPane = ref<HTMLDivElement | null>(null);
const sourceInfo = ref<{ sourceUrl: string; titleCandidate: string; capturedAt?: string } | null>(null);
const coverage = ref<{ covered?: { top: number; bottom: number }; truncated: boolean; tileCount: number; mode: string } | null>(null);
const droppedDuplicates = ref(0);
const editedOcrBlockIds = new Set<string>();
const deletedOcrBlockIds = new Set<string>();
const originalOcrText = new Map<string, string>();
let ocrRunGeneration = 0;
let ocrOrderLocked = false;
// 扩展交接完成后临时存储会删除；识别失败时保留本次 File 供重试或导出。
const currentJob = ref<ScreenshotJobInput | null>(null);
const insertedCandidateKeys = ref<string[]>([]);
const rejectedCandidateKeys = ref<string[]>([]);
const verifiedPixelOverlaps = ref<VerifiedCandidateOverlap[]>([]);
const pixelCandidates = ref<PixelCandidate[]>([]);
const pixelRawCandidateCount = ref(0);
const pixelDedupedCandidateCount = ref(0);
let pixelScanController: AbortController | null = null;
const pixelScanning = ref(false);
const pixelScanError = ref("");
const candidateCount = computed(() => {
  // 同一张网页图片跨屏会在多个视口重复出现；按稳定 key 去重后计数，
  // 无 key 的候选（screen/region 模式）逐个计入。
  const keys = new Set<string>();
  let unkeyed = 0;
  for (const tile of tiles.value) {
    for (const candidate of tile.imageCandidates) {
      if (candidate.key) keys.add(candidate.key);
      else unkeyed += 1;
    }
  }
  return Math.max(0, keys.size + unkeyed + pixelCandidates.value.length - rejectedCandidateKeys.value.length);
});
const stitchedCandidates = computed(() => {
  const job = currentJob.value;
  if (!stitchedFile.value || !job?.selection) return [];
  const pixelSuggestions = pixelCandidates.value.map((candidate) => {
    const top = job.selection!.top + candidate.y * (job.selection!.bottom - job.selection!.top);
    const bottom = top + candidate.height * (job.selection!.bottom - job.selection!.top);
    const spans = job.tiles.map((tile) => ({ top: tile.scrollY, bottom: tile.scrollY +
      (tile.coveredCssHeight ?? job.viewport?.height ?? 0) })).filter((span) => span.bottom > span.top).sort((a, b) => a.top - b.top);
    let coveredTo = top;
    let gap = false;
    for (const span of spans) {
      if (span.bottom <= top || span.top >= bottom) continue;
      if (span.top > coveredTo + 1) gap = true;
      coveredTo = Math.max(coveredTo, Math.min(bottom, span.bottom));
    }
    const coverage = gap ? "gap" as const : coveredTo < bottom - 1 ? "partial" as const : "complete" as const;
    return { ...candidate, tileIndex: 0, anchorY: candidate.y * stitchedSize.value.height, coverage, kind: undefined as "code" | undefined };
  });
  return [...mergeCrossTileCandidates(tiles.value, job.selection, job.viewport?.height, verifiedPixelOverlaps.value),
    ...pixelSuggestions]
    .filter((candidate) => !rejectedCandidateKeys.value.includes(`whole:${candidate.key}`));
});
const figureInsertIndex = ref<number | null>(null);
/** 本次裁剪会话里用户是否在“图片插入位置”下拉里明确选过；选过则自动推算不再覆盖。 */
const figureInsertIndexTouched = ref(false);
/** 预填/手选的插入位置锚定块 id（"end" = 正文末尾）。候选在 OCR 流式识别期间
 * 就能点选，数字下标会随后续文字块追加而漂移；上传与重发布时按 id 重新解析。 */
const figureInsertAnchorId = ref<string | "end" | null>(null);
const activeCandidateKey = ref<string | null>(null);
const imageTextPolicy = ref<"both" | "image_only">("both");

interface ReviewNavigationState {
  imagePageY: number;
  imageScrollLeft: number;
  rightBlockId: string;
  rightBlockOffset: number;
  editorScrollTop: number;
  previewScrollTop: number;
  selectedBlockId: string;
  showTiles: boolean;
}

let cropReturnNavigation: ReviewNavigationState | null = null;

// 手动区域裁剪（region 模式，也服务隐私裁剪）
const cropState = ref<{
  url: string;
  file: File;
  natural: { width: number; height: number };
  rect: { x0: number; y0: number; x1: number; y1: number } | null;
  dragging: boolean;
  tileIndex?: number;
} | null>(null);
const cropImageRef = ref<HTMLImageElement | null>(null);
const cropPaneRef = ref<HTMLDivElement | null>(null);
const suggestedCrop = ref(false);
/** 主内容区域自动预填失败时的提示（纯色图、解码失败等回退到手动画框）。 */
const cropPrefillNote = ref("");
const cropPreviewUrl = ref("");
let previewCropFile: File | null = null;
let previewCropKey = "";
let previewCropObjectUrl = "";
/** 裁剪目的：region 模式先裁后 OCR；或从校对区“保留插图”上传引用。 */
const cropPurpose = ref<"ocr" | "image">("ocr");
const longCropClickStage = ref<0 | 1 | 2>(0);
const uploadingImage = ref(false);
const applying = ref(false);
let imageUploadController: AbortController | null = null;
/** tile 序号 → 原始本地 File（保留插图功能需要源字节）。 */
const tileFiles = new Map<number, File>();

let client: ScreenshotOcrClient | null = null;
let objectUrls: string[] = [];

const markdown = computed(() => assembleMarkdown(blocks.value.map((b) => ({ kind: b.kind, level: b.level, text: b.text }))));
// 私有图片读回需要登录态，<img> 原生加载不带 Authorization：预览时替换为
// 已鉴权 fetch 得到的 blob URL；导出的 Markdown 仍保留私有读回地址。
const previewMarkdown = ref("");
const figurePreviewUrls = new Map<string, string>();
const uploadedFigures: UploadedFigureVM[] = [];
watch(markdown, async (value) => {
  const urls = [...new Set(value.match(/\/api\/agent\/blog\/notes\/images\/\d+\//g) ?? [])];
  let display = value;
  for (const url of urls) {
    if (figurePreviewUrls.has(url)) {
      display = display.split(url).join(figurePreviewUrls.get(url)!);
      continue;
    }
    try {
      const response = await fetch(url);
      if (!response.ok) continue;
      const blobUrl = URL.createObjectURL(await response.blob());
      figurePreviewUrls.set(url, blobUrl);
      display = display.split(url).join(blobUrl);
    } catch {
      // 读回失败时保留原地址：MdPreview 会显示裂图，正文文字不受影响
    }
  }
  previewMarkdown.value = display;
});
const warnings = computed(() => (step.value === "review" ? collectBlockWarnings(inferredFromVm()) : []));
const coveredText = computed(() => {
  if (!coverage.value?.covered) return "";
  const { top, bottom } = coverage.value.covered;
  return `已覆盖页面 ${Math.round(top)}–${Math.round(bottom)}px（约 ${Math.max(0, Math.round(bottom - top))}px）`;
});

function inferredFromVm(): OcrBlock[] {
  return blocks.value.map((block) => ({
    id: block.id,
    kind: block.kind,
    level: block.level,
    lines: block.text.split("\n").map((text) => ({ text, confidence: block.lowConfidence ? 0.5 : 1, bbox: block.bbox })),
    warnings: block.warnings,
    bbox: block.bbox,
  }));
}

function ensureClient(): ScreenshotOcrClient {
  if (!client) {
    client = new ScreenshotOcrClient({
      onProgress: (value) => {
        progress.value = value;
        if (value.stage === "recognizing" && value.detail.startsWith("正在识别长图第")) {
          progressNote.value = value.detail;
        }
      },
      onError: (detail) => {
        error.value = detail;
      },
    });
  }
  return client;
}

function revokeUrls() {
  for (const url of objectUrls) URL.revokeObjectURL(url);
  objectUrls = [];
}

function resetResult() {
  ocrRunGeneration += 1;
  busy.value = false;
  editedOcrBlockIds.clear();
  deletedOcrBlockIds.clear();
  originalOcrText.clear();
  ocrOrderLocked = false;
  pixelScanController?.abort();
  pixelScanController = null;
  pixelCandidates.value = [];
  pixelRawCandidateCount.value = 0;
  pixelDedupedCandidateCount.value = 0;
  pixelScanning.value = false;
  pixelScanError.value = "";
  if (previewCropObjectUrl) URL.revokeObjectURL(previewCropObjectUrl);
  previewCropObjectUrl = "";
  previewCropFile = null;
  previewCropKey = "";
  revokeUrls();
  imageUrl.value = "";
  imageSize.value = { width: 0, height: 0 };
  tiles.value = [];
  stitchedFile.value = null;
  stitchedUrl.value = "";
  stitchedSize.value = { width: 0, height: 0 };
  stitchError.value = "";
  showTiles.value = false;
  cropReturnNavigation = null;
  blocks.value = [];
  rawOcrLines.value = [];
  selectedBlockId.value = "";
  edited.value = false;
  error.value = "";
  progress.value = null;
  progressNote.value = "";
  droppedDuplicates.value = 0;
  lastRunMs.value = 0;
  cropState.value = null;
  suggestedCrop.value = false;
  cropPrefillNote.value = "";
  cropPreviewUrl.value = "";
  cropPurpose.value = "ocr";
  longCropClickStage.value = 0;
  tileFiles.clear();
  uploadedFigures.length = 0;
  insertedCandidateKeys.value = [];
  rejectedCandidateKeys.value = [];
  verifiedPixelOverlaps.value = [];
  figureInsertIndex.value = null;
  figureInsertAnchorId.value = null;
  figureInsertIndexTouched.value = false;
  activeCandidateKey.value = null;
  for (const url of figurePreviewUrls.values()) URL.revokeObjectURL(url);
  figurePreviewUrls.clear();
}

/** 长截图先拼成最终图，只识别一次；单屏截图直接识别原图。 */
async function runJob(job: ScreenshotJobInput) {
  if (busy.value) return;
  resetResult();
  const runGeneration = ocrRunGeneration;
  currentJob.value = job;
  error.value = "";
  busy.value = true;
  coverage.value = {
    covered: job.covered,
    truncated: Boolean(job.truncated),
    tileCount: job.tiles.length,
    mode: job.mode,
  };
  sourceInfo.value = {
    sourceUrl: job.sourceUrl,
    titleCandidate: job.titleCandidate,
    capturedAt: job.capturedAt,
  };
  try {
    // Validate before createImageBitmap/cropping so a local file with a fake
    // image extension gets the actionable signature error, not a decode error.
    for (const tile of job.tiles) {
      const bytes = new Uint8Array(await tile.file.arrayBuffer());
      const verdict = validateImageFile({ name: tile.file.name, size: tile.file.size, type: tile.file.type }, bytes);
      if (!verdict.ok) throw new Error(verdict.detail);
    }
    let workingJob = job;
    let ocrFile: File | null = null;
    if (job.mode === "longpage" && job.tiles.length > 1 && (!job.selection || !job.viewport?.height)) {
      throw new Error("长截图缺少拼接范围，无法生成最终长图；请从扩展重新截取。");
    }
    if (job.mode === "longpage" && job.selection && job.viewport?.height) {
      const croppedTiles = await cropLongShotTiles(job.tiles, job.selection, job.viewport.height);
      verifiedPixelOverlaps.value = await verifyCandidatePixelOverlaps(croppedTiles);
      workingJob = { ...job, tiles: croppedTiles };
      currentJob.value = workingJob;
      progressNote.value = "正在拼接最终长图…";
      stitchedFile.value = await stitchLongShotTiles(croppedTiles, job.selection, job.viewport.height);
      const compositeBitmap = await createImageBitmap(stitchedFile.value);
      stitchedSize.value = { width: compositeBitmap.width, height: compositeBitmap.height };
      compositeBitmap.close();
      stitchedUrl.value = URL.createObjectURL(stitchedFile.value);
      objectUrls.push(stitchedUrl.value);
      ocrFile = stitchedFile.value;
    }
    const perTileLines: OcrLine[][] = [];
    const tileVms: TileVM[] = [];
    for (let index = 0; index < workingJob.tiles.length; index += 1) {
      const tile = workingJob.tiles[index];
      const bitmap = await createImageBitmap(tile.file);
      const size = { width: bitmap.width, height: bitmap.height };
      bitmap.close();
      const url = URL.createObjectURL(tile.file);
      objectUrls.push(url);
      tileFiles.set(index, tile.file);
      tileVms.push({
        index,
        url,
        width: size.width,
        height: size.height,
        scrollY: tile.scrollY,
        scrollX: tile.scrollX,
        coveredCssHeight: tile.coveredCssHeight,
        label: tile.file.name,
        imageCandidates: tile.imageCandidates ?? [],
      });
    }
    imageLabel.value = job.titleCandidate || job.tiles[0]?.file.name || "截图";
    if (stitchedUrl.value) {
      imageUrl.value = stitchedUrl.value;
      imageSize.value = stitchedSize.value;
    } else if (tileVms.length) {
      imageUrl.value = tileVms[0].url;
      imageSize.value = { width: tileVms[0].width, height: tileVms[0].height };
    }
    tiles.value = tileVms;
    // Publish the source preview first. Image candidates are scanned from uncapped source
    // tiles while OCR runs, so OCR failure/latency cannot hide the source or its suggestions.
    pixelScanController?.abort();
    pixelScanController = new AbortController();
    const scanSignal = pixelScanController.signal;
    pixelScanning.value = true;
    pixelScanError.value = "";
    step.value = "review";
    const publishPixelCandidates = (detected: PixelCandidate[]) => {
      pixelRawCandidateCount.value = detected.length;
      const domBoxes = workingJob.selection && workingJob.viewport?.height
        ? mergeCrossTileCandidates(tileVms, workingJob.selection, workingJob.viewport.height, verifiedPixelOverlaps.value)
        : tileVms.flatMap((tile) => tile.imageCandidates.map((candidate) => ({ x: candidate.x, y: candidate.y,
          width: candidate.width, height: candidate.height })));
      // DOM 候选（扩展截屏的网页图片+代码块）是权威来源：与之重叠的像素建议剔除；
      // 剩余像素建议只保留强证据（confidence ≥ 0.55），弱提示多为文字/卡片误报。
      const hasDomMetadata = domBoxes.length > 0;
      pixelCandidates.value = detected
        .filter((pixel) => (hasDomMetadata ? (pixel.confidence ?? 0) >= 0.55 : true))
        .filter((pixel) => !domBoxes.some((dom) => {
          const overlap = Math.max(0, Math.min(pixel.x + pixel.width, dom.x + dom.width) - Math.max(pixel.x, dom.x)) *
            Math.max(0, Math.min(pixel.y + pixel.height, dom.y + dom.height) - Math.max(pixel.y, dom.y));
          return overlap / Math.max(1e-9, Math.min(pixel.width * pixel.height, dom.width * dom.height)) >= 0.25;
        }));
      pixelDedupedCandidateCount.value = pixelCandidates.value.length;
    };
    const scanPixels = async (textBoxes: Array<{ x: number; y: number; width: number; height: number }> = []) => {
      if (workingJob.selection && workingJob.viewport?.height) {
        return detectPixelImageCandidatesAcrossTiles(workingJob.tiles.map((tile, index) => ({
          file: tile.file, index, scrollY: tile.scrollY, coveredCssHeight: tile.coveredCssHeight ?? workingJob.viewport!.height,
        })), workingJob.selection, workingJob.viewport.height, textBoxes, scanSignal);
      }
      const source = workingJob.tiles[0];
      return source ? detectPixelImageCandidates(source.file, textBoxes, scanSignal) : [];
    };
    let pixelScanPromise: Promise<PixelCandidate[]> | null = null;
    let pixelScanScheduledAfterFirstPaint = false;
    const startPixelScan = (textBoxes: Array<{ x: number; y: number; width: number; height: number }> = []) => {
      if (pixelScanPromise) return pixelScanPromise;
      pixelScanPromise = scanPixels(textBoxes).then((detected) => {
        if (!scanSignal.aborted) publishPixelCandidates(detected);
        return detected;
      }).catch((cause) => {
        if (!scanSignal.aborted) pixelScanError.value = cause instanceof Error ? cause.message : "本地图片区域检测失败";
        return [] as PixelCandidate[];
      }).finally(() => {
        if (!scanSignal.aborted) pixelScanning.value = false;
      });
      return pixelScanPromise;
    };
    const schedulePixelScanAfterFirstPaint = () => {
      if (pixelScanScheduledAfterFirstPaint) return;
      pixelScanScheduledAfterFirstPaint = true;
      // Vue must patch the first OCR cards and the browser must get a paint
      // opportunity before the CPU-bound pixel scan starts competing for canvas work.
      void nextTick().then(() => new Promise<void>((resolve) => {
        window.requestAnimationFrame(() => window.setTimeout(resolve, 0));
      })).then(() => startPixelScan());
    };

    const publishLines = (tileIndex: number, lines: OcrLine[]) => {
      if (runGeneration !== ocrRunGeneration) return;
      perTileLines[tileIndex] = lines;
      rawOcrLines.value = perTileLines.flatMap((tileLines) => tileLines);
      const perTileBlocks = perTileLines.map((tileLines, index) =>
        inferBlocks(tileLines).map((block) => ({ ...block, tileIndex: ocrFile ? -1 : index })),
      );
      const { blocks: merged, dropped } = ocrFile
        ? { blocks: perTileBlocks[0] ?? [], dropped: 0 }
        : dedupeBlocksAcrossTiles(perTileBlocks);
      droppedDuplicates.value = dropped;
      let incoming: EditableBlockVM[] = merged.map((block) => {
        const tileIndex = block.tileIndex ?? 0;
        const firstLine = block.lines[0]?.bbox ?? block.bbox;
        const id = `blk-${tileIndex}-${Math.round(firstLine.y)}-${Math.round(firstLine.x)}`;
        const text = blockEditableText(block);
        if (!originalOcrText.has(id)) originalOcrText.set(id, text);
        return {
          id, tileIndex, kind: block.kind, level: block.level, text,
          warnings: block.warnings, bbox: block.bbox,
          lowConfidence: block.lines.some((line) => line.confidence < 0.9),
        };
      });
      for (const figure of uploadedFigures) {
        if (figure.textPolicy !== "image_only") continue;
        incoming = incoming.filter((block) => {
          if (figure.sourceIsStitched ? block.tileIndex !== -1 : block.tileIndex !== figure.sourceTileIndex) return true;
          return !isTextCoveredByRect(block, figure.sourceRect);
        });
      }
      const incomingById = new Map(incoming.map((block) => [block.id, block]));
      const next: EditableBlockVM[] = [];
      const consumed = new Set<string>();
      for (const old of blocks.value) {
        if (deletedOcrBlockIds.has(old.id)) continue;
        if (old.id.startsWith("blk-manual-") || old.id.startsWith("blk-figure-")) {
          next.push(old);
          consumed.add(old.id);
          continue;
        }
        const fresh = incomingById.get(old.id);
        if (!fresh) {
          if (editedOcrBlockIds.has(old.id)) next.push(old);
          continue;
        }
        consumed.add(old.id);
        if (!editedOcrBlockIds.has(old.id)) {
          next.push(fresh);
          continue;
        }
        const baseline = originalOcrText.get(old.id) ?? "";
        const extension = baseline && fresh.text.startsWith(baseline) ? fresh.text.slice(baseline.length) : "";
        // 已校对的块：文字属于用户，OCR 的置信度提示不再适用，
        // 合并时不能把新鲜块的校对类警告覆盖回来。
        next.push({ ...old, bbox: fresh.bbox,
          warnings: fresh.warnings.filter((warning) => !isProofreadWarning(warning)), lowConfidence: false,
          text: old.text !== baseline && extension ? `${old.text}${extension}` : old.text });
      }
      for (const fresh of incoming) {
        if (consumed.has(fresh.id) || deletedOcrBlockIds.has(fresh.id)) continue;
        if (ocrOrderLocked) {
          next.push(fresh);
          continue;
        }
        const at = next.findIndex((old) => !old.id.startsWith("blk-manual-") && !old.id.startsWith("blk-figure-") &&
          old.tileIndex === fresh.tileIndex && old.bbox.y > fresh.bbox.y);
        if (at < 0) next.push(fresh);
        else next.splice(at, 0, fresh);
      }
      for (const figure of uploadedFigures) {
        if (next.some((block) => block.id === figure.block.id)) continue;
        // 重发布时块列表可能已因后续分片追加而变长：按锚定块 id 重新解析下标，
        // 快照下标只作兜底，避免插图被插到漂移后的位置。
        const anchoredAt = figure.anchorId === "end" ? next.length
          : figure.anchorId ? next.findIndex((block) => block.id === figure.anchorId)
          : -1;
        const at = anchoredAt >= 0 ? anchoredAt : figure.insertAt;
        next.splice(Math.max(0, Math.min(next.length, at)), 0, figure.block);
      }
      blocks.value = next;
    };

    try {
      if (ocrFile) {
        progressNote.value = "图片源和候选已可查看；正在识别长图文字…";
        const outcome = await ensureClient().recognize(ocrFile, { onPartial: (partial) => {
          if (runGeneration !== ocrRunGeneration) return;
          publishLines(0, partial.lines);
          progressNote.value = `首批结果可校对；正在识别长图第 ${partial.completedBands}/${partial.bandCount} 段…`;
          // Let the browser paint the first OCR blocks before the CPU pixel scan
          // competes for main-thread canvas and image-data work.
          schedulePixelScanAfterFirstPaint();
        } });
        lastRunMs.value = outcome.ms;
        publishLines(0, outcome.lines);
      } else {
        for (let index = 0; index < workingJob.tiles.length; index += 1) {
          progressNote.value = `图片源和候选已可查看；正在识别第 ${index + 1}/${workingJob.tiles.length} 张截图…`;
          const outcome = await ensureClient().recognize(workingJob.tiles[index].file, { onPartial: (partial) => {
            if (runGeneration !== ocrRunGeneration) return;
            publishLines(index, partial.lines);
            schedulePixelScanAfterFirstPaint();
          } });
          lastRunMs.value += outcome.ms;
          publishLines(index, outcome.lines);
        }
      }
      if (runGeneration !== ocrRunGeneration) return;
    const insertedBlockIsSelected = uploadedFigures.some((figure) => figure.block.id === selectedBlockId.value);
    if (insertedBlockIsSelected && step.value === "review") void nextTick(() => selectBlock(selectedBlockId.value));
    } catch (cause) {
      error.value = `文字 OCR 未完成：${cause instanceof Error ? cause.message : "本地识别失败"}。图片源和图片候选仍可继续校对。`;
    }
    // OCR boxes are auxiliary evidence only: a local geometry/texture pass has already
    // published candidates before OCR begins. When OCR succeeds, it may improve pale
    // regions that contain labels, but an OCR failure keeps the first pass visible.
    await startPixelScan();
    if (blocks.value.length && !scanSignal.aborted) {
      pixelScanning.value = true;
      const scanWidth = stitchedSize.value.width || tileVms[0]?.width || 1;
      const scanHeight = stitchedSize.value.height || tileVms[0]?.height || 1;
      const textBoxes = blocks.value.filter((block) => block.tileIndex === -1 || !stitchedFile.value)
        .map((block) => ({ x: block.bbox.x / scanWidth, y: block.bbox.y / scanHeight,
          width: block.bbox.width / scanWidth, height: block.bbox.height / scanHeight }));
      try {
        const refined = await scanPixels(textBoxes);
        if (!scanSignal.aborted) publishPixelCandidates(refined);
      } catch (cause) {
        if (!pixelCandidates.value.length) pixelScanError.value = cause instanceof Error ? cause.message : "本地图片区域检测失败";
      } finally {
        pixelScanning.value = false;
      }
    }
    if (!blocks.value.length && !error.value) {
      error.value = "这些截图上没有识别到文字。图片区域仍可查看；可确认候选或手动框选。";
    }
    // OCR 完成进入 review 后自动定位第一个待办（警告块或待确认候选），
    // 用户少一次人工扫视；失败时静默保持现状。
    void nextTick(() => { void focusFirstPendingReviewItem(); });
  } catch (cause) {
    step.value = "select";
    error.value = cause instanceof Error ? cause.message : "本地识别失败，请重试";
  } finally {
    if (runGeneration === ocrRunGeneration) {
      busy.value = false;
      progress.value = null;
      progressNote.value = "";
    }
  }
}

/** 手动区域模式：先让用户框选，裁剪后再识别。 */
function startCrop(job: ScreenshotJobInput) {
  currentJob.value = job;
  cropPurpose.value = "ocr";
  suggestedCrop.value = false;
  cropPrefillNote.value = "";
  cropPreviewUrl.value = "";
  const tile = job.tiles[0];
  const url = URL.createObjectURL(tile.file);
  objectUrls.push(url);
  cropState.value = {
    url,
    file: tile.file,
    natural: { width: tile.width || 1, height: tile.height || 1 },
    rect: null,
    dragging: false,
  };
  step.value = "crop";
  // 进入裁剪前自动预填主内容区域；用户仍可拖拽调整或点“重新框选”清掉。
  void prefillCropContentRegion();
}

/** 用像素分析把主内容区域预填进裁剪框；失败回退现状（空选区 + 提示）。 */
async function prefillCropContentRegion() {
  const state = cropState.value;
  if (!state) return;
  const region = await detectContentRegionFromFile(state.file);
  // 分析期间用户可能已自己开始拖框，或已切换到其他裁剪会话/步骤：不覆盖。
  if (cropState.value !== state || state.rect || step.value !== "crop") return;
  if (!region) {
    cropPrefillNote.value = "未能自动识别主内容区域，请手动拖出要识别的范围。";
    return;
  }
  state.rect = {
    x0: region.x0 * state.natural.width,
    y0: region.y0 * state.natural.height,
    x1: region.x1 * state.natural.width,
    y1: region.y1 * state.natural.height,
  };
}

function cropRectNormalized() {
  const rect = cropState.value?.rect;
  if (!rect) return null;
  const x0 = Math.max(0, Math.min(rect.x0, rect.x1));
  const x1 = Math.min(cropState.value!.natural.width, Math.max(rect.x0, rect.x1));
  const y0 = Math.max(0, Math.min(rect.y0, rect.y1));
  const y1 = Math.min(cropState.value!.natural.height, Math.max(rect.y0, rect.y1));
  if (x1 - x0 < 8 || y1 - y0 < 8) return null;
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
}

async function applyCropAndRecognize() {
  const state = cropState.value;
  const rect = cropRectNormalized();
  if (!state || !rect) {
    ElMessage.warning("请先在图上拖出要识别的区域");
    return;
  }
  const bitmap = await createImageBitmap(state.file);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(rect.width);
  canvas.height = Math.round(rect.height);
  canvas.getContext("2d")?.drawImage(bitmap, rect.x, rect.y, rect.width, rect.height, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, state.file.type || "image/png"));
  if (!blob) {
    error.value = "裁剪失败，请重试";
    return;
  }
  const cropped = new File([blob], state.file.name.replace(/\.\w+$/, "") + "-crop" + (state.file.name.match(/\.\w+$/)?.[0] ?? ""), {
    type: state.file.type || "image/png",
  });
  void runJob({
    tiles: [{ file: cropped, width: canvas.width, height: canvas.height, scrollX: 0, scrollY: 0 }],
    mode: "region",
    sourceUrl: sourceInfo.value?.sourceUrl ?? "",
    titleCandidate: sourceInfo.value?.titleCandidate ?? "",
    capturedAt: sourceInfo.value?.capturedAt,
    covered: undefined,
    truncated: false,
    warnings: [],
  });
}

function pickFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (file && !busy.value) void runJob({ tiles: [{ file, width: 0, height: 0, scrollX: 0, scrollY: 0 }], mode: "screen", sourceUrl: "", titleCandidate: "", warnings: [] });
}

function onDrop(event: DragEvent) {
  event.preventDefault();
  const file = event.dataTransfer?.files?.[0];
  if (file && !busy.value) void runJob({ tiles: [{ file, width: 0, height: 0, scrollX: 0, scrollY: 0 }], mode: "screen", sourceUrl: "", titleCandidate: "", warnings: [] });
}

function markEdited(blockId?: string) {
  edited.value = true;
  if (blockId) {
    editedOcrBlockIds.add(blockId);
    const block = blocks.value.find((item) => item.id === blockId);
    if (block) {
      if (!originalOcrText.has(blockId)) originalOcrText.set(blockId, block.text);
      // 用户改过文字/类型/层级即视为已校对该块：校对类提示完成使命，
      // 不再挂在“文字明明已经是对的”的块上；图片权限等状态提示保留。
      block.lowConfidence = false;
      block.warnings = block.warnings.filter((warning) => !isProofreadWarning(warning));
    }
  }
}

function imageAnchor(): number {
  const pane = imagePane.value;
  return (pane?.getBoundingClientRect().top ?? 0) + (pane?.clientHeight ?? 0) * 0.25;
}

function captureImagePageY(): number {
  const pane = imagePane.value;
  if (!pane) return 0;
  const anchor = imageAnchor();
  const images = [...pane.querySelectorAll<HTMLImageElement>(".ocr-image-wrap img")].filter((image) => image.complete && image.naturalHeight > 0);
  if (!images.length) return pane.scrollTop;
  const image = images.find((item) => {
    const rect = item.getBoundingClientRect();
    return rect.top <= anchor && rect.bottom >= anchor;
  }) ?? images.find((item) => item.getBoundingClientRect().bottom > anchor) ?? images[0]!;
  const imageRect = image.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (anchor - imageRect.top) / Math.max(1, imageRect.height)));
  const tileFigure = image.closest<HTMLElement>(".ocr-tile");
  if (tileFigure?.dataset.tileIndex && Number(tileFigure.dataset.tileIndex) >= 0) {
    const tileIndex = Number(tileFigure.dataset.tileIndex);
    const tile = tiles.value[tileIndex];
    if (tile) return tile.scrollY + ratio * (tile.coveredCssHeight ?? tile.height);
  }
  if (image.closest(".ocr-stitched") && currentJob.value?.selection) {
    const { top, bottom } = currentJob.value.selection;
    return top + ratio * (bottom - top);
  }
  return ratio * image.naturalHeight;
}

function captureReviewNavigation(): ReviewNavigationState {
  const pane = blocksPane.value;
  const cards = [...(pane?.querySelectorAll<HTMLElement>(".ocr-block-card") ?? [])];
  const selected = cards.find((card) => card.dataset.blockId === selectedBlockId.value);
  const anchor = pane?.getBoundingClientRect().top ?? 0;
  const visible = selected ?? cards.find((card) => card.getBoundingClientRect().bottom > anchor) ?? cards[0];
  const input = visible?.querySelector<HTMLTextAreaElement>("textarea");
  return {
    imagePageY: captureImagePageY(),
    imageScrollLeft: imagePane.value?.scrollLeft ?? 0,
    rightBlockId: visible?.dataset.blockId ?? selectedBlockId.value,
    rightBlockOffset: visible ? visible.getBoundingClientRect().top - anchor : 0,
    editorScrollTop: input?.scrollTop ?? 0,
    previewScrollTop: previewPane.value?.scrollTop ?? 0,
    selectedBlockId: selectedBlockId.value,
    showTiles: showTiles.value,
  };
}

function scrollImagePageY(pageY: number) {
  const pane = imagePane.value;
  if (!pane) return;
  const anchor = imageAnchor();
  let image: HTMLImageElement | undefined;
  let localY = 0;
  const useTiles = Boolean(stitchedUrl.value && showTiles.value);
  if (stitchedUrl.value && !useTiles) {
    image = pane.querySelector<HTMLImageElement>(".ocr-stitched .ocr-image-wrap img") ?? undefined;
    const selection = currentJob.value?.selection;
    const ratio = selection ? (pageY - selection.top) / Math.max(1, selection.bottom - selection.top) : 0;
    localY = Math.max(0, Math.min(1, ratio)) * (image?.naturalHeight ?? stitchedSize.value.height);
  } else if (useTiles) {
    const tile = [...tiles.value].reverse().find((item) => pageY >= item.scrollY) ?? tiles.value[0];
    if (tile) {
      const figure = pane.querySelector<HTMLElement>(`.ocr-tile[data-tile-index="${tile.index}"]`);
      image = figure?.querySelector<HTMLImageElement>(".ocr-image-wrap img") ?? undefined;
      localY = Math.max(0, Math.min(1, (pageY - tile.scrollY) / Math.max(1, tile.coveredCssHeight ?? tile.height))) * (image?.naturalHeight ?? tile.height);
    }
  } else {
    image = pane.querySelector<HTMLImageElement>('.ocr-tile[data-tile-index="0"] .ocr-image-wrap img') ?? undefined;
    localY = pageY;
  }
  if (!image) return;
  const imageRect = image.getBoundingClientRect();
  const renderedY = localY / Math.max(1, image.naturalHeight) * imageRect.height;
  pane.scrollTop = Math.max(0, pane.scrollTop + imageRect.top + renderedY - anchor);
}

async function waitForReviewLayout() {
  await nextTick();
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  const pane = imagePane.value;
  const images = [...(pane?.querySelectorAll<HTMLImageElement>("img") ?? [])];
  await Promise.all(images.map(async (image) => {
    if (image.complete && image.naturalWidth) return;
    try { await image.decode(); } catch { /* broken source remains visible for manual recovery */ }
  }));
  await nextTick();
}

async function restoreReviewNavigation(state: ReviewNavigationState, focusBlockId?: string) {
  step.value = "review";
  showTiles.value = state.showTiles;
  selectedBlockId.value = focusBlockId ?? state.selectedBlockId;
  await waitForReviewLayout();
  scrollImagePageY(state.imagePageY);
  if (imagePane.value) imagePane.value.scrollLeft = state.imageScrollLeft;
  const pane = blocksPane.value;
  const blockId = focusBlockId ?? state.rightBlockId;
  const card = pane?.querySelector<HTMLElement>(`[data-block-id="${CSS.escape(blockId)}"]`);
  if (pane && card) {
    const offset = focusBlockId ? pane.clientHeight * 0.25 : state.rightBlockOffset;
    if (focusBlockId) alignTextBlock(blockId);
    else pane.scrollTop = Math.max(0, pane.scrollTop + card.getBoundingClientRect().top - pane.getBoundingClientRect().top - offset);
    const editor = card.querySelector<HTMLTextAreaElement>("textarea");
    if (editor && !focusBlockId) editor.scrollTop = state.editorScrollTop;
  }
  if (previewPane.value) previewPane.value.scrollTop = state.previewScrollTop;
}

function enterImageCrop() {
  if (step.value === "review") cropReturnNavigation = captureReviewNavigation();
  step.value = "crop";
}

async function returnToReview() {
  const state = cropReturnNavigation ?? captureReviewNavigation();
  cropReturnNavigation = null;
  await restoreReviewNavigation(state);
}

async function toggleTileView() {
  const state = captureReviewNavigation();
  state.showTiles = !showTiles.value;
  await restoreReviewNavigation(state);
}

function scrollPaneTarget(pane: HTMLElement, target: HTMLElement, ratio = 0.25) {
  pane.scrollTop = Math.max(0, pane.scrollTop + target.getBoundingClientRect().top - pane.getBoundingClientRect().top - pane.clientHeight * ratio);
}

function alignTextBlock(id: string, ratio = 0.25) {
  const pane = blocksPane.value;
  const card = pane?.querySelector<HTMLElement>(`[data-block-id="${CSS.escape(id)}"]`);
  if (pane && card) scrollPaneTarget(pane, card, ratio);
}

// OCR can finish after an image upload has returned to review. Re-align the
// selected reference after that asynchronous replacement publishes its card.
watch(
  [() => blocks.value.map((block) => block.id).join("\u0000"), selectedBlockId, busy, step],
  async () => {
    const id = selectedBlockId.value;
    if (step.value !== "review" || busy.value || !id.startsWith("blk-figure-")) return;
    await nextTick();
    alignTextBlock(id);
  },
  { flush: "post" },
);

function deleteBlock(id: string) {
  const index = blocks.value.findIndex((block) => block.id === id);
  if (index < 0) return;
  blocks.value = blocks.value.filter((block) => block.id !== id);
  deletedOcrBlockIds.add(id);
  const next = blocks.value[Math.min(index, blocks.value.length - 1)];
  selectedBlockId.value = next?.id ?? "";
  markEdited();
  if (next) void nextTick(() => selectBlock(next.id));
}

function moveBlock(id: string, offset: number) {
  const index = blocks.value.findIndex((block) => block.id === id);
  const target = index + offset;
  if (index < 0 || target < 0 || target >= blocks.value.length) return;
  const next = [...blocks.value];
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item);
  blocks.value = next;
  ocrOrderLocked = true;
  selectedBlockId.value = id;
  markEdited();
  void nextTick(() => selectBlock(id));
}

function addBlockAfter(id: string, kind: OcrBlockKind) {
  const index = blocks.value.findIndex((block) => block.id === id);
  const block: EditableBlockVM = {
    id: `blk-manual-${Date.now()}`,
    tileIndex: blocks.value[index]?.tileIndex ?? 0,
    kind,
    level: 3,
    text: "",
    warnings: [],
    bbox: { x: 0, y: 0, width: 0, height: 0 },
    lowConfidence: false,
  };
  if (index >= 0) blocks.value.splice(index + 1, 0, block);
  else blocks.value.push(block);
  selectedBlockId.value = block.id;
  markEdited();
}

const KIND_LABELS: Record<OcrBlockKind, string> = {
  heading: "标题",
  paragraph: "段落",
  list: "列表",
  code: "代码（需校对）",
};

function selectBlock(id: string) {
  selectedBlockId.value = id;
  void nextTick(() => {
    alignTextBlock(id);
    const picturePane = imagePane.value;
    const block = blocks.value.find((item) => item.id === id);
    if (!picturePane || !block?.bbox.width || !block.bbox.height) return;
    const overlaySelector = showTiles.value && block.tileIndex >= 0
      ? `.ocr-tile[data-tile-index="${block.tileIndex}"] [data-block-id="${CSS.escape(id)}"]`
      : !showTiles.value && stitchedUrl.value
        ? `.ocr-stitched [data-block-id="${CSS.escape(id)}"]`
        : `.ocr-tile[data-tile-index="${block.tileIndex}"] [data-block-id="${CSS.escape(id)}"]`;
    const overlay = picturePane.querySelector<HTMLElement>(overlaySelector);
    if (overlay) {
      scrollPaneTarget(picturePane, overlay);
    } else if (showTiles.value && block.tileIndex === -1 && currentJob.value?.selection) {
      const { top, bottom } = currentJob.value.selection;
      scrollImagePageY(top + block.bbox.y / Math.max(1, stitchedSize.value.height) * (bottom - top));
    }
  });
}

function blocksForTile(tileIndex: number): EditableBlockVM[] {
  return blocks.value.filter((block) => block.tileIndex === tileIndex && block.bbox.width > 0 && block.bbox.height > 0);
}

function overlayStyle(block: EditableBlockVM, tile: { width: number; height: number }) {
  if (!tile.width || !tile.height) return { display: "none" };
  return {
    left: `${(block.bbox.x / tile.width) * 100}%`,
    top: `${(block.bbox.y / tile.height) * 100}%`,
    width: `${(block.bbox.width / tile.width) * 100}%`,
    height: `${(block.bbox.height / tile.height) * 100}%`,
  };
}

function tileMetaLabel(tile: TileVM): string {
  if (coverage.value?.mode === "longpage") return `视口 ${tile.index + 1} · 页面 ${Math.round(tile.scrollY)}px 处`;
  return `视口 ${tile.index + 1}`;
}

function downloadMarkdown() {
  const blob = new Blob([markdown.value], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${(imageLabel.value || "screenshot").replace(/\.(png|jpe?g|webp)$/i, "") || "screenshot"}.md`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadSourceTile(index: number) {
  const file = currentJob.value?.tiles[index]?.file;
  if (!file) return;
  const url = URL.createObjectURL(file);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = file.name || `screenshot-${index + 1}.png`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

function downloadStitched() {
  if (!stitchedFile.value || !stitchedUrl.value) return;
  const anchor = document.createElement("a");
  anchor.href = stitchedUrl.value;
  anchor.download = stitchedFile.value.name;
  anchor.click();
}

async function saveFigure(file: File, target: "private_note" | "article_draft", signal?: AbortSignal): Promise<string> {
  const uploadUrl = target === "private_note" ? "/api/agent/blog/notes/images/" : "/api/agent/blog/images/";
  const form = new FormData();
  form.append("image", file);
  const response = await fetch(uploadUrl, { method: "POST", body: form, signal });
  const result = await response.json().catch(() => ({})) as { url?: string; detail?: string };
  if (!response.ok) throw new Error(result.detail ?? `图片上传失败（HTTP ${response.status}）`);
  const url = result.url ?? "";
  const validUrl = target === "private_note"
    ? /^\/api\/agent\/blog\/notes\/images\/\d+\/$/.test(url)
    : /^\/media\/blog\/[a-zA-Z0-9_.-]+$/.test(url);
  if (!validUrl) throw new Error("图片服务返回了异常地址，已放弃插入引用");
  const readBack = await fetch(url, { method: "GET", signal });
  if (!readBack.ok) throw new Error("图片上传后无法读回，已放弃插入引用");
  return url;
}

async function requestApply() {
  if (applying.value) return;
  if (!markdown.value.trim()) {
    ElMessage.warning("没有可用的正文内容");
    return;
  }
  const target = saveTarget.value;
  const imagesToConvert = uploadedFigures.filter((image) => image.target !== target && blocks.value.some((block) => block.text.includes(image.url)));
  applying.value = true;
  try {
    const incompatiblePath = target === "article_draft"
      ? /\/api\/agent\/blog\/notes\/images\/\d+\//g
      : /\/media\/blog\/[a-zA-Z0-9_.-]+/g;
    const untrackedReferences = [...new Set(markdown.value.match(incompatiblePath) ?? [])]
      .filter((path) => !imagesToConvert.some((image) => image.url === path));
    if (untrackedReferences.length) {
      throw new Error("正文包含无法自动转换的图片地址，请在当前目标重新插入这些图片");
    }
    if (target === "article_draft" && imagesToConvert.some((image) => image.target === "private_note")) {
      await ElMessageBox.confirm(
        `有 ${imagesToConvert.length} 张插图保存在私有空间。转为博客草稿会把裁剪后的图片上传到可通过图片地址访问的博客媒体。是否继续？`,
        "转换插图存储",
        { type: "warning", confirmButtonText: "转换并继续", cancelButtonText: "取消" },
      );
    }
    for (const image of imagesToConvert) {
      const nextUrl = await saveFigure(image.file, target);
      for (const block of blocks.value) {
        if (block.text.includes(image.url)) {
          block.text = block.text.split(image.url).join(nextUrl);
          block.warnings = [target === "private_note" ? "私有图片引用：保存笔记后本人可读" : "博客图片引用：提交公开前请核对图片使用权"];
        }
      }
      image.url = nextUrl;
      image.target = target;
      markEdited();
    }
    if (incompatiblePath.test(markdown.value)) {
      throw new Error("仍有图片地址与当前目标权限不匹配，请检查后重试");
    }
    emit("applyContent", { title: suggestTitle(), content: markdown.value, target });
  } catch (cause) {
    if (cause !== "cancel" && cause !== "close") {
      const detail = cause instanceof Error ? cause.message : "插图转换失败，请重试";
      ElMessage.error(detail);
    }
  } finally {
    applying.value = false;
  }
}

/**
 * 保留插图：把选中区域裁出、上传到现有私有图片接口，
 * 读回确认（GET 返回 200）后才插入引用；失败保持原内容不变。
 * @returns 是否成功插入引用；「智能确认」按该返回值计数，不影响其他忽略返回值的调用点。
 */
async function uploadCropAsImage(): Promise<boolean> {
  const state = cropState.value;
  const rect = cropRectNormalized();
  if (state?.file === stitchedFile.value && longCropClickStage.value !== 2) {
    ElMessage.warning("请在长图上依次点击插图左上角和右下角");
    return false;
  }
  if (!state || !rect) {
    ElMessage.warning("请先在图上拖出要保留的插图区域");
    return false;
  }
  if (!Number.isFinite(rect.x) || rect.width < 8 || rect.height < 8) {
    ElMessage.warning("所选区域太小");
    return false;
  }
  uploadingImage.value = true;
  imageUploadController?.abort();
  imageUploadController = new AbortController();
  try {
    const cropKey = JSON.stringify(rect);
    const croppedFile = previewCropFile && previewCropKey === cropKey ? previewCropFile : await buildFigureFile(rect);
    const imageTarget = saveTarget.value;
    const imageUrl = await saveFigure(croppedFile, imageTarget, imageUploadController.signal);
    if (imageTextPolicy.value === "image_only") {
      const sourceRect = state.file === stitchedFile.value
        ? { x: rect.x / state.natural.width * stitchedSize.value.width,
            y: rect.y / state.natural.height * stitchedSize.value.height,
            width: rect.width / state.natural.width * stitchedSize.value.width,
            height: rect.height / state.natural.height * stitchedSize.value.height }
        : rect;
      blocks.value = blocks.value.filter((block) => {
        if (state.file === stitchedFile.value && block.tileIndex !== -1) return true;
        return !isTextCoveredByRect(block, sourceRect);
      });
    }
    const reference = `![截图插图](${imageUrl})`;
    const anchorIndex = blocks.value.findIndex((block) => block.id === selectedBlockId.value);
    // 插入位置三级兜底：锚定块（预填/手选时快照的 id，防 OCR 流式追加导致下标漂移）
    // > 按裁剪框纵向位置现算 > 选中块之后/正文末尾
    const insertAt = resolveFigureInsertAt(figureInsertIndex.value ?? autoInsertIndexForState(state, rect) ??
      (anchorIndex >= 0 ? anchorIndex + 1 : blocks.value.length));
    const newBlock: EditableBlockVM = {
      id: `blk-figure-${Date.now()}`,
      tileIndex: state.tileIndex ?? blocks.value[anchorIndex]?.tileIndex ?? 0,
      kind: "paragraph",
      level: 3,
      text: reference,
      warnings: [imageTarget === "private_note" ? "私有图片引用：保存笔记后本人可读" : "博客图片引用：提交公开前请核对图片使用权"],
      bbox: { x: 0, y: 0, width: 0, height: 0 },
      lowConfidence: false,
    };
    const sourceRect = state.file === stitchedFile.value
      ? { x: rect.x / state.natural.width * stitchedSize.value.width,
          y: rect.y / state.natural.height * stitchedSize.value.height,
          width: rect.width / state.natural.width * stitchedSize.value.width,
          height: rect.height / state.natural.height * stitchedSize.value.height }
      : rect;
    blocks.value.splice(insertAt, 0, newBlock);
    uploadedFigures.push({ url: imageUrl, target: imageTarget, file: croppedFile, block: newBlock, insertAt,
      anchorId: figureInsertAnchorId.value ?? "end",
      sourceRect, sourceTileIndex: state.tileIndex ?? 0, sourceIsStitched: state.file === stitchedFile.value,
      textPolicy: imageTextPolicy.value });
    if (activeCandidateKey.value) insertedCandidateKeys.value.push(activeCandidateKey.value);
    activeCandidateKey.value = null;
    figureInsertIndex.value = null;
    figureInsertAnchorId.value = null;
    markEdited();
    const navigation = cropReturnNavigation ?? captureReviewNavigation();
    cropReturnNavigation = null;
    await restoreReviewNavigation(navigation, newBlock.id);
    ElMessage.success(imageTarget === "private_note" ? "插图已保存为私有图片并插入引用" : "插图已保存为博客图片并插入引用");
    return true;
  } catch (cause) {
    if (imageUploadController?.signal.aborted) return false;
    error.value = cause instanceof Error ? cause.message : "插图上传失败，请重试";
    ElMessage.error(error.value);
    return false;
  } finally {
    imageUploadController = null;
    uploadingImage.value = false;
  }
}

/** 校对区源图上直接拖拽框选配图：候选漏判时用户自己圈出图片区域。 */
interface ReviewImageSource {
  key: string;
  file: File;
  natural: { width: number; height: number };
  url: string;
  tileIndex: number;
}

const reviewDrag = ref<{
  source: ReviewImageSource;
  startX: number;
  startY: number;
  x: number;
  y: number;
} | null>(null);

function stitchedDragSource(): ReviewImageSource | null {
  if (!stitchedFile.value || !stitchedUrl.value) return null;
  return { key: "stitched", file: stitchedFile.value, natural: stitchedSize.value, url: stitchedUrl.value, tileIndex: -1 };
}

function tileDragSource(tile: TileVM): ReviewImageSource | null {
  const file = tileFiles.get(tile.index);
  if (!file) return null;
  return { key: `tile:${tile.index}`, file, natural: { width: tile.width, height: tile.height }, url: tile.url, tileIndex: tile.index };
}

function reviewImagePoint(event: MouseEvent, image: HTMLImageElement, natural: { width: number; height: number }) {
  const bounds = image.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(natural.width, (event.clientX - bounds.left) / Math.max(1, bounds.width) * natural.width)),
    y: Math.max(0, Math.min(natural.height, (event.clientY - bounds.top) / Math.max(1, bounds.height) * natural.height)),
  };
}

function onReviewImageMouseDown(event: MouseEvent, source: ReviewImageSource | null) {
  if (event.button !== 0 || !source) return;
  const image = (event.currentTarget as HTMLElement).querySelector("img");
  if (!image) return;
  const point = reviewImagePoint(event, image, source.natural);
  event.preventDefault();
  reviewDrag.value = { source, startX: point.x, startY: point.y, x: point.x, y: point.y };
  // 拖出图片边缘后松手也要收尾：用最后已知位置结束，交给窗口级监听兜底
  window.addEventListener("mouseup", () => finalizeReviewDrag(), { once: true });
}

function onReviewImageMouseMove(event: MouseEvent, source: ReviewImageSource | null) {
  const drag = reviewDrag.value;
  if (!drag || !source || drag.source.key !== source.key) return;
  const image = (event.currentTarget as HTMLElement).querySelector("img");
  if (!image) return;
  const point = reviewImagePoint(event, image, source.natural);
  drag.x = point.x;
  drag.y = point.y;
}

function onReviewImageMouseUp(event: MouseEvent, source: ReviewImageSource | null) {
  const drag = reviewDrag.value;
  if (!drag || !source || drag.source.key !== source.key) return;
  const image = (event.currentTarget as HTMLElement).querySelector("img");
  if (image) {
    const point = reviewImagePoint(event, image, source.natural);
    drag.x = point.x;
    drag.y = point.y;
  }
  finalizeReviewDrag();
}

/** 收尾拖选：位移过小视为普通点击（保留块定位/候选点选），足够大才进入裁剪确认。 */
function finalizeReviewDrag(): void {
  const drag = reviewDrag.value;
  reviewDrag.value = null;
  if (!drag) return;
  const rect = {
    x0: Math.min(drag.startX, drag.x), y0: Math.min(drag.startY, drag.y),
    x1: Math.max(drag.startX, drag.x), y1: Math.max(drag.startY, drag.y),
  };
  if (rect.x1 - rect.x0 < 8 || rect.y1 - rect.y0 < 8) return;
  openManualFigureCrop(rect, drag.source);
}

const reviewDragStyle = computed(() => {
  const drag = reviewDrag.value;
  if (!drag) return {};
  const { width, height } = drag.source.natural;
  const left = Math.min(drag.startX, drag.x);
  const top = Math.min(drag.startY, drag.y);
  return {
    left: `${left / Math.max(1, width) * 100}%`,
    top: `${top / Math.max(1, height) * 100}%`,
    width: `${Math.abs(drag.x - drag.startX) / Math.max(1, width) * 100}%`,
    height: `${Math.abs(drag.y - drag.startY) / Math.max(1, height) * 100}%`,
  };
});

/** 拖选完成后进入与候选点击相同的确认流程：预填裁剪框与插入位置，上传前仍需确认。 */
function openManualFigureCrop(
  rect: { x0: number; y0: number; x1: number; y1: number },
  source: ReviewImageSource,
) {
  cropPurpose.value = "image";
  suggestedCrop.value = true;
  cropPreviewUrl.value = "";
  longCropClickStage.value = 2;
  figureInsertIndex.value = null;
  figureInsertAnchorId.value = null;
  figureInsertIndexTouched.value = false;
  activeCandidateKey.value = null;
  cropState.value = {
    url: source.url,
    file: source.file,
    natural: { ...source.natural },
    rect,
    dragging: false,
    tileIndex: source.tileIndex,
  };
  enterImageCrop();
  applyAutoInsertIndex();
  void nextTick(focusAndPreviewCrop);
}

/** 从校对区进入插图裁剪：以选中块所在视口为源图。 */
function cropFigureFromSource() {
  const anchorTile = blocks.value.find((block) => block.id === selectedBlockId.value)?.tileIndex ?? 0;
  const tile = tiles.value[anchorTile] ?? tiles.value[0];
  if (!tile) {
    ElMessage.warning("没有可用的源图");
    return;
  }
  // 从已显示的 tile URL 反查原 File：tiles 由本地 File 创建，可直接引用
  const sourceFile = stitchedFile.value ?? tileFiles.get(tile.index);
  if (!sourceFile) {
    ElMessage.warning("本地文件不可用，请重新选择截图");
    return;
  }
  cropPurpose.value = "image";
  suggestedCrop.value = false;
  cropPreviewUrl.value = "";
  longCropClickStage.value = 0;
  figureInsertIndex.value = null;
  figureInsertAnchorId.value = null;
  figureInsertIndexTouched.value = false;
  activeCandidateKey.value = null;
  cropState.value = {
    url: stitchedUrl.value || tile.url,
    file: sourceFile,
    natural: stitchedFile.value ? stitchedSize.value : { width: tile.width, height: tile.height },
    rect: null,
    dragging: false,
    tileIndex: tile.index,
  };
  enterImageCrop();
}

function candidateKey(tileIndex: number, candidateIndex: number): string {
  return `${tileIndex}:${candidateIndex}`;
}

/** 整图纵向像素 → 默认插入序号：插到第一个中心点之下的文字块之前。
 * 兼容两种块坐标系：整图/单图 OCR 的块（tileIndex -1，bbox 即整图像素），
 * 以及逐屏 OCR 的块（tileIndex 为屏号，bbox 是屏内像素，需先把整图 Y 换算回所在屏）。 */
function insertIndexForStitchedY(stitchedY: number): number {
  if (blocks.value.some((block) => block.tileIndex === -1)) {
    const index = blocks.value.findIndex((block) => block.tileIndex === -1 && block.bbox.y > stitchedY);
    return index < 0 ? blocks.value.length : index;
  }
  const job = currentJob.value;
  const selection = job?.selection;
  if (!selection || selection.bottom <= selection.top) return blocks.value.length;
  const pageY = selection.top + stitchedY / Math.max(1, stitchedSize.value.height) * (selection.bottom - selection.top);
  for (const tile of tiles.value) {
    const cssHeight = tile.coveredCssHeight ?? job?.viewport?.height ?? 0;
    if (!cssHeight || pageY >= tile.scrollY + cssHeight) continue;
    if (pageY < tile.scrollY) continue;
    const localY = (pageY - tile.scrollY) / cssHeight * tile.height;
    const index = blocks.value.findIndex((block) => block.tileIndex > tile.index ||
      (block.tileIndex === tile.index && block.bbox.y > localY));
    return index < 0 ? blocks.value.length : index;
  }
  return blocks.value.length;
}

/** 当前裁剪来源与归一化裁剪框 → 默认插入序号；无法定位时返回 null 交给调用方兜底。 */
function autoInsertIndexForState(
  state: NonNullable<typeof cropState.value>,
  rect: { y: number; height: number },
): number | null {
  const centerY = rect.y + rect.height / 2;
  if (state.file === stitchedFile.value) {
    return insertIndexForStitchedY(centerY);
  }
  const tile = tiles.value[state.tileIndex ?? 0];
  if (!tile) return null;
  if (stitchedFile.value && currentJob.value?.selection) {
    // 从单屏源图裁剪：先换算回页面 CSS 纵坐标，再映射到整图坐标
    const selection = currentJob.value.selection;
    const pageY = tile.scrollY + centerY / state.natural.height * (tile.coveredCssHeight ?? currentJob.value.viewport?.height ?? 0);
    return insertIndexForStitchedY((pageY - selection.top) / (selection.bottom - selection.top) * stitchedSize.value.height);
  }
  const nextBlock = blocks.value.findIndex((block) => block.tileIndex > tile.index ||
    (block.tileIndex === tile.index && block.bbox.y > centerY));
  return nextBlock < 0 ? blocks.value.length : nextBlock;
}

/** 按当前裁剪框刷新默认插入位置；用户在本次会话里明确选过就不覆盖。
 * 用归一化裁剪框：小于 8px 的退化框（如长图两击式的第一下）先不预填。 */
function applyAutoInsertIndex() {
  const state = cropState.value;
  if (!state || figureInsertIndexTouched.value) return;
  const rect = cropRectNormalized();
  if (!rect) return;
  const auto = autoInsertIndexForState(state, rect);
  if (auto === null) return;
  figureInsertIndex.value = auto;
  figureInsertAnchorId.value = auto >= blocks.value.length ? "end" : blocks.value[auto]?.id ?? "end";
}

/** 用户在下拉里选择后快照锚定块：即使后续 OCR 分片继续追加，位置也不漂移。 */
function onFigureInsertSelect() {
  figureInsertIndexTouched.value = true;
  const value = figureInsertIndex.value;
  figureInsertAnchorId.value = value === null || value >= blocks.value.length ? "end" : blocks.value[value]?.id ?? "end";
}

/** 把锚定块解析为当前列表的下标；锚块被删或列表重建失败时退回传入的兜底值。 */
function resolveFigureInsertAt(fallback: number): number {
  const anchor = figureInsertAnchorId.value;
  if (anchor === "end") return blocks.value.length;
  if (anchor) {
    const at = blocks.value.findIndex((block) => block.id === anchor);
    if (at >= 0) return at;
  }
  return fallback;
}

/** 用户点选黄色候选框后预填裁剪区域；本人仍要确认上传。 */
function cropSuggestedFigure(tile: TileVM, candidateIndex: number) {
  const candidate = tile.imageCandidates[candidateIndex];
  const sourceFile = tileFiles.get(tile.index);
  if (!candidate || !sourceFile) return;
  const rect = {
    x0: candidate.x * tile.width,
    y0: candidate.y * tile.height,
    x1: (candidate.x + candidate.width) * tile.width,
    y1: (candidate.y + candidate.height) * tile.height,
  };
  figureInsertIndex.value = null;
  figureInsertAnchorId.value = null;
  figureInsertIndexTouched.value = false;
  activeCandidateKey.value = candidateKey(tile.index, candidateIndex);
  cropPurpose.value = "image";
  suggestedCrop.value = true;
  cropPreviewUrl.value = "";
  longCropClickStage.value = 0;
  cropState.value = {
    url: tile.url,
    file: sourceFile,
    natural: { width: tile.width, height: tile.height },
    rect,
    dragging: false,
    tileIndex: tile.index,
  };
  enterImageCrop();
  applyAutoInsertIndex();
  void nextTick(focusAndPreviewCrop);
}

function cropStitchedCandidate(candidate: (typeof stitchedCandidates.value)[number]) {
  if (!stitchedFile.value || !stitchedUrl.value) return;
  const tile = tiles.value[candidate.tileIndex];
  const rect = { x0: candidate.x * stitchedSize.value.width, y0: candidate.y * stitchedSize.value.height,
    x1: (candidate.x + candidate.width) * stitchedSize.value.width, y1: (candidate.y + candidate.height) * stitchedSize.value.height };
  figureInsertIndex.value = null;
  figureInsertAnchorId.value = null;
  figureInsertIndexTouched.value = false;
  activeCandidateKey.value = `whole:${candidate.key}`;
  cropPurpose.value = "image";
  suggestedCrop.value = true;
  cropPreviewUrl.value = "";
  longCropClickStage.value = 2;
  cropState.value = {
    url: stitchedUrl.value,
    file: stitchedFile.value,
    natural: stitchedSize.value,
    rect,
    dragging: false,
    tileIndex: tile?.index,
  };
  enterImageCrop();
  applyAutoInsertIndex();
  void nextTick(focusAndPreviewCrop);
}

function cropPixelTileCandidate(candidate: PixelCandidate) {
  const tile = tiles.value[0];
  const sourceFile = tileFiles.get(0);
  if (!tile || !sourceFile) return;
  cropPurpose.value = "image";
  suggestedCrop.value = true;
  cropPreviewUrl.value = "";
  longCropClickStage.value = 0;
  activeCandidateKey.value = candidate.key;
  figureInsertIndex.value = null;
  figureInsertAnchorId.value = null;
  figureInsertIndexTouched.value = false;
  cropState.value = { url: tile.url, file: sourceFile, natural: { width: tile.width, height: tile.height },
    rect: { x0: candidate.x * tile.width, y0: candidate.y * tile.height,
      x1: (candidate.x + candidate.width) * tile.width, y1: (candidate.y + candidate.height) * tile.height },
    dragging: false, tileIndex: tile.index };
  enterImageCrop();
  applyAutoInsertIndex();
  void nextTick(focusAndPreviewCrop);
}

/** 推荐框打开后定位到它，并提供实际裁剪预览；用户可确认或重新框选。 */
function focusAndPreviewCrop() {
  const state = cropState.value;
  const image = cropImageRef.value;
  if (!state || !image?.complete || !image.naturalWidth) return;
  if (suggestedCrop.value && state.rect && cropPaneRef.value) {
    const centerY = (state.rect.y0 + state.rect.y1) / 2;
    cropPaneRef.value.scrollTop = Math.max(0, centerY / state.natural.height * image.clientHeight - cropPaneRef.value.clientHeight / 2);
  }
  refreshCropPreview();
}

async function buildFigureFile(rect: { x: number; y: number; width: number; height: number }): Promise<File> {
  const state = cropState.value;
  if (!state) throw new Error("裁剪源图已失效，请返回重试");
  let blob: Blob;
  if (state.file === stitchedFile.value && currentJob.value?.selection && currentJob.value.viewport?.height) {
    const originalTiles = currentJob.value.tiles;
    const file = await cropFromOriginalTiles(originalTiles, currentJob.value.selection,
      { x: rect.x / state.natural.width, y: rect.y / state.natural.height,
        width: rect.width / state.natural.width, height: rect.height / state.natural.height }, currentJob.value.viewport.height);
    blob = file;
  } else {
    const bitmap = await createImageBitmap(state.file);
    const pixelScale = Math.min(1, Math.sqrt(20_000_000 / (rect.width * rect.height)));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.floor(rect.width * pixelScale));
    canvas.height = Math.max(1, Math.floor(rect.height * pixelScale));
    const context = canvas.getContext("2d");
    if (!context) { bitmap.close(); throw new Error("浏览器无法裁剪插图"); }
    context.drawImage(bitmap, rect.x, rect.y, rect.width, rect.height, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const encoded = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!encoded) throw new Error("裁剪失败，请重试");
    blob = encoded;
  }
  if (blob.size > 5 * 1024 * 1024) {
    const bitmap = await createImageBitmap(blob);
    const canvas = document.createElement("canvas");
    const scale = Math.min(1, Math.sqrt(18_000_000 / (bitmap.width * bitmap.height)));
    canvas.width = Math.max(1, Math.floor(bitmap.width * scale));
    canvas.height = Math.max(1, Math.floor(bitmap.height * scale));
    const context = canvas.getContext("2d");
    if (!context) { bitmap.close(); throw new Error("浏览器无法压缩插图"); }
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    for (const quality of [0.92, 0.82, 0.7]) {
      const compressed = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
      if (compressed && compressed.size <= 5 * 1024 * 1024) { blob = compressed; break; }
    }
  }
  if (blob.size > 5 * 1024 * 1024) throw new Error("插图压缩后仍超过 5 MiB，请缩小范围或分段插入");
  return new File([blob], blob.type === "image/jpeg" ? "screenshot-figure.jpg" : "screenshot-figure.png", { type: blob.type });
}

async function refreshCropPreview() {
  cropPreviewUrl.value = "";
  previewCropFile = null;
  previewCropKey = "";
  if (previewCropObjectUrl) URL.revokeObjectURL(previewCropObjectUrl);
  previewCropObjectUrl = "";
  if (cropPurpose.value !== "image") return;
  const rect = cropRectNormalized();
  const image = cropImageRef.value;
  if (!rect || !image?.complete || !image.naturalWidth) return;
  try {
    const file = await buildFigureFile(rect);
    previewCropFile = file;
    previewCropKey = JSON.stringify(rect);
    previewCropObjectUrl = URL.createObjectURL(file);
    cropPreviewUrl.value = previewCropObjectUrl;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "无法生成裁剪预览";
  }
}

function replaceSuggestedCrop() {
  if (!cropState.value) return;
  suggestedCrop.value = false;
  cropState.value.rect = null;
  cropPreviewUrl.value = "";
  longCropClickStage.value = 0;
  // 重新框选是新意图：允许自动插入位置跟随新画的区域
  figureInsertIndex.value = null;
  figureInsertAnchorId.value = null;
  figureInsertIndexTouched.value = false;
}

function candidateStyle(candidate: NonNullable<ScreenshotTileInput["imageCandidates"]>[number]) {
  return {
    left: `${candidate.x * 100}%`,
    top: `${candidate.y * 100}%`,
    width: `${candidate.width * 100}%`,
    height: `${candidate.height * 100}%`,
  };
}

function candidateRejectStyle(candidate: { x: number; y: number; width: number }) {
  return { left: `${(candidate.x + candidate.width) * 100}%`, top: `${candidate.y * 100}%` };
}

function rejectFigureCandidate(key: string) {
  if (!rejectedCandidateKeys.value.includes(key)) rejectedCandidateKeys.value.push(key);
  ElMessage.info("已拒绝此图片建议；需要时可通过手动框选重新保留");
}

/**
 * 像素建议的自动接受置信度阈值：与 detectPixelImageCandidatesAcrossTiles 里
 * 「像素建议有独立色彩/边界证据即保留」的 0.55 门槛保持一致；低于它的
 * 像素建议只是弱提示（多为文字/分隔线误报），保留给人工逐个判断。
 * 网页图片（DOM）候选不依赖该阈值：按 priority（≥2 即非悬浮元素/图标且完整可见）
 * 与覆盖完整性筛选。
 */
const SMART_ACCEPT_PIXEL_CONFIDENCE = 0.55;
const smartConfirming = ref(false);

interface SmartConfirmTask {
  /** 对应候选的拒绝/已插入登记 key，执行前再查一次避免批量中途状态漂移。 */
  key: string;
  /** 复用单候选点击入口；返回是否成功插入引用（uploadCropAsImage 的显式布尔）。 */
  run: () => Promise<boolean>;
}

/** 收集当前可自动接受的高置信度候选（与单候选点击共用同一套裁剪/上传入口）。 */
function collectSmartConfirmTasks(): SmartConfirmTask[] {
  const tasks: SmartConfirmTask[] = [];
  if (stitchedFile.value) {
    // 长图模式：逐屏候选已在拼接坐标里合并，只处理拼接长图上的候选，避免同一图片重复插入。
    for (const candidate of stitchedCandidates.value) {
      const isPixel = candidate.origin === "pixels";
      if (isPixel ? (candidate.confidence ?? 0) < SMART_ACCEPT_PIXEL_CONFIDENCE : candidate.coverage !== "complete") continue;
      tasks.push({ key: `whole:${candidate.key}`, run: () => { cropStitchedCandidate(candidate); return uploadCropAsImage(); } });
    }
    return tasks;
  }
  for (const tile of tiles.value) {
    tile.imageCandidates.forEach((candidate, index) => {
      if ((candidate.priority ?? 2) < 2) return;
      tasks.push({ key: candidateKey(tile.index, index), run: () => { cropSuggestedFigure(tile, index); return uploadCropAsImage(); } });
    });
  }
  for (const candidate of pixelCandidates.value) {
    if ((candidate.confidence ?? 0) < SMART_ACCEPT_PIXEL_CONFIDENCE) continue;
    tasks.push({ key: candidate.key, run: () => { cropPixelTileCandidate(candidate); return uploadCropAsImage(); } });
  }
  return tasks;
}

/**
 * 一键智能确认：批量自动接受高置信度候选。每个候选都走与单候选点击
 * 完全相同的预填裁剪框 → 上传 → 插入引用流程；本按钮的点击本身就是
 * 隐私不变量要求的「用户确认后才上传」那次显式动作。单张失败不中断其余。
 */
async function smartConfirmCandidates() {
  if (smartConfirming.value || busy.value || step.value !== "review") return;
  const tasks = collectSmartConfirmTasks().filter((task) =>
    !rejectedCandidateKeys.value.includes(task.key) && !insertedCandidateKeys.value.includes(task.key));
  if (!tasks.length) {
    ElMessage.info("没有可自动确认的高置信度候选；其余候选请逐个检查或手动框选。");
    return;
  }
  smartConfirming.value = true;
  let accepted = 0;
  const failures: string[] = [];
  try {
    for (let index = 0; index < tasks.length; index += 1) {
      const task = tasks[index]!;
      if (rejectedCandidateKeys.value.includes(task.key) || insertedCandidateKeys.value.includes(task.key)) continue;
      // 弹窗被关闭或用户已离开校对步骤时停止批量流程
      if (!props.modelValue || step.value !== "review") break;
      progressNote.value = `智能确认中 ${index + 1}/${tasks.length}…`;
      try {
        // 按显式返回值计数：成功 true；早退守卫（区域过小、无选区等）与上传异常均为 false。
        if (await task.run()) accepted += 1;
        else failures.push(`候选 ${index + 1} 上传失败`);
      } catch (cause) {
        failures.push(cause instanceof Error ? cause.message : `候选 ${index + 1} 上传失败`);
      }
    }
  } finally {
    smartConfirming.value = false;
    progressNote.value = "";
  }
  if (failures.length) {
    ElMessage.warning(`智能确认完成：${accepted} 张已插入，${failures.length} 张失败（${failures[0]}${failures.length > 1 ? " 等" : ""}）。`);
  } else {
    ElMessage.success(`智能确认完成，已插入 ${accepted} 张图片引用。`);
  }
  void nextTick(() => { void focusFirstPendingReviewItem(); });
}

/**
 * 自动定位 review 的第一个待办：优先选中第一个带警告/低置信度的文字块
 * （同时联动左侧源图与右侧校对列表滚动）；没有文字待办时滚动到第一个
 * 待确认的图片候选框。对话框当前没有折叠面板，无需展开动作。
 */
async function focusFirstPendingReviewItem() {
  if (step.value !== "review") return;
  await waitForReviewLayout();
  if (step.value !== "review" || smartConfirming.value) return;
  const pendingBlock = blocks.value.find((block) => block.lowConfidence || block.warnings.length > 0);
  if (pendingBlock) {
    selectBlock(pendingBlock.id);
    return;
  }
  const pane = imagePane.value;
  const candidate = pane?.querySelector<HTMLElement>(".ocr-image-candidate");
  if (pane && candidate) scrollPaneTarget(pane, candidate);
}

function visibleTileCandidates(tile: TileVM) {
  return tile.imageCandidates.map((candidate, index) => ({ candidate, index }))
    .filter(({ index }) => !rejectedCandidateKeys.value.includes(candidateKey(tile.index, index)));
}

function suggestTitle(): string {
  const heading = blocks.value.find((block) => block.kind === "heading" && block.text.trim());
  return heading?.text.trim().split("\n")[0].slice(0, 180) || sourceInfo.value?.titleCandidate?.slice(0, 180) || "截图笔记";
}

function confirmLeave(): boolean {
  if (!edited.value) return true;
  return window.confirm("校对结果还没有保存或下载，确定丢弃吗？");
}

function hasUnsavedChanges(): boolean {
  return props.modelValue && (edited.value || uploadingImage.value ||
    (step.value === "review" && Boolean(markdown.value.trim())) ||
    (step.value === "crop" && Boolean(currentJob.value)));
}

function confirmPageLeave(): boolean {
  if (!props.modelValue) return true;
  if (uploadingImage.value) {
    if (!window.confirm("图片仍在上传。离开将取消本次上传与读回校验，是否继续？")) return false;
    imageUploadController?.abort();
    return true;
  }
  if (edited.value) return confirmLeave();
  if (hasUnsavedChanges()) return window.confirm("截图校对结果尚未应用到笔记或博客草稿。离开后需重新识别，确定继续吗？");
  return true;
}

defineExpose({ hasUnsavedChanges, confirmPageLeave });

function handleClose(done: () => void) {
  if (uploadingImage.value) {
    if (!window.confirm("图片仍在上传。关闭将取消本次上传与读回校验，是否继续？")) return;
    imageUploadController?.abort();
    done();
    return;
  }
  if (confirmLeave()) done();
}

/* 手动区域：在预览图上拖拽框选（坐标换算到图片自然像素） */
function cropPoint(event: MouseEvent) {
  const image = cropImageRef.value;
  const state = cropState.value;
  if (!image || !state) return null;
  const bounds = image.getBoundingClientRect();
  const scaleX = state.natural.width / bounds.width;
  const scaleY = state.natural.height / bounds.height;
  return {
    x: Math.max(0, Math.min(state.natural.width, (event.clientX - bounds.left) * scaleX)),
    y: Math.max(0, Math.min(state.natural.height, (event.clientY - bounds.top) * scaleY)),
  };
}

function onCropMouseDown(event: MouseEvent) {
  const point = cropPoint(event);
  if (!point || !cropState.value) return;
  suggestedCrop.value = false;
  cropPreviewUrl.value = "";
  if (cropState.value.file === stitchedFile.value) {
    if (longCropClickStage.value === 1) {
      cropState.value.rect = { ...cropState.value.rect!, x1: point.x, y1: point.y };
      longCropClickStage.value = 2;
      nextTick(refreshCropPreview);
    } else {
      cropState.value.rect = { x0: point.x, y0: point.y, x1: point.x, y1: point.y };
      longCropClickStage.value = 1;
    }
    return;
  }
  cropState.value.dragging = true;
  cropState.value.rect = { x0: point.x, y0: point.y, x1: point.x, y1: point.y };
}

function onCropMouseMove(event: MouseEvent) {
  const state = cropState.value;
  if (!state || (!state.dragging && !(state.file === stitchedFile.value && longCropClickStage.value === 1))) return;
  const point = cropPoint(event);
  if (!point) return;
  state.rect = { ...state.rect!, x1: point.x, y1: point.y };
}

function onCropMouseUp() {
  if (cropState.value) cropState.value.dragging = false;
  refreshCropPreview();
  // 框选完成后按插图实际纵向位置预填插入位置；重新框选也会跟随新位置
  applyAutoInsertIndex();
}

const cropRectStyle = computed(() => {
  const state = cropState.value;
  const rect = state?.rect;
  if (!state || !rect || !state.natural.width) return {};
  const left = Math.min(rect.x0, rect.x1);
  const top = Math.min(rect.y0, rect.y1);
  return {
    left: `${(left / state.natural.width) * 100}%`,
    top: `${(top / state.natural.height) * 100}%`,
    width: `${(Math.abs(rect.x1 - rect.x0) / state.natural.width) * 100}%`,
    height: `${(Math.abs(rect.y1 - rect.y0) / state.natural.height) * 100}%`,
  };
});

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      // initialJob 与 modelValue 同一批更新时，initialJob 的 watcher 可能先
      // 开始识别；此时不要二次重置来源/覆盖信息或释放它正在用的图片。
      if (busy.value && currentJob.value === props.initialJob) return;
      step.value = "select";
      resetResult();
      currentJob.value = null;
      sourceInfo.value = null;
      coverage.value = null;
      const warmingClient = ensureClient();
      // Load/cache and prime a local GPU session while the user is choosing a
      // screenshot. This keeps the first visible OCR band out of WebGPU's shader
      // compilation path; failures remain retryable when recognition starts.
      void warmingClient.init().catch((cause) => {
        if (client === warmingClient && props.modelValue) {
          error.value = cause instanceof Error ? cause.message : "本地 OCR 初始化失败，请重试";
        }
      });
      const job = props.initialJob;
      if (job?.tiles.length) {
        if (job.cropRequired && job.tiles.length === 1) {
          startCrop(job);
        } else {
          void runJob(job);
        }
      }
    } else {
      client?.dispose();
      client = null;
      resetResult();
      currentJob.value = null;
    }
  },
);

watch(
  () => props.initialJob,
  (job) => {
    if (job && props.modelValue) {
      if (job.cropRequired && job.tiles.length === 1) startCrop(job);
      else void runJob(job);
    }
  },
);

onBeforeUnmount(() => {
  client?.dispose();
  client = null;
  revokeUrls();
});
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :before-close="handleClose"
    :close-on-click-modal="false"
    append-to-body
    width="min(1180px, 96vw)"
    top="2vh"
    class="screenshot-ocr-dialog"
    title="截图识别为 Markdown（本地 OCR）"
  >
    <div v-if="step === 'select'" class="ocr-select" @dragover.prevent @drop="onDrop">
      <el-alert v-if="error" type="error" :title="error" :closable="false" show-icon />
      <p class="ocr-hint">
        只处理你已能正常看到且有权保存的内容；不要用它绕过登录、付费墙或复制限制。
        截图仅在本浏览器内识别；只有主动选择“保留插图”时，所裁剪的插图才会上传。
      </p>
      <div v-if="busy" class="ocr-progress">
        <el-progress :percentage="50" :indeterminate="true" :show-text="false" />
        <p>{{ progressNote || progress?.detail || "正在处理…" }}</p>
      </div>
      <div v-if="error && currentJob?.tiles.length" class="ocr-recovery">
        <el-button type="primary" :disabled="busy" @click="runJob(currentJob!)">重新识别刚才的截图</el-button>
        <el-button v-for="(_, index) in currentJob.tiles" :key="index" :disabled="busy" @click="downloadSourceTile(index)">
          下载源图 {{ index + 1 }}
        </el-button>
      </div>
      <div class="ocr-dropzone">
        <input ref="fileInput" type="file" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" @change="pickFile" />
        <p>选择 PNG / JPEG / WebP 截图（≤20 MiB），或拖到此处。其他截图扩展导出的图片也可以直接上传。</p>
        <el-button type="primary" :disabled="busy" @click="fileInput?.click()">选择截图</el-button>
      </div>
      <p class="ocr-hint">首次使用会从本站下载约 21 MiB 中文识别模型并校验哈希；之后浏览器会缓存。</p>
    </div>

    <div v-else-if="step === 'crop' && cropState" class="ocr-crop">
      <el-alert type="info" :closable="false" show-icon :title="cropPurpose === 'image' && suggestedCrop ? '系统已经框好推荐区域。请检查下方裁剪预览：正确就直接上传；不正确点“重新框选覆盖推荐范围”，再自己选。' : cropState.file === stitchedFile ? '整张长图可滚动：先点插图左上角，再滚动图片并点右下角。确认后才会上传。' : cropPurpose === 'image' ? '在图上拖出要保留的配图区域，检查裁剪预览后再上传。' : '已按主内容区域自动预填选区，可直接识别或拖拽调整；也可以重新框选裁掉导航、评论或隐私内容。'">
      </el-alert>
      <p v-if="cropPrefillNote" class="ocr-hint">{{ cropPrefillNote }}</p>
      <div ref="cropPaneRef" class="ocr-crop-pane" :class="{ 'ocr-crop-long': cropState.file === stitchedFile }">
        <div class="ocr-crop-canvas">
          <img
            ref="cropImageRef"
            :src="cropState.url"
            alt="待裁剪截图"
            @load="focusAndPreviewCrop"
            @mousedown.prevent="onCropMouseDown"
            @mousemove="onCropMouseMove"
            @mouseup="onCropMouseUp"
            @mouseleave="onCropMouseUp"
          />
          <div v-if="cropState.rect" class="ocr-crop-rect" :style="cropRectStyle"></div>
        </div>
      </div>
      <div v-if="cropPurpose === 'image' && cropPreviewUrl" class="ocr-crop-preview" aria-label="当前图片裁剪预览">
        <strong>{{ suggestedCrop ? "系统推荐区域的实际裁剪预览" : "你重新框选的实际裁剪预览" }}</strong>
        <img :src="cropPreviewUrl" alt="当前选定的插图区域预览" />
      </div>
      <div class="ocr-crop-actions">
        <el-button v-if="cropPurpose === 'image' && cropState.rect" @click="replaceSuggestedCrop">
          {{ suggestedCrop ? "重新框选覆盖推荐范围" : "重新框选" }}
        </el-button>
        <span v-if="cropPurpose === 'image'" class="ocr-hint">插图用途：</span>
        <el-select v-if="cropPurpose === 'image'" v-model="imageTextPolicy" size="small" aria-label="OCR 文字保留方式" style="width: 190px">
          <el-option label="图片与 OCR 文字都保留" value="both" />
          <el-option label="只保留图片" value="image_only" />
        </el-select>
        <el-select v-if="cropPurpose === 'image'" v-model="figureInsertIndex" size="small" aria-label="图片插入位置" placeholder="选择插入位置" style="width: 220px" @change="onFigureInsertSelect">
          <el-option label="插入到正文末尾" :value="blocks.length" />
          <el-option v-for="(block, index) in blocks" :key="block.id" :label="`插入到：${block.text.slice(0, 28) || '文字块'}`" :value="index" />
        </el-select>
        <span v-if="cropPurpose === 'image'" class="ocr-target-switch" role="radiogroup" aria-label="插图保存目标">
          <button type="button" :aria-pressed="saveTarget === 'private_note'" :class="['ocr-target-btn', { active: saveTarget === 'private_note' }]" :disabled="uploadingImage" @click="saveTarget = 'private_note'">私有笔记</button>
          <button type="button" :aria-pressed="saveTarget === 'article_draft'" :class="['ocr-target-btn', { active: saveTarget === 'article_draft' }]" :disabled="uploadingImage" @click="saveTarget = 'article_draft'">博客草稿</button>
        </span>
        <el-button v-if="cropPurpose === 'image'" @click="returnToReview">返回校对</el-button>
        <el-button v-else @click="step = 'select'; resetResult()">返回</el-button>
        <el-button v-if="cropPurpose === 'image'" type="primary" :loading="uploadingImage" @click="uploadCropAsImage">
          {{ saveTarget === 'private_note' ? '上传为私有图片' : '上传为博客图片' }}
        </el-button>
        <el-button v-else type="primary" @click="applyCropAndRecognize">识别所选区域</el-button>
      </div>
    </div>

    <div v-else class="ocr-review" :data-pixel-raw-candidates="pixelRawCandidateCount" :data-pixel-deduped-candidates="pixelDedupedCandidateCount">
      <div class="ocr-toolbar">
        <el-button size="small" :disabled="busy" @click="confirmLeave() ? (step = 'select', resetResult()) : undefined">
          换一张截图
        </el-button>
        <el-button size="small" type="primary" plain :loading="smartConfirming" :disabled="busy" @click="smartConfirmCandidates">
          智能确认
        </el-button>
        <el-button size="small" :disabled="!tiles.length" @click="cropFigureFromSource">手动框选页面配图</el-button>
        <span v-if="smartConfirming" class="ocr-engine">{{ progressNote }}</span>
        <el-button v-if="stitchedFile" size="small" @click="downloadStitched">下载拼接长图</el-button>
        <el-button v-if="stitchedFile" size="small" @click="toggleTileView">{{ showTiles ? "收起逐屏定位" : "查看逐屏定位" }}</el-button>
        <span class="ocr-source" v-if="imageLabel">{{ imageLabel }}</span>
        <span v-if="lastRunMs" class="ocr-engine">本地识别 {{ (lastRunMs / 1000).toFixed(1) }} s</span>
      </div>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        :title="candidateCount ? `发现 ${candidateCount} 处可见网页图片候选或像素建议区域。点击虚线框检查最终裁剪预览；黄色为网页图片，蓝色为本地像素建议，部分捕获会明确标记。图片只在你确认后上传。漏选的图片可直接在源图上按住拖拽框选。` : '没有自动候选。OCR 只识别文字；可直接在源图上按住拖拽框选配图，或点“手动框选页面配图”选取。'"
      />
      <el-alert v-if="pixelScanning" type="info" :closable="false" title="正在按原始分辨率分段检查图片区域；截图已可查看，候选会逐步出现。" />
      <el-alert v-if="pixelScanError" type="warning" :closable="false" :title="`本地图片候选检测未完成：${pixelScanError}。仍可查看截图并手动框选。`" />

      <el-alert v-if="error" type="error" :title="error" :closable="false" show-icon />
      <el-alert v-if="stitchError" type="warning" :title="stitchError" :closable="false" show-icon />
      <el-alert
        v-if="coverage?.truncated"
        type="warning"
        :closable="false"
        show-icon
        title="截图未覆盖完整选择范围（超限或中途停止）。以下内容只是已截到的部分，不是全文。"
      />
      <el-alert
        v-for="warning in currentJob?.warnings ?? []"
        :key="warning"
        type="warning"
        :title="warning"
        :closable="false"
        show-icon
      />
      <el-alert
        v-for="warning in stitchedFile ? ['已先拼成最终长图，再对长图进行一次本地 OCR；请对照长图校对文字与插图。'] : []"
        :key="warning"
        type="info"
        :title="warning"
        :closable="false"
        show-icon
      />
      <el-alert
        v-for="warning in warnings"
        :key="warning"
        type="warning"
        :title="warning"
        :closable="false"
        show-icon
      />
      <p v-if="coveredText" class="ocr-hint">{{ coveredText }}<template v-if="droppedDuplicates"> · 已去掉 {{ droppedDuplicates }} 个重复块</template></p>

      <div class="ocr-columns">
        <div ref="imagePane" class="ocr-image-pane" aria-label="源图对照区">
          <figure v-if="stitchedUrl" class="ocr-tile ocr-stitched" data-tile-index="-1">
            <figcaption class="ocr-tile-label">已按所选宽度拼接的长图（可下载或框选跨屏配图）</figcaption>
            <div
              class="ocr-image-wrap"
              @mousedown="onReviewImageMouseDown($event, stitchedDragSource())"
              @mousemove="onReviewImageMouseMove($event, stitchedDragSource())"
              @mouseup="onReviewImageMouseUp($event, stitchedDragSource())"
            >
              <img :src="stitchedUrl" alt="按页面位置拼接的完整长截图" draggable="false" />
              <div
                v-if="reviewDrag && reviewDrag.source.key === 'stitched'"
                class="ocr-crop-rect"
                :style="reviewDragStyle"
              ></div>
              <div
                v-for="block in blocksForTile(-1)"
                :key="block.id"
                class="ocr-block-overlay"
                :class="{ selected: block.id === selectedBlockId, low: block.lowConfidence }"
                :style="overlayStyle(block, stitchedSize)"
                :data-block-id="block.id"
                :title="block.kind === 'code' ? '代码块候选' : KIND_LABELS[block.kind]"
                @click="selectBlock(block.id)"
              ></div>
              <button
                v-for="candidate in stitchedCandidates"
                :key="candidate.key"
                type="button"
                class="ocr-image-candidate"
                :class="[{ inserted: insertedCandidateKeys.includes(`whole:${candidate.key}`) }, { pixels: candidate.origin === 'pixels' }, { partial: candidate.coverage !== 'complete' }, { code: candidate.kind === 'code' }]"
                :style="candidateStyle(candidate)"
                :aria-label="`保留长图配图候选 ${candidate.key}`"
                :title="`${candidate.kind === 'code' ? '代码块' : candidate.origin === 'pixels' ? '建议区域（像素）' : '网页图片'} · ${candidate.coverage === 'complete' ? '覆盖完整' : '部分图片/可能有缺口'} · 置信度 ${Math.round((candidate.confidence ?? 0.5) * 100)}%`"
                @click.stop="cropStitchedCandidate(candidate)"
              ></button>
              <button v-for="candidate in stitchedCandidates" :key="`reject-${candidate.key}`" type="button"
                class="ocr-candidate-reject" :style="candidateRejectStyle(candidate)" aria-label="拒绝此图片候选"
                title="拒绝此候选" @click.stop="rejectFigureCandidate(`whole:${candidate.key}`)">×</button>
            </div>
          </figure>
          <template v-if="!stitchedUrl || showTiles">
          <figure v-for="tile in tiles" :key="tile.index" class="ocr-tile" :data-tile-index="tile.index">
            <figcaption class="ocr-tile-label">{{ tileMetaLabel(tile) }}</figcaption>
            <div
              class="ocr-image-wrap"
              @mousedown="onReviewImageMouseDown($event, tileDragSource(tile))"
              @mousemove="onReviewImageMouseMove($event, tileDragSource(tile))"
              @mouseup="onReviewImageMouseUp($event, tileDragSource(tile))"
            >
              <img :src="tile.url" alt="待校对截图" draggable="false" />
              <div
                v-if="reviewDrag && reviewDrag.source.key === `tile:${tile.index}`"
                class="ocr-crop-rect"
                :style="reviewDragStyle"
              ></div>
              <div
                v-for="block in blocksForTile(tile.index)"
                :key="block.id"
                class="ocr-block-overlay"
                :class="{ selected: block.id === selectedBlockId, low: block.lowConfidence }"
                :style="overlayStyle(block, tile)"
                :data-block-id="block.id"
                :title="block.kind === 'code' ? '代码块候选' : KIND_LABELS[block.kind]"
                @click="selectBlock(block.id)"
              ></div>
              <button
                v-for="item in visibleTileCandidates(tile)"
                :key="`image-${tile.index}-${item.index}`"
                type="button"
                class="ocr-image-candidate"
                :class="[{ inserted: insertedCandidateKeys.includes(candidateKey(tile.index, item.index)) }, { code: item.candidate.kind === 'code' }]"
                :style="candidateStyle(item.candidate)"
                :aria-label="`保留视口 ${tile.index + 1} 的配图候选 ${item.index + 1}`"
                :title="insertedCandidateKeys.includes(candidateKey(tile.index, item.index)) ? '已插入，可再次调整裁剪' : item.candidate.kind === 'code' ? '代码块（点击检查并插入）' : '点击检查并插入此配图'"
                @click.stop="cropSuggestedFigure(tile, item.index)"
              ></button>
              <button v-for="item in visibleTileCandidates(tile)" :key="`reject-${tile.index}-${item.index}`" type="button" class="ocr-candidate-reject"
                :style="candidateRejectStyle(item.candidate)" aria-label="拒绝此图片候选" title="拒绝此候选"
                @click.stop="rejectFigureCandidate(candidateKey(tile.index, item.index))">×</button>
              <button
                v-for="candidate in (!stitchedFile && tile.index === 0 ? pixelCandidates : [])"
                :key="candidate.key"
                type="button"
                class="ocr-image-candidate pixels"
                :style="candidateStyle(candidate)"
                :aria-label="`建议区域 ${candidate.key}`"
                title="建议区域（本地像素规则，低置信度）；请检查并调整裁剪框"
                @click.stop="cropPixelTileCandidate(candidate)"
              ></button>
            </div>
          </figure>
          </template>
        </div>

        <div ref="blocksPane" class="ocr-blocks-pane" aria-label="识别结果校对区">
          <div v-if="busy && !blocks.length" class="ocr-progress">
            <el-progress :percentage="60" :indeterminate="true" :show-text="false" />
            <p>{{ progressNote || progress?.detail || "正在处理…" }}</p>
          </div>
          <div v-if="busy && blocks.length" class="ocr-progress ocr-progress-inline">
            <el-progress :percentage="60" :indeterminate="true" :show-text="false" />
            <p>{{ progressNote || progress?.detail || "正在继续识别；已显示部分结果" }}</p>
          </div>
          <template v-if="blocks.length || !busy">
            <p v-if="!blocks.length" class="ocr-hint">没有识别到内容。</p>
            <div
              v-for="(block, index) in blocks"
              :key="block.id"
              class="ocr-block-card"
              :class="{ selected: block.id === selectedBlockId, low: block.lowConfidence }"
              :data-block-id="block.id"
              @click="selectBlock(block.id)"
            >
              <div class="ocr-block-head">
                <el-select
                  :model-value="block.kind"
                  size="small"
                  style="width: 130px"
                  :aria-label="`第 ${index + 1} 块类型`"
                  @update:model-value="(kind: OcrBlockKind) => { block.kind = kind; markEdited(block.id); }"
                  @click.stop
                >
                  <el-option v-for="(label, kind) in KIND_LABELS" :key="kind" :label="label" :value="kind" />
                </el-select>
                <el-select
                  v-if="block.kind === 'heading'"
                  :model-value="block.level"
                  size="small"
                  style="width: 80px"
                  aria-label="标题级别"
                  @update:model-value="(level: 2 | 3) => { block.level = level; markEdited(block.id); }"
                  @click.stop
                >
                  <el-option :value="2" label="## 大" />
                  <el-option :value="3" label="### 小" />
                </el-select>
                <span class="ocr-block-order">{{ index + 1 }}</span>
                <span class="ocr-spacer"></span>
                <el-button size="small" text :aria-label="`上移第 ${index + 1} 块`" @click.stop="moveBlock(block.id, -1)">↑</el-button>
                <el-button size="small" text :aria-label="`下移第 ${index + 1} 块`" @click.stop="moveBlock(block.id, 1)">↓</el-button>
                <el-button size="small" text type="danger" :aria-label="`删除第 ${index + 1} 块`" @click.stop="deleteBlock(block.id)">删除</el-button>
              </div>
              <el-input
                v-model="block.text"
                :rows="block.kind === 'code' ? Math.min(10, Math.max(3, block.text.split('\n').length)) : 2"
                type="textarea"
                :autosize="block.kind === 'code' ? false : { minRows: 2, maxRows: 8 }"
                :aria-label="`第 ${index + 1} 块文字`"
                @input="markEdited(block.id)"
                @focus="selectBlock(block.id)"
                @click.stop
              />
              <div class="ocr-block-warnings">
                <el-tag v-if="block.lowConfidence" type="warning" size="small">含低置信度文字，需校对</el-tag>
                <el-tag v-for="warning in block.warnings" :key="warning" type="warning" size="small">{{ warning }}</el-tag>
              </div>
              <div class="ocr-add-row">
                <el-button size="small" text @click.stop="addBlockAfter(block.id, 'paragraph')">+段落</el-button>
                <el-button size="small" text @click.stop="addBlockAfter(block.id, 'code')">+代码</el-button>
              </div>
            </div>
          </template>
        </div>
      </div>

      <div v-if="sourceInfo" class="ocr-source-card">
        <strong>来源</strong>
        <span>{{ sourceInfo.titleCandidate || "（无标题）" }}</span>
        <a v-if="sourceInfo.sourceUrl" :href="sourceInfo.sourceUrl" target="_blank" rel="noopener noreferrer nofollow">{{ sourceInfo.sourceUrl }}</a>
        <span v-if="sourceInfo.capturedAt">{{ new Date(sourceInfo.capturedAt).toLocaleString("zh-CN") }} 截取</span>
      </div>

      <div class="ocr-preview">
        <div class="ocr-preview-head">
          <strong>Markdown 预览</strong>
          <span class="ocr-hint">与文章页一致的 XSS 清洗；保存前请逐块核对。</span>
          <span class="ocr-spacer"></span>
          <span class="ocr-target-switch" role="radiogroup" aria-label="保存目标">
            <button type="button" :aria-pressed="saveTarget === 'private_note'" :class="['ocr-target-btn', { active: saveTarget === 'private_note' }]" :disabled="applying" @click="saveTarget = 'private_note'">私有笔记（默认）</button>
            <button type="button" :aria-pressed="saveTarget === 'article_draft'" :class="['ocr-target-btn', { active: saveTarget === 'article_draft' }]" :disabled="applying" @click="saveTarget = 'article_draft'">博客草稿</button>
          </span>
          <el-button size="small" @click="downloadMarkdown" :disabled="!markdown.trim()">下载 .md</el-button>
          <el-button size="small" type="primary" :loading="applying" @click="requestApply" :disabled="!markdown.trim()">
            {{ saveTarget === "article_draft" ? "应用到博客草稿" : "放入私有笔记" }}
          </el-button>
        </div>
        <div ref="previewPane" class="ocr-preview-body">
          <pre v-if="busy" class="ocr-markdown-progress">{{ previewMarkdown || markdown }}</pre>
          <MdPreview v-else :model-value="previewMarkdown || markdown" :sanitize="(html: string) => xss(html)" preview-theme="github" />
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<style scoped>
.ocr-hint { color: var(--el-text-color-secondary); font-size: 13px; margin: 4px 0; }
.ocr-select { display: grid; gap: 12px; }
.ocr-dropzone {
  display: grid; gap: 10px; justify-items: center; padding: 28px 16px;
  border: 1px dashed var(--el-border-color); border-radius: 8px; background: var(--el-fill-color-lighter);
}
.ocr-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
.ocr-engine { color: var(--el-text-color-secondary); font-size: 12px; }
.ocr-source { color: var(--el-text-color-secondary); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 320px; }
.ocr-columns { display: flex; gap: 12px; min-height: 340px; }
.ocr-image-pane { flex: 0 0 44%; max-height: 52vh; overflow: auto; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; background: var(--el-fill-color-light); padding: 8px; display: grid; gap: 10px; align-content: start; }
.ocr-image-pane::before { content: ""; display: block; width: 100%; height: 25vh; min-height: 80px; }
.ocr-image-pane::after { content: ""; display: block; width: 100%; height: 38vh; min-height: 120px; }
.ocr-tile { margin: 0; display: grid; gap: 4px; }
.ocr-stitched img { display: block; width: 100%; height: auto; }
.ocr-tile-label { font-size: 12px; color: var(--el-text-color-secondary); }
.ocr-image-wrap { position: relative; font-size: 0; }
.ocr-image-wrap img { display: block; width: 100%; height: auto; }
.ocr-block-overlay { position: absolute; border: 1.5px solid rgba(64, 158, 255, 0.75); background: rgba(64, 158, 255, 0.08); cursor: pointer; border-radius: 2px; }
.ocr-block-overlay:hover { background: rgba(64, 158, 255, 0.2); }
.ocr-block-overlay.selected { border-color: var(--el-color-success); background: rgba(103, 194, 58, 0.18); }
.ocr-block-overlay.low { border-color: var(--el-color-warning); }
.ocr-image-candidate { position: absolute; z-index: 2; border: 3px dashed #e6a23c; background: rgba(230, 162, 60, .16); cursor: pointer; border-radius: 3px; }
.ocr-image-candidate:hover, .ocr-image-candidate:focus-visible { background: rgba(230, 162, 60, .32); outline: 2px solid #b77513; }
.ocr-image-candidate.inserted { border-color: #67c23a; background: rgba(103, 194, 58, .12); }
.ocr-image-candidate.pixels { border-color: #409eff; background: rgba(64, 158, 255, .12); }
/* 代码块候选：深松绿实线边框，与图片（黄虚线）/像素建议（蓝）区分。 */
.ocr-image-candidate.code { border: 3px solid #174b46; background: rgba(23, 75, 70, .14); }
.ocr-image-candidate.code:hover, .ocr-image-candidate.code:focus-visible { background: rgba(23, 75, 70, .28); outline: 2px solid #0e332f; }
.ocr-image-candidate.partial { border-style: dotted; border-color: #e6a23c; background: rgba(230, 162, 60, .10); }
.ocr-candidate-reject { position: absolute; z-index: 4; width: 22px; height: 22px; padding: 0; transform: translate(-50%, -50%); border: 1px solid #b42318; border-radius: 50%; color: #fff; background: #c0392b; font: 700 17px/18px system-ui, sans-serif; cursor: pointer; }
.ocr-blocks-pane { flex: 1; max-height: 52vh; overflow: auto; display: grid; gap: 8px; align-content: start; padding-right: 4px; }
.ocr-blocks-pane::before { content: ""; display: block; width: 100%; height: 25vh; min-height: 80px; }
.ocr-blocks-pane::after { content: ""; display: block; width: 100%; height: 38vh; min-height: 120px; }
.ocr-progress { padding: 32px 8px; text-align: center; color: var(--el-text-color-secondary); }
.ocr-block-card { border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 8px; display: grid; gap: 6px; cursor: default; }
.ocr-block-card.selected { border-color: var(--el-color-success); }
.ocr-block-card.low { border-left: 3px solid var(--el-color-warning); }
.ocr-block-head { display: flex; align-items: center; gap: 6px; }
.ocr-block-order { color: var(--el-text-color-secondary); font-size: 12px; min-width: 20px; }
.ocr-spacer { flex: 1; }
.ocr-block-warnings { display: flex; gap: 6px; flex-wrap: wrap; }
.ocr-add-row { display: flex; gap: 4px; }
.ocr-source-card { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 10px; padding: 8px 10px; background: var(--el-fill-color-light); border-radius: 6px; font-size: 12px; color: var(--el-text-color-regular); }
.ocr-source-card strong { font-size: 12px; }
.ocr-source-card a { color: var(--el-color-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 340px; }
.ocr-preview { margin-top: 10px; border-top: 1px solid var(--el-border-color); padding-top: 8px; }
.ocr-preview-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }
.ocr-target-switch { display: inline-flex; border: 1px solid var(--el-border-color); border-radius: 4px; overflow: hidden; }
.ocr-target-btn { border: 0; background: var(--el-fill-color-light); padding: 5px 10px; font-size: 12px; cursor: pointer; color: var(--el-text-color-regular); }
.ocr-target-btn.active { background: var(--el-color-primary); color: #fff; }
.ocr-preview-body { max-height: 30vh; overflow: auto; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 0 12px; }
.ocr-markdown-progress { margin: 12px 0; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
.ocr-crop { display: grid; gap: 10px; }
.ocr-crop-pane { position: relative; max-height: 58vh; overflow: auto; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 8px; background: var(--el-fill-color-light); }
.ocr-crop-canvas { position: relative; display: inline-block; max-width: 100%; font-size: 0; }
.ocr-crop-pane img { display: block; max-width: 100%; max-height: 46vh; width: auto; height: auto; cursor: crosshair; user-select: none; }
.ocr-crop-long .ocr-crop-canvas { width: 100%; }
.ocr-crop-long img { width: 100%; max-height: none; }
.ocr-crop-rect { position: absolute; border: 2px dashed var(--el-color-primary); background: rgba(64, 158, 255, 0.12); pointer-events: none; }
.ocr-crop-preview { display: grid; gap: 6px; justify-items: start; padding: 8px 10px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; background: var(--el-fill-color-lighter); }
.ocr-crop-preview strong { font-size: 12px; color: var(--el-text-color-regular); }
.ocr-crop-preview img { display: block; max-width: min(100%, 480px); max-height: 300px; object-fit: contain; border: 1px solid var(--el-border-color); background: #fff; }
.ocr-crop-actions { display: flex; gap: 8px; justify-content: flex-end; align-items: center; flex-wrap: wrap; }
</style>
