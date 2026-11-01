/**
 * B-045 阶段A：OCR worker。识别只在浏览器本地进行：
 * 模型从本站同源 /models/ocr/ 加载并校验 SHA-256，图片字节经消息传入，
 * 未确认前不上传、不落库、不调用任何写作模型或第三方 OCR API。
 */
import "./ocrOrtEnv";
import { getDefaultWebExecutionProviders, PaddleOcrService } from "ppu-paddle-ocr/web";
import type { PaddleOptions } from "ppu-paddle-ocr";
import { dedupeOverlappingBandLines, mapBandLines, planOcrBands } from "../utils/ocrBands";
import { removeDuplicateDetectionBoxes } from "../utils/ocrDetection";
import {
  applyRowEnhancementToPixels,
  computeRowCondition,
  isStrongerHypothesis,
  paddedRectForRow,
  pickRowEnhancement,
  selectUncertainRows,
  type Rect,
  type RowEnhancement,
} from "../utils/ocrRecEnhance";
import type { OcrLine } from "../utils/screenshotOcr";

type DiagnosticRecognitionOptions = {
  strategy?: "per-line" | "per-box";
  recBatchSize?: 1 | 4;
  skipRetry?: boolean;
  paddingVertical?: number;
};

interface InitMessage {
  type: "init";
  /** Local benchmark override; normal product startup always uses the default provider list. */
  providerOverride?: "wasm";
  /** In-memory model override used only by the opt-in local model A/B E2E. */
  diagnosticModelAssets?: {
    name: "PP-OCRv6 tiny";
    detection: ArrayBuffer;
    recognition: ArrayBuffer;
    charactersDictionary: ArrayBuffer;
    sha256: { detection: string; recognition: string; charactersDictionary: string };
  };
}
interface RecognizeMessage {
  type: "recognize";
  id: number;
  buffer: ArrayBuffer;
  /** Opt-in local-only diagnostics used by the RPC.png acceptance test. */
  diagnostics?: boolean;
  /** Controlled local A/B only; ignored unless diagnostics are explicitly enabled. */
  diagnosticRecognition?: DiagnosticRecognitionOptions;
}
type WorkerMessage = InitMessage | RecognizeMessage;

const MODEL_FILES = {
  detection: "/models/ocr/PP-OCRv5_mobile_det_infer.ort",
  recognition: "/models/ocr/PP-OCRv5_mobile_rec_infer.onnx",
  charactersDictionary: "/models/ocr/ppocrv5_dict.txt",
} as const;
const OCR_VERTICAL_PADDING = 0.6;
const OCR_REC_BATCH_SIZE = 4;
/** ppu 默认从最长边 2000px 的缩小副本上裁识别输入；DPR≥1.25 的屏幕截图宽
 * 2500–3840px，等于每行都先被缩小再识别，直接拉低置信度。8192 覆盖所有现实
 * 截图宽度（始终用原生像素识别），同时仍对极端上传保留上限。 */
const OCR_REC_MAX_CROP_SOURCE_SIDE = 8192;

let service: PaddleOcrService | null = null;
let initPromise: Promise<void> | null = null;
let selectedExecutionProviders: string[] = ["wasm"];

interface BandTiming {
  index: number;
  top: number;
  bottom: number;
  prepareMs: number;
  detectionMs: number;
  recognitionMs: number;
  detectionBoxes: number;
  recognitionBoxes: number;
  duplicateDetectionBoxesRemoved: number;
  recognizedRows: number;
  retainedRows: number;
  dedupeMs: number;
  retryMs: number;
  retryRows: number;
  retryAccepted: number;
  retryBatchSize: number;
  enhanceRows: number;
  enhanceAccepted: number;
}

const RETRY_ROW_LIMIT = 10;
const ENHANCE_ROW_LIMIT = 12;
const UNCERTAIN_CONFIDENCE = 0.9;

/** A small second pass for readable, uncertain rows. Keep it bounded so a long
 * screenshot still produces its first draft promptly. Scores remain the model's
 * real scores; an alternative is kept whenever the passes disagree.
 *
 * Pass 1 re-recognizes the same band crops one box at a time (per-line batching
 * can truncate valid suffixes). Pass 2 conditions the crop the way the PaddleOCR
 * guides recommend for hard rows — invert dark-background rows, stretch low
 * contrast, upscale small text — and is only trusted when it clearly beats the
 * incumbent hypothesis. Conditioning only changes the input quality; it never
 * invents text, and everything weaker stays a visible review alternative. */
async function retryUncertainRows(
  canvas: OffscreenCanvas,
  rows: OcrLine[],
  recognitor: { run: (...args: any[]) => Promise<any[]> },
  dictionary: string[],
  recBatchSize: 1 | 4,
): Promise<{ rows: OcrLine[]; attempted: number; accepted: number; enhancedRows: number; enhancedAccepted: number }> {
  const targets = selectUncertainRows(rows, RETRY_ROW_LIMIT);
  if (!targets.length) return { rows, attempted: 0, accepted: 0, enhancedRows: 0, enhancedAccepted: 0 };
  const boxes = targets.map(({ row }) => paddedRectForRow(row.bbox, canvas.width, canvas.height));
  const updated = [...rows];
  let accepted = 0;

  const secondPass = await recognitor.run(canvas, boxes, dictionary, "per-box", { minimumConfidence: 0, recBatchSize });
  for (const candidate of secondPass) {
    const targetIndex = boxes.findIndex((box) => box.x === candidate.box?.x && box.y === candidate.box?.y &&
      box.width === candidate.box?.width && box.height === candidate.box?.height);
    const target = targets[targetIndex];
    if (!target) continue;
    const text = String(candidate.text ?? "").trim();
    const confidence = Number(candidate.confidence);
    if (!text || !Number.isFinite(confidence) || text === target.row.text.trim()) continue;
    const alternatives = [...(target.row.alternatives ?? [])];
    // A high score on a tiny fragment is not evidence that a whole sentence
    // was recovered. Do not replace a row with an implausibly short proposal.
    if (isStrongerHypothesis({ text, confidence }, target.row)) {
      alternatives.unshift({ text: target.row.text, confidence: target.row.confidence });
      updated[target.index] = { ...target.row, text, confidence, alternatives: alternatives.slice(0, 3) };
      accepted += 1;
    } else {
      alternatives.push({ text, confidence });
      updated[target.index] = { ...target.row, alternatives: alternatives.slice(0, 3) };
    }
  }

  const enhanced = await enhanceUncertainRows(canvas, targets, boxes, updated, recognitor, dictionary);
  return { rows: updated, attempted: targets.length, accepted, enhancedRows: enhanced.attempted, enhancedAccepted: enhanced.accepted };
}

/** Pass 2: one conditioned crop per row that pass 1 left below the confidence
 * bar. Bounded to ENHANCE_ROW_LIMIT rows and one inference each; rows with no
 * applicable conditioning (normal-contrast dark text at a readable size) are
 * skipped without spending an inference. */
async function enhanceUncertainRows(
  canvas: OffscreenCanvas,
  targets: Array<{ row: OcrLine; index: number }>,
  boxes: Rect[],
  rows: OcrLine[],
  recognitor: { run: (...args: any[]) => Promise<any[]> },
  dictionary: string[],
): Promise<{ attempted: number; accepted: number }> {
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return { attempted: 0, accepted: 0 };
  const pending = targets
    .map((target, position) => ({ target, position, incumbent: rows[target.index]! }))
    .filter(({ incumbent }) => incumbent.confidence < UNCERTAIN_CONFIDENCE)
    .sort((a, b) => a.incumbent.confidence - b.incumbent.confidence)
    .slice(0, ENHANCE_ROW_LIMIT);
  let attempted = 0;
  let accepted = 0;
  for (const { target, position, incumbent } of pending) {
    const rect = boxes[position]!;
    if (rect.width < 4 || rect.height < 4) continue;
    const condition = computeRowCondition(context.getImageData(rect.x, rect.y, rect.width, rect.height).data);
    const enhancement = pickRowEnhancement({ ...condition, textHeight: target.row.bbox.height });
    if (enhancement.scale === 1 && !enhancement.invert && !enhancement.stretch) continue;
    attempted += 1;
    const cropCanvas = drawEnhancedCrop(canvas, rect, enhancement);
    const [candidate] = await recognitor.run(
      cropCanvas,
      [{ x: 0, y: 0, width: cropCanvas.width, height: cropCanvas.height }],
      dictionary, "per-box", { minimumConfidence: 0, recBatchSize: 1 },
    );
    const text = String(candidate?.text ?? "").trim();
    const confidence = Number(candidate?.confidence);
    if (!text || !Number.isFinite(confidence)) continue;
    const alternatives = [...(incumbent.alternatives ?? [])];
    if (text === incumbent.text.trim()) {
      // The conditioned input read the same text with a higher real score:
      // keep the reading, adopt the stronger measurement. This is what lowers
      // false "low confidence" flags on correctly read dark/small/low-contrast
      // rows without changing a single character.
      if (confidence > incumbent.confidence) {
        rows[target.index] = { ...incumbent, confidence };
        accepted += 1;
      }
      continue;
    }
    if (isStrongerHypothesis({ text, confidence }, incumbent)) {
      alternatives.unshift({ text: incumbent.text, confidence: incumbent.confidence });
      rows[target.index] = { ...incumbent, text, confidence, alternatives: dedupeAlternatives(alternatives).slice(0, 3) };
      accepted += 1;
    } else {
      alternatives.push({ text, confidence });
      rows[target.index] = { ...incumbent, alternatives: dedupeAlternatives(alternatives).slice(0, 3) };
    }
  }
  return { attempted, accepted };
}

function dedupeAlternatives(alternatives: Array<{ text: string; confidence: number }>): Array<{ text: string; confidence: number }> {
  return alternatives.filter((item, index) => item.text && alternatives.findIndex((other) => other.text === item.text) === index);
}

/** Crop the row rect out of the band canvas, applying the conditioning: smooth
 * upscale first, then invert/stretch on the enlarged pixels. */
function drawEnhancedCrop(source: OffscreenCanvas, rect: Rect, enhancement: RowEnhancement): OffscreenCanvas {
  const width = Math.max(1, Math.round(rect.width * enhancement.scale));
  const height = Math.max(1, Math.round(rect.height * enhancement.scale));
  const crop = new OffscreenCanvas(width, height);
  const context = crop.getContext("2d", { willReadFrequently: true });
  if (!context) return crop;
  context.imageSmoothingEnabled = enhancement.scale > 1;
  if (enhancement.scale > 1) context.imageSmoothingQuality = "high";
  context.drawImage(source, rect.x, rect.y, rect.width, rect.height, 0, 0, width, height);
  if (enhancement.invert || enhancement.stretch) {
    const imageData = context.getImageData(0, 0, width, height);
    applyRowEnhancementToPixels(imageData.data, enhancement);
    context.putImageData(imageData, 0, 0);
  }
  return crop;
}

function post(message: unknown, transfer?: Transferable[]) {
  // eslint-disable-next-line no-restricted-globals
  (self as unknown as Worker).postMessage(message, transfer ?? []);
}

async function sha256Hex(buffer: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

interface AssetManifest {
  files: Record<string, { sha256: string; bytes: number }>;
  models?: { name?: string };
  engine?: { name?: string; version?: string };
}

/** 拉取同源模型并逐一校验哈希；任何不符都视为资源被篡改/损坏，拒绝初始化。 */
async function loadVerified(path: string, manifest: AssetManifest): Promise<ArrayBuffer> {
  const expected = manifest.files[path.replace(/^\//, "")];
  if (!expected) throw new Error(`资源清单缺少 ${path}，请重新执行 sync-ocr-assets`);
  const response = await fetch(path, { referrerPolicy: "no-referrer" });
  if (!response.ok) throw new Error(`模型资源 ${path} 加载失败（HTTP ${response.status}）`);
  const buffer = await response.arrayBuffer();
  if (buffer.byteLength !== expected.bytes) {
    throw new Error(`模型资源 ${path} 字节数与清单不符（${buffer.byteLength} != ${expected.bytes}）`);
  }
  const actual = await sha256Hex(buffer);
  if (actual !== expected.sha256) {
    throw new Error(`模型资源 ${path} SHA-256 校验失败，请重新执行 sync-ocr-assets`);
  }
  return buffer;
}

async function initialize(providerOverride?: "wasm", diagnosticModelAssets?: InitMessage["diagnosticModelAssets"]): Promise<{ engine: string; model: string }> {
  const diagnosticModelName = diagnosticModelAssets?.name;
  if (diagnosticModelAssets && !import.meta.env.DEV) {
    throw new Error("备用 OCR 模型只允许在开发构建的本地 A/B 验收中使用");
  }
  if (initPromise) return initPromise.then(() => ({ engine: "ppu-paddle-ocr", model: diagnosticModelName ?? "PP-OCRv5 mobile" }));
  initPromise = (async () => {
    const manifestResponse = await fetch("/models/ocr/manifest.json", { referrerPolicy: "no-referrer" });
    if (!manifestResponse.ok) throw new Error(`资源清单加载失败（HTTP ${manifestResponse.status}）`);
    const contentType = manifestResponse.headers.get("content-type") ?? "";
    if (!contentType.toLowerCase().includes("json")) {
      throw new Error("OCR 资源清单返回了网页而不是 JSON。请重新构建前端并重启服务，确认 /models/ocr/manifest.json 可访问。");
    }
    let manifest: AssetManifest;
    try {
      manifest = (await manifestResponse.json()) as AssetManifest;
    } catch {
      throw new Error("OCR 资源清单不是有效 JSON，请重新构建前端并重启服务。");
    }
    if (!manifest || typeof manifest.files !== "object" || manifest.files === null) {
      throw new Error("OCR 资源清单缺少文件列表，请重新构建前端。");
    }

    post({ type: "progress", stage: "loading", detail: "正在加载与校验 OCR 模型…" });
    let detection: ArrayBuffer;
    let recognition: ArrayBuffer;
    let charactersDictionary: ArrayBuffer;
    if (diagnosticModelAssets) {
      const supplied = diagnosticModelAssets;
      const assets = [supplied.detection, supplied.recognition, supplied.charactersDictionary];
      const expectedHashes = [supplied.sha256.detection, supplied.sha256.recognition, supplied.sha256.charactersDictionary];
      const limits = [5_000_000, 10_000_000, 1_000_000];
      if (supplied.name !== "PP-OCRv6 tiny" || assets.some((asset, index) => !(asset instanceof ArrayBuffer) || asset.byteLength === 0 || asset.byteLength > limits[index])) {
        throw new Error("本地诊断模型资源不符合允许的大小或格式");
      }
      const hashes = await Promise.all(assets.map(sha256Hex));
      if (hashes.some((hash, index) => hash !== expectedHashes[index])) throw new Error("本地诊断模型 SHA-256 校验失败");
      [detection, recognition, charactersDictionary] = assets;
    } else {
      [detection, recognition, charactersDictionary] = await Promise.all([
        loadVerified(MODEL_FILES.detection, manifest),
        loadVerified(MODEL_FILES.recognition, manifest),
        loadVerified(MODEL_FILES.charactersDictionary, manifest),
      ]);
    }
    const executionProviders = providerOverride === "wasm"
      ? ["wasm"]
      : ((await getDefaultWebExecutionProviders()) ?? ["wasm"]);
    selectedExecutionProviders = executionProviders.map((provider) => typeof provider === "string" ? provider : provider.name ?? "unknown");
    post({ type: "progress", stage: "initializing", detail: `正在初始化本地 OCR 引擎（${executionProviders.join("+")}）…` });
    const next = new PaddleOcrService({
      model: {
        detection,
        recognition,
        charactersDictionary,
      },
      // WebGPU is used when available; the library falls back to the same local
      // WASM runtime if device session creation fails. Both sessions stay in this worker.
      session: {
        executionProviders,
        // Pre-serialized .ort test assets must not be re-optimized by ORT.
        ...(diagnosticModelAssets ? { graphOptimizationLevel: "disabled" } : {}),
      },
      processing: { engine: "canvas-native" },
      // Each long-image band is kept near native resolution; never let the
      // detector's automatic 960–1920px cap shrink the entire long page.
      detection: { maxSideLength: 1920, paddingVertical: OCR_VERTICAL_PADDING },
      // Keep every decoded row in the review UI, including weak proposals. The
      // editor marks low-confidence text instead of silently filtering it out.
      // The library type incorrectly requires charactersDictionary here; the
      // dictionary is parsed from model data and merged at initialization.
      recognition: {
        minimumConfidence: 0,
        recBatchSize: OCR_REC_BATCH_SIZE,
        maxCropSourceSideLength: OCR_REC_MAX_CROP_SOURCE_SIDE,
      } as unknown as PaddleOptions["recognition"],
    });
    await next.initialize();
    const activeProviders = ((next as unknown as { options?: { session?: { executionProviders?: Array<string | { name?: string }> } } }).options
      ?.session?.executionProviders ?? []);
    const hasWebGpu = activeProviders.some((provider) => (typeof provider === "string" ? provider : provider.name) === "webgpu");
    if (hasWebGpu) {
      // Compile the common long-page detector shape and one/two recognizer crop
      // shapes before a private screenshot is submitted. Discard every warm-up
      // result; synthetic pixels never enter the OCR editor or diagnostics.
      const warmup = new OffscreenCanvas(1149, 640);
      const context = warmup.getContext("2d", { willReadFrequently: true });
      if (context) {
        context.fillStyle = "#fff";
        context.fillRect(0, 0, warmup.width, warmup.height);
        context.fillStyle = "#111";
        context.font = "32px sans-serif";
        context.fillText("Aa 123", 24, 100);
        context.font = "24px sans-serif";
        context.fillText("Abc xyz", 24, 180);
        await next.recognize(warmup, { flatten: true, noCache: true });
      }
    }
    service = next;
  })().catch((error) => {
    service = null;
    initPromise = null;
    throw error;
  });
  await initPromise;
  return { engine: "ppu-paddle-ocr", model: diagnosticModelName ?? "PP-OCRv5 mobile" };
}

async function recognize(
  id: number,
  buffer: ArrayBuffer,
  diagnostics = false,
  diagnosticRecognition?: DiagnosticRecognitionOptions,
): Promise<void> {
  if (!service) throw new Error("OCR 引擎尚未初始化");
  const started = performance.now();
  const decodeStarted = performance.now();
  const bitmap = await createImageBitmap(new Blob([buffer]));
  const decodeMs = Math.round(performance.now() - decodeStarted);
  const bands = planOcrBands(bitmap.height);
  const lines: OcrLine[] = [];
  const bandTimings: BandTiming[] = [];
  const recognitionTensorShapes: number[][] = [];
  const requestedPadding = diagnosticRecognition?.paddingVertical;
  const recognitionOptions: DiagnosticRecognitionOptions = diagnostics ? {
    ...(diagnosticRecognition?.strategy === "per-line" || diagnosticRecognition?.strategy === "per-box"
      ? { strategy: diagnosticRecognition.strategy } : {}),
    ...(diagnosticRecognition?.recBatchSize === 1 || diagnosticRecognition?.recBatchSize === 4
      ? { recBatchSize: diagnosticRecognition.recBatchSize } : {}),
    ...(diagnosticRecognition?.skipRetry === true ? { skipRetry: true } : {}),
    ...(Number.isFinite(requestedPadding) && requestedPadding! >= 0 && requestedPadding! <= 1
      ? { paddingVertical: requestedPadding } : {}),
  } : {};
  const effectiveBatchSize = recognitionOptions.recBatchSize ?? OCR_REC_BATCH_SIZE;
  let dedupeMs = 0;
  try {
    for (let index = 0; index < bands.length; index += 1) {
      const band = bands[index];
      if (!band) continue;
      if (bands.length > 1) {
        post({ type: "progress", stage: "recognizing", detail: `正在识别长图第 ${index + 1}/${bands.length} 段…` });
      }
      const prepareStarted = performance.now();
      const canvas = new OffscreenCanvas(bitmap.width, band.bottom - band.top);
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) throw new Error("浏览器无法创建 OCR 分段画布");
      context.drawImage(bitmap, 0, band.top, bitmap.width, canvas.height, 0, 0, bitmap.width, canvas.height);
      const timing: BandTiming = {
        index, top: band.top, bottom: band.bottom,
        prepareMs: Math.round(performance.now() - prepareStarted),
        detectionMs: 0, recognitionMs: 0, detectionBoxes: 0, recognitionBoxes: 0, duplicateDetectionBoxesRemoved: 0,
        recognizedRows: 0, retainedRows: 0, dedupeMs: 0,
        retryMs: 0, retryRows: 0, retryAccepted: 0, retryBatchSize: 0,
        enhanceRows: 0, enhanceAccepted: 0,
      };
      const internal = service as unknown as {
        detector: {
          run: (...args: any[]) => Promise<any[]>;
          postprocessDetection: (...args: any[]) => any[];
          options?: { minimumAreaThreshold?: number; paddingVertical?: number };
        };
        recognitor: {
          run: (...args: any[]) => Promise<any[]>;
          runInference: (...args: any[]) => Promise<unknown>;
        };
      };
      const detector = internal.detector;
      const recognitor = internal.recognitor;
      const originalVerticalPadding = detector.options?.paddingVertical;
      if (diagnostics && recognitionOptions.paddingVertical !== undefined && detector.options) {
        detector.options.paddingVertical = recognitionOptions.paddingVertical;
      }
      let rawDetectionBoxes: Array<{ x: number; y: number; width: number; height: number }> = [];
      let paddedDetectionBoxes: Array<{ x: number; y: number; width: number; height: number }> = [];
      let recognitionBoxes: Array<{ x: number; y: number; width: number; height: number }> = [];
      const originalPostprocess = detector.postprocessDetection.bind(detector);
      if (diagnostics) {
        detector.postprocessDetection = (detection: unknown, input: unknown, ...args: unknown[]) => {
          const padded = originalPostprocess(detection, input, ...args);
          // ppu-paddle-ocr applies its default padding inside postprocess. Run
          // postprocess a second time on the already-computed map with a tiny
          // non-zero value (the library uses `value || default`) to expose the
          // pre-padding boxes for diagnosis. This is opt-in and never changes
          // the boxes used by product recognition.
          rawDetectionBoxes = originalPostprocess(detection, input, detector.options?.minimumAreaThreshold ?? 20, 0.0001, 0.0001);
          paddedDetectionBoxes = padded;
          return padded;
        };
      }
      const originalDetectionRun = detector.run.bind(detector);
      const originalRecognitionRun = recognitor.run.bind(recognitor);
      const originalInferenceRun = recognitor.runInference.bind(recognitor);
      detector.run = async (...args: any[]) => {
        const stageStarted = performance.now();
        const result = await originalDetectionRun(...args) as Array<{ x: number; y: number; width: number; height: number }>;
        timing.detectionMs += Math.round(performance.now() - stageStarted);
        timing.detectionBoxes += Array.isArray(result) ? result.length : 0;
        const unique = removeDuplicateDetectionBoxes(result);
        timing.duplicateDetectionBoxesRemoved += unique.removed;
        timing.recognitionBoxes += unique.boxes.length;
        if (diagnostics) recognitionBoxes = unique.boxes.map((box) => ({ ...box }));
        return unique.boxes;
      };
      recognitor.run = async (...args: any[]) => {
        const stageStarted = performance.now();
        const result = await originalRecognitionRun(...args);
        timing.recognitionMs += Math.round(performance.now() - stageStarted);
        timing.recognizedRows += Array.isArray(result) ? result.length : 0;
        return result;
      };
      if (diagnostics) {
        recognitor.runInference = async (tensor: { dims?: number[] }) => {
          if (Array.isArray(tensor?.dims)) recognitionTensorShapes.push([...tensor.dims]);
          return originalInferenceRun(tensor);
        };
      }
      let result: unknown;
      try {
        result = await service.recognize(canvas, {
          flatten: true,
          noCache: true,
          recBatchSize: effectiveBatchSize,
          ...(recognitionOptions.strategy ? { strategy: recognitionOptions.strategy } : {}),
        });
      } finally {
        detector.run = originalDetectionRun;
        recognitor.run = originalRecognitionRun;
        recognitor.runInference = originalInferenceRun;
        detector.postprocessDetection = originalPostprocess;
        if (detector.options) detector.options.paddingVertical = originalVerticalPadding;
      }
      const rawItems = (result as { results?: Array<Record<string, unknown>> }).results ?? [];
      timing.recognizedRows = rawItems.length;
      let localLines: OcrLine[] = rawItems.map((item) => {
        // Node 版结果字段是 bbox，web 版是 box；两者都兼容。
        const bbox = (item.bbox ?? item.box ?? {}) as { x?: number; y?: number; width?: number; height?: number };
        return {
          text: String(item.text ?? ""),
          confidence: typeof item.confidence === "number" ? item.confidence : 0,
          bbox: {
            x: Math.round(Number(bbox.x) || 0),
            y: Math.round(Number(bbox.y) || 0),
            width: Math.round(Number(bbox.width) || 0),
            height: Math.round(Number(bbox.height) || 0),
          },
        };
      });
      const retryStarted = performance.now();
      try {
        const dictionary = ((service as unknown as { options?: { recognition?: { charactersDictionary?: string[] } } })
          .options?.recognition?.charactersDictionary ?? []);
        // ppu-paddle-ocr clips batched CTC output by estimated width ratio.
        // In our same-crop A/B, per-box batch 4 truncated valid suffixes;
        // the bounded retry therefore uses batch 1 in the shipped path.
        const retryBatchSize = diagnostics && recognitionOptions.recBatchSize ? recognitionOptions.recBatchSize : 1;
        timing.retryBatchSize = retryBatchSize;
        const retry = recognitionOptions.skipRetry
          ? { rows: localLines, attempted: 0, accepted: 0, enhancedRows: 0, enhancedAccepted: 0 }
          : await retryUncertainRows(canvas, localLines, recognitor, dictionary, retryBatchSize);
        localLines = retry.rows;
        timing.retryRows = retry.attempted;
        timing.retryAccepted = retry.accepted;
        timing.enhanceRows = retry.enhancedRows;
        timing.enhanceAccepted = retry.enhancedAccepted;
      } catch {
        // The first OCR pass is still usable when a targeted retry fails.
      }
      timing.retryMs = Math.round(performance.now() - retryStarted);
      const retained = mapBandLines(band, localLines, true);
      timing.retainedRows = retained.length;
      lines.push(...retained);
      const dedupeStarted = performance.now();
      const partialLines = dedupeOverlappingBandLines(lines);
      timing.dedupeMs = Math.round(performance.now() - dedupeStarted);
      dedupeMs += timing.dedupeMs;
      bandTimings.push(timing);
      // Publish only lines owned by this band. The worker keeps the aggregate
      // privately for final ordering/deduplication; the editor can show a useful
      // first draft while subsequent bands are still being recognized.
      post({
        type: "partial",
        id,
        lines: partialLines,
        completedBands: index + 1,
        bandCount: bands.length,
        metrics: { ...timing },
        ...(diagnostics ? {
          diagnostic: {
            rawBandLines: localLines,
            rawDetectionBoxes,
            paddedDetectionBoxes,
            recognitionBoxes,
            recognitionTensorShapes,
            detectionInput: {
              width: bitmap.width,
              height: canvas.height,
              modelMaxSide: 1920,
              paddingVertical: OCR_VERTICAL_PADDING,
              paddingHorizontal: 0.6,
            },
          },
        } : {}),
      });
    }
  } finally {
    bitmap.close();
  }
  const dedupeStarted = performance.now();
  const orderedLines = dedupeOverlappingBandLines(lines);
  dedupeMs += Math.round(performance.now() - dedupeStarted);
  const ms = Math.round(performance.now() - started);
  post({ type: "result", id, lines: orderedLines, ms, metrics: {
    decodeMs, bandTimings, dedupeMs, workerMs: ms, selectedExecutionProviders,
    recognitionStrategy: recognitionOptions.strategy ?? "per-line",
    recognitionBatchSize: effectiveBatchSize,
    retriesDisabledForDiagnostic: recognitionOptions.skipRetry ?? false,
  } });
}

self.addEventListener("message", (event: MessageEvent<WorkerMessage>) => {
  const message = event.data;
  if (!message || typeof message !== "object") return;
  void (async () => {
    try {
      if (message.type === "init") {
        const info = await initialize(message.providerOverride === "wasm" ? "wasm" : undefined, message.diagnosticModelAssets);
        post({ type: "ready", ...info });
        return;
      }
      if (message.type === "recognize") {
        await recognize(message.id, message.buffer, message.diagnostics === true, message.diagnosticRecognition);
        return;
      }
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : String(cause);
      const id = message.type === "recognize" ? message.id : null;
      post({
        type: "error", id, code: "ocr_failed", detail,
        ...(message.type === "recognize" && message.diagnostics === true && cause instanceof Error ? { diagnosticStack: cause.stack } : {}),
      });
    }
  })();
});
