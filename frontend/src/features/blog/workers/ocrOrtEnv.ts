/**
 * B-045：onnxruntime-web 环境配置。必须在 ppu-paddle-ocr/web 之前导入：
 * ppu 库的 applyDefaultWasmPaths() 只在 ort.env.wasm.wasmPaths 为空时
 * 才会写入 jsDelivr CDN 地址；这里先固定为本站同源路径，运行时
 * 绝不请求第三方域名（设计 V3.0 §6）。
 */
import * as ort from "onnxruntime-web";

// 必须带完整 origin 的绝对 URL：Vite dev 会把不带协议的路径当作源码模块导入
// （public 目录文件不允许被 import），绝对 URL 则由浏览器按普通静态资源拉取。
const ortOrigin = typeof self !== "undefined" && self.location?.origin ? self.location.origin : "";
ort.env.wasm.wasmPaths = `${ortOrigin}/ort/`;
// 本站未启用 COOP/COEP（无 SharedArrayBuffer），WASM fallback 显式单线程；
// WebGPU 可用时不依赖 SharedArrayBuffer，WASM 资源仍同源自托管供 fallback/算子使用。
ort.env.wasm.numThreads = 1;
// Worker 初始化时优先探测 WebGPU，并回退到本地 WASM。
ort.env.wasm.proxy = false;

export { ort };
