/**
 * B-045 阶段A：OCR worker 的主线程客户端。
 * 生命周期由调用方管理：open 时创建，关闭时 terminate，避免常驻 worker。
 */
import {
  IMAGE_MAX_BYTES,
  validateDecodedImage,
  validateImageFile,
  type OcrLine,
} from "./screenshotOcr";
import { planOcrBands } from "./ocrBands";

export interface OcrProgress {
  stage: "loading" | "initializing" | "recognizing";
  detail: string;
}

export interface RecognizeOutcome {
  lines: OcrLine[];
  ms: number;
  width: number;
  height: number;
  timings: {
    fileReadMs: number;
    validationMs: number;
    mainDecodeMs: number;
    initMs: number;
    workerMs: number;
    workerDecodeMs: number;
    dedupeMs: number;
    bands: Array<{
      index: number;
      top: number;
      bottom: number;
      prepareMs: number;
      detectionMs: number;
      recognitionMs: number;
      detectionBoxes: number;
      recognizedRows: number;
      retainedRows: number;
      dedupeMs: number;
    }>;
  };
}

export interface OcrPartialResult {
  lines: OcrLine[];
  completedBands: number;
  bandCount: number;
}

interface WorkerOcrMetrics {
  decodeMs?: number;
  workerMs?: number;
  dedupeMs?: number;
  bandTimings?: RecognizeOutcome["timings"]["bands"];
}

interface PendingRecognize {
  resolve: (outcome: { lines: OcrLine[]; ms: number; metrics?: WorkerOcrMetrics }) => void;
  reject: (error: Error) => void;
  onPartial?: (partial: OcrPartialResult) => void;
}

export class ScreenshotOcrClient {
  private worker: Worker | null = null;
  private initOnce: Promise<void> | null = null;
  private nextId = 1;
  private pending = new Map<number, PendingRecognize>();
  private initTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private handlers: { onProgress?: (progress: OcrProgress) => void; onError?: (detail: string) => void } = {}) {}

  private ensureWorker(): Worker {
    if (this.worker) return this.worker;
    const worker = new Worker(new URL("../workers/ocrWorker.ts", import.meta.url), { type: "module" });
    worker.addEventListener("message", (event: MessageEvent) => {
      const message = event.data as Record<string, unknown> | null;
      if (!message || typeof message !== "object") return;
      const type = message.type;
      if (type === "progress") {
        this.handlers.onProgress?.({
          stage: message.stage as OcrProgress["stage"],
          detail: String(message.detail ?? ""),
        });
        return;
      }
      if (type === "ready") {
        this.resolveInit();
        return;
      }
      if (type === "result") {
        const id = Number(message.id);
        const pending = this.pending.get(id);
        this.pending.delete(id);
        pending?.resolve({
          lines: (message.lines as OcrLine[]) ?? [],
          ms: Number(message.ms) || 0,
          metrics: (message.metrics as WorkerOcrMetrics | undefined) ?? undefined,
        });

        return;
      }
      if (type === "partial") {
        const pending = this.pending.get(Number(message.id));
        if (pending) {
          pending.onPartial?.({
            lines: Array.isArray(message.lines) ? message.lines as OcrLine[] : [],
            completedBands: Number(message.completedBands) || 0,
            bandCount: Number(message.bandCount) || 0,
          });
        }
        return;
      }
      if (type === "error") {
        const detail = String(message.detail ?? "本地识别失败");
        if (message.id === null || message.id === undefined) {
          this.handlers.onError?.(detail);
          this.rejectInit(new Error(detail));
          return;
        }
        const id = Number(message.id);
        const pending = this.pending.get(id);
        this.pending.delete(id);
        pending?.reject(new Error(detail));
      }
    });
    worker.addEventListener("error", (event: ErrorEvent) => {
      const detail = event.message || "OCR worker 加载失败";
      this.handlers.onError?.(detail);
      this.failWorker(new Error(detail));
    });
    this.worker = worker;
    return worker;
  }

  private initResolve: (() => void) | null = null;
  private initReject: ((error: Error) => void) | null = null;

  private resolveInit() {
    if (this.initTimer) clearTimeout(this.initTimer);
    this.initTimer = null;
    this.initResolve?.();
    this.initResolve = null;
    this.initReject = null;
  }

  private rejectInit(error: Error) {
    if (this.initTimer) clearTimeout(this.initTimer);
    this.initTimer = null;
    this.initReject?.(error);
    this.initResolve = null;
    this.initReject = null;
    this.initOnce = null;
  }

  private failWorker(error: Error) {
    this.rejectInit(error);
    for (const [, pending] of this.pending) pending.reject(error);
    this.pending.clear();
    this.worker?.terminate();
    this.worker = null;
    this.initOnce = null;
  }

  /** 初始化引擎（幂等）；失败后可重试。 */
  init(): Promise<void> {
    if (this.initOnce) return this.initOnce;
    const worker = this.ensureWorker();
    this.initOnce = new Promise<void>((resolve, reject) => {
      this.initResolve = resolve;
      this.initReject = reject;
      this.initTimer = setTimeout(() => this.failWorker(new Error("OCR 引擎初始化超时，请重试或缩小图片")), 90_000);
      worker.postMessage({ type: "init" });
    }).catch((cause) => {
      this.initOnce = null;
      throw cause;
    });
    return this.initOnce;
  }

  /**
   * 校验并识别一张本地图片。图片字节只发给本地 worker；
   * 解码后的像素数校验在主线程完成，防止解码炸弹。
   */
  async recognize(file: File, options: { onPartial?: (partial: OcrPartialResult) => void } = {}): Promise<RecognizeOutcome> {
    const started = performance.now();
    let stageStarted = performance.now();
    const bytes = new Uint8Array(await file.arrayBuffer());
    const fileReadMs = Math.round(performance.now() - stageStarted);
    stageStarted = performance.now();
    const verdict = validateImageFile({ name: file.name, size: file.size, type: file.type }, bytes);
    if (!verdict.ok) throw new Error(verdict.detail);
    const validationMs = Math.round(performance.now() - stageStarted);

    stageStarted = performance.now();
    const bitmap = await createImageBitmap(new Blob([bytes.buffer as ArrayBuffer], { type: "image/png" }));
    let width = 0;
    let height = 0;
    try {
      width = bitmap.width;
      height = bitmap.height;
      const pixelCheck = validateDecodedImage(width, height);
      if (!pixelCheck.ok) throw new Error(pixelCheck.detail);
    } finally {
      bitmap.close();
    }
    const mainDecodeMs = Math.round(performance.now() - stageStarted);

    stageStarted = performance.now();
    await this.init();
    const initMs = Math.round(performance.now() - stageStarted);
    const id = this.nextId++;
    this.handlers.onProgress?.({ stage: "recognizing", detail: "正在本地识别…" });
    const copy = bytes.slice();
    const { lines, ms, metrics } = await new Promise<{ lines: OcrLine[]; ms: number; metrics?: WorkerOcrMetrics }>((resolve, reject) => {
      const bandCount = planOcrBands(height).length;
      const timeoutMs = Math.min(600_000, 120_000 + (bandCount - 1) * 35_000);
      const timer = setTimeout(() => this.failWorker(new Error("OCR 识别超时，请缩小截图后重试")), timeoutMs);
      this.pending.set(id, {
        onPartial: options.onPartial,
        resolve: (value) => { clearTimeout(timer); resolve(value); },
        reject: (error) => { clearTimeout(timer); reject(error); },
      });
      this.ensureWorker().postMessage({ type: "recognize", id, buffer: copy.buffer }, [copy.buffer]);
    });
    return {
      lines, ms, width, height,
      timings: {
        fileReadMs, validationMs, mainDecodeMs, initMs,
        workerMs: metrics?.workerMs ?? ms,
        workerDecodeMs: metrics?.decodeMs ?? 0,
        dedupeMs: metrics?.dedupeMs ?? 0,
        bands: metrics?.bandTimings ?? [],
      },
    };
  }

  dispose() {
    this.failWorker(new Error("OCR 已取消"));
  }
}
