/** Node 测试与扩展弹窗使用的 ESM 门面；页面内执行的是同源经典脚本 extract-core.js。 */
import "./extract-core.js";

const core = globalThis.__BLOG_WEBCLIP_EXTRACT__;
export const EXTRACTOR_VERSION = core.EXTRACTOR_VERSION;
export const MAX_HTML_BYTES = core.MAX_HTML_BYTES;
export const MAX_TEXT_CHARS = core.MAX_TEXT_CHARS;
export const MAX_NODES = core.MAX_NODES;
export const findArticleRoot = core.findArticleRoot;
export const imageSourceOf = core.imageSourceOf;
export const toMarkdown = core.toMarkdown;
export const titleCandidateOf = core.titleCandidateOf;
export const siteCandidateOf = core.siteCandidateOf;
export const canonicalCandidateOf = core.canonicalCandidateOf;
export const extractFromDocument = core.extractFromDocument;
