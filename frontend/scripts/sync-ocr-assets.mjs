/**
 * B-045 阶段A：把 OCR 运行资源从固定版本的 npm 包复制到 public/，
 * 由本站同源路径提供，运行时绝不请求第三方 CDN。
 *
 * 资源来源（均为 Apache-2.0，详见 docs/长截图OCR转Markdown与私有笔记设计V3.0.md）：
 * - pdfmarkdown-ppocrv5-models@1.0.0  PP-OCRv5 mobile 检测/识别模型与字典
 * - onnxruntime-web@1.23.2            WASM 推理后端
 *
 * 生成 public/models/ocr/manifest.json：版本、SHA-256、字节大小、许可证、来源。
 * 幂等：内容一致时跳过写入。node scripts/sync-ocr-assets.mjs
 */

import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pub = (...p) => path.join(frontendDir, "public", ...p);
const mod = (pkg, ...p) => path.join(frontendDir, "node_modules", pkg, ...p);

const COPIES = [
  { pkg: "pdfmarkdown-ppocrv5-models", from: "detection/PP-OCRv5_mobile_det_infer.ort", to: "models/ocr/PP-OCRv5_mobile_det_infer.ort" },
  { pkg: "pdfmarkdown-ppocrv5-models", from: "recognition/PP-OCRv5_mobile_rec_infer.onnx", to: "models/ocr/PP-OCRv5_mobile_rec_infer.onnx" },
  { pkg: "pdfmarkdown-ppocrv5-models", from: "recognition/ppocrv5_dict.txt", to: "models/ocr/ppocrv5_dict.txt" },
  { pkg: "onnxruntime-web", from: "dist/ort-wasm-simd-threaded.wasm", to: "ort/ort-wasm-simd-threaded.wasm" },
  { pkg: "onnxruntime-web", from: "dist/ort-wasm-simd-threaded.mjs", to: "ort/ort-wasm-simd-threaded.mjs" },
  // Edge/Chrome 有 navigator.gpu 时 ort 会改请求 jsep 变体（即便只用 wasm EP），需一并自托管
  { pkg: "onnxruntime-web", from: "dist/ort-wasm-simd-threaded.jsep.wasm", to: "ort/ort-wasm-simd-threaded.jsep.wasm" },
  { pkg: "onnxruntime-web", from: "dist/ort-wasm-simd-threaded.jsep.mjs", to: "ort/ort-wasm-simd-threaded.jsep.mjs" },
];

function sha256(file) {
  return createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

const modelsVersion = JSON.parse(fs.readFileSync(mod("pdfmarkdown-ppocrv5-models", "package.json"), "utf8")).version;
const ortVersion = JSON.parse(fs.readFileSync(mod("onnxruntime-web", "package.json"), "utf8")).version;
const engineVersion = JSON.parse(fs.readFileSync(mod("ppu-paddle-ocr", "package.json"), "utf8")).version;

for (const copy of COPIES) {
  const src = mod(copy.pkg, copy.from);
  const dest = pub(copy.to);
  if (!fs.existsSync(src)) throw new Error(`缺少资源源文件：${src}（先 npm install）`);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  if (fs.existsSync(dest) && fs.readFileSync(src).equals(fs.readFileSync(dest))) {
    console.log(`未变化 ${copy.to}`);
    continue;
  }
  fs.copyFileSync(src, dest);
  console.log(`已复制 ${copy.to} <- ${copy.pkg}@${copy.pkg === "onnxruntime-web" ? ortVersion : modelsVersion}/${copy.from}`);
}

const manifest = {
  generated_by: "frontend/scripts/sync-ocr-assets.mjs",
  engine: { name: "ppu-paddle-ocr", version: engineVersion, license: "MIT", runtime: "onnxruntime-web" },
  models: { name: "PP-OCRv5 mobile", source: `pdfmarkdown-ppocrv5-models@${modelsVersion}（npm，Apache-2.0）`, license: "Apache-2.0" },
  wasm: { name: "onnxruntime-web", version: ortVersion, license: "MIT", note: "使用单线程 wasm 执行提供者；普通及 jsep 运行资源均由本站同源提供，具体加载项以浏览器实际选择为准" },
  files: {},
};

for (const copy of COPIES) {
  const file = pub(copy.to);
  manifest.files[copy.to] = { sha256: sha256(file), bytes: fs.statSync(file).size };
}

fs.writeFileSync(pub("models/ocr/manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
console.log("manifest 已更新 public/models/ocr/manifest.json");
