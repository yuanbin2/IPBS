/**
 * 把 Vditor 运行时按需加载的排版资源从 npm 包复制到 public/，
 * 与 OCR 资产同一策略：本站同源提供，运行时不请求第三方 CDN。
 *
 * 背景：vditor 默认 cdn 是 https://unpkg.com/vditor@版本，核心解析器 lute、
 * KaTeX 公式、mermaid 流程图、代码高亮样式都在运行时按需拉取；unpkg 不可达时
 * 编辑器初始化缓慢，公式/流程图/高亮直接失效。VditorEditor 通过 cdn 选项指向
 * /vendor/vditor 后，所有资源同源加载；md-editor-v3（文章阅读页与 OCR 校对
 * 预览）的公式/流程图也复用同一份 katex/mermaid。
 *
 * 复制清单是子集而非整个 dist（24MB）。排除的目录是编辑器当前不会按需加载、
 * 或明确未启用的图表引擎：mathjax（默认 KaTeX）、graphviz、plantuml、
 * smiles-drawer、wavedrom、abcjs、echarts、markmap。启用任一引擎时在此补录。
 *
 * 幂等：内容一致时跳过写入。node scripts/sync-editor-assets.mjs
 */

import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pub = (...p) => path.join(frontendDir, "public", ...p);
const vditorDist = path.join(frontendDir, "node_modules", "vditor", "dist");

// 单文件直接复制；目录用 DIR_COPIES 整目录复制。
const FILE_COPIES = [
  "index.css",
  "method.min.js",
];

const DIR_COPIES = [
  "js/lute",
  "js/katex",
  "js/mermaid",
  "js/flowchart.js",
  "js/highlight.js",
  "js/i18n",
  "js/icons",
  "css",
  "images",
];

function sha256(file) {
  return createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function copyFileSync(src, dest, manifest) {
  if (!fs.existsSync(dest) || !fs.readFileSync(src).equals(fs.readFileSync(dest))) {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(src, dest);
    console.log(`已复制 ${path.relative(pub(), dest)}`);
  }
  const rel = path.relative(pub(), dest).replaceAll("\\", "/");
  manifest.files[rel] = { bytes: fs.statSync(dest).size, sha256: sha256(dest) };
}

function copyDirSync(src, dest, manifest) {
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDirSync(srcPath, destPath, manifest);
    else copyFileSync(srcPath, destPath, manifest);
  }
}

const vditorVersion = JSON.parse(fs.readFileSync(path.join(frontendDir, "node_modules", "vditor", "package.json"), "utf8")).version;
const manifest = {
  generated_by: "frontend/scripts/sync-editor-assets.mjs",
  engine: { name: "vditor", version: vditorVersion, license: "MIT", note: "编辑器与阅读页的公式/流程图/代码高亮资源由本站同源提供，运行时不请求第三方 CDN" },
  files: {},
};

for (const rel of FILE_COPIES) {
  copyFileSync(path.join(vditorDist, rel), pub("vendor", "vditor", "dist", rel), manifest);
}
for (const rel of DIR_COPIES) {
  copyDirSync(path.join(vditorDist, rel), pub("vendor", "vditor", "dist", rel), manifest);
}

fs.writeFileSync(pub("vendor", "vditor", "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
console.log("manifest 已更新 public/vendor/vditor/manifest.json");
