/**
 * md-editor-v3 全局扩展资源配置（文章阅读页 + 截图 OCR 校对预览共用）。
 *
 * 默认配置从 jsdelivr CDN 拉取 KaTeX 与 mermaid，国内网络经常不可达，
 * 公式和流程图会静默失效。这里指向 scripts/sync-editor-assets.mjs 复制到
 * public/vendor/vditor/ 的同源副本（与 Vditor 编辑器共用同一份文件），
 * 公式（$...$ / $$...$$）、mermaid 图表在阅读页可靠渲染。
 */
import { config } from "md-editor-v3";

const VENDOR_VDITOR = "/vendor/vditor/dist";

let configured = false;

export function configureMarkdownExtensions(): void {
  if (configured) return;
  configured = true;
  config({
    editorExtensions: {
      katex: {
        css: `${VENDOR_VDITOR}/js/katex/katex.min.css`,
        js: `${VENDOR_VDITOR}/js/katex/katex.min.js`,
      },
      mermaid: {
        js: `${VENDOR_VDITOR}/js/mermaid/mermaid.min.js`,
      },
    },
  });
}
