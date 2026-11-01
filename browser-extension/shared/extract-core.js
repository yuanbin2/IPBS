(function () {
/**
 * 通用网页正文抽取 + DOM 转 Markdown（B-043 通用剪藏）。
 *
 * 设计参考 MarkDownload（Apache-2.0）对 Mozilla Readability（Apache-2.0）与
 * Turndown（MIT）的组合用法：先用类 Readability 的评分在当前 DOM 的**克隆树**上
 * 选取正文容器，再用类 Turndown 的规则转 Markdown。本文件是为本仓库 MV3 扩展
 * 重新实现的移植版（无第三方依赖、无 CDN 加载、不修改原网页）。
 *
 * 注意：抽取器不是安全过滤器。来源 HTML/Markdown/URL 都是不可信输入，站内仍按
 * B-040 规则重新校验大小、脚本、属性与 URL 协议。
 */

const EXTRACTOR_VERSION = "webclip-extract-1";

/** 上限：与站内 v2 协议一致，正文 HTML 最多 2 MiB UTF-8。 */
const MAX_HTML_BYTES = 2 * 1024 * 1024;
const MAX_TEXT_CHARS = 400_000;
const MAX_NODES = 200_000;

const DROP_TAGS = new Set([
  "script", "style", "noscript", "template", "iframe", "form", "input", "button",
  "textarea", "select", "option", "meta", "link", "base", "svg", "canvas", "video",
  "audio", "object", "embed", "nav", "aside", "footer", "header",
]);
const KEEP_STRUCTURE = new Set(["p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre", "table", "thead", "tbody", "tr", "th", "td", "hr", "figure", "figcaption"]);
const IMAGE_TAGS = new Set(["img", "picture", "source"]);
const EXTRA_BLOCK_TAGS = new Set(["main", "details", "summary", "dl", "dt", "dd", "figcaption"]);

function utf8Length(value) {
  return new TextEncoder().encode(value).length;
}

/** 收集文本长度，用于容器评分。 */
function textLengthOf(node) {
  const text = node.textContent ?? "";
  return text.replace(/\s+/g, " ").trim().length;
}

function linkDensityOf(node) {
  const text = textLengthOf(node);
  if (!text) return 0;
  let linkText = 0;
  for (const anchor of node.querySelectorAll("a")) linkText += textLengthOf(anchor);
  return Math.min(linkText / text, 1);
}

/** 类 Readability 评分：段落数量、文本长度、类名/id 提示，惩罚链接密度。 */
function scoreContainer(node) {
  let score = 0;
  const paragraphs = node.querySelectorAll("p").length;
  score += Math.min(paragraphs, 60) * 3;
  const text = textLengthOf(node);
  score += Math.min(text, 20000) / 100;
  const identity = `${node.className ?? ""} ${node.id ?? ""}`.toLowerCase();
  if (/(article|post|content|main|entry|body|text|detail)/.test(identity)) score += 20;
  if (/(comment|sidebar|widget|related|recommend|footer|nav|menu|advert|share|social)/.test(identity)) score -= 25;
  score -= linkDensityOf(node) * 30;
  return score;
}

/** 在克隆树上找正文容器；返回 null 表示没有可用正文。 */
function findArticleRoot(clonedDoc) {
  const candidates = [];
  const selectors = ["article", "main", '[role="main"]', ".article", ".post", ".content", ".entry", "#content", ".detail", ".post-content", ".article-content"];
  for (const selector of selectors) {
    for (const node of clonedDoc.querySelectorAll(selector)) {
      if (node.closest("nav, aside, footer")) continue;
      candidates.push(node);
    }
  }
  if (!candidates.length) {
    for (const node of clonedDoc.querySelectorAll("div, section")) {
      const paragraphs = node.querySelectorAll("p").length;
      if (paragraphs >= 3) candidates.push(node);
    }
  }
  let best = null;
  let bestScore = 0;
  for (const node of candidates) {
    const score = scoreContainer(node);
    if (score > bestScore) {
      bestScore = score;
      best = node;
    }
  }
  if (!best) return null;
  const text = textLengthOf(best);
  if (text < 40) return null;
  return best;
}

/** 去掉抽取结果中的噪声节点（克隆树上进行，不影响原网页）。 */
function cleanClone(root) {
  const dropSelectors = [
    "script", "style", "noscript", "template", "iframe", "form", "input", "button",
    "textarea", "select", "svg", "canvas", "video", "audio", "object", "embed",
    "nav", "aside", "footer", "header",
    '[class*="comment"]', '[id*="comment"]', '[class*="sidebar"]', '[id*="sidebar"]',
    '[class*="related"]', '[id*="related"]', '[class*="recommend"]', '[class*="share"]',
    '[class*="social"]', '[class*="advert"]', '[class*="breadcrumb"]', '[class*="pagination"]',
    '[aria-hidden="true"]', '[hidden]',
  ];
  for (const selector of dropSelectors) {
    for (const node of root.querySelectorAll(selector)) {
      // 只清理后代里的噪声，别把正文根节点自己删掉
      if (node !== root) node.remove();
    }
  }
}

function nodeText(node) {
  return (node.textContent ?? "").replace(/\s+/g, " ").trim();
}

function escapeCell(value) {
  return value.replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
}

function codeLanguageOf(node) {
  for (const element of [node, ...node.querySelectorAll("code")].slice(0, 3)) {
    const className = typeof element.className === "string" ? element.className : "";
    const match = /(?:language|lang)-([a-zA-Z0-9_+.#-]{1,20})/.exec(className);
    if (match) return match[1].toLowerCase();
  }
  return "";
}

function markdownForChildren(node, options) {
  let out = "";
  for (const child of node.childNodes) out += markdownForNode(child, options);
  return out;
}

function markdownForNode(node, options) {
  if (node.nodeType === 3) {
    const text = node.nodeValue ?? "";
    return text.replace(/\s+/g, " ");
  }
  if (node.nodeType !== 1) return "";
  const tag = node.tagName.toLowerCase();
  if (DROP_TAGS.has(tag) && !KEEP_STRUCTURE.has(tag)) return "";

  switch (tag) {
    case "h1": case "h2": case "h3": case "h4": case "h5": case "h6": {
      const level = Number(tag.slice(1));
      const text = nodeText(node);
      return text ? `\n\n${"#".repeat(level)} ${text}\n\n` : "";
    }
    case "p": case "div": case "section": case "article": case "figure": {
      const inner = markdownForChildren(node, options).trim();
      return inner ? `\n\n${inner}\n\n` : "";
    }
    case "br":
      return "  \n";
    case "hr":
      return "\n\n---\n\n";
    case "strong": case "b": {
      const inner = nodeText(node);
      return inner ? `**${inner}**` : "";
    }
    case "em": case "i": {
      const inner = nodeText(node);
      return inner ? `*${inner}*` : "";
    }
    case "del": case "s": case "strike": {
      const inner = nodeText(node);
      return inner ? `~~${inner}~~` : "";
    }
    case "code": {
      if (node.closest("pre")) return markdownForChildren(node, options);
      const inner = nodeText(node);
      return inner ? `\`${inner}\`` : "";
    }
    case "pre": {
      const language = codeLanguageOf(node);
      const code = (node.textContent ?? "").replace(/\r\n/g, "\n").replace(/\n+$/, "");
      return `\n\n\`\`\`${language}\n${code}\n\`\`\`\n\n`;
    }
    case "blockquote": {
      const inner = markdownForChildren(node, options).trim();
      if (!inner) return "";
      const quoted = inner.split("\n").map((line) => (line ? `> ${line}` : ">")).join("\n");
      return `\n\n${quoted}\n\n`;
    }
    case "ul": case "ol": {
      const items = [];
      let index = 1;
      for (const child of node.children) {
        if (child.tagName.toLowerCase() !== "li") continue;
        const inner = markdownForChildren(child, options).trim();
        if (!inner) continue;
        const bullet = tag === "ol" ? `${index}. ` : "- ";
        items.push(bullet + inner.split("\n").join("\n  "));
        index += 1;
      }
      return items.length ? `\n\n${items.join("\n")}\n\n` : "";
    }
    case "li":
      return markdownForChildren(node, options);
    case "table": {
      const rows = [];
      for (const tr of node.querySelectorAll("tr")) {
        const cells = [];
        for (const cell of tr.querySelectorAll("th, td")) cells.push(escapeCell(nodeText(cell)));
        if (cells.length) rows.push(cells);
      }
      if (!rows.length) return "";
      const width = Math.max(...rows.map((row) => row.length));
      const header = rows[0];
      while (header.length < width) header.push("");
      const lines = [`| ${header.join(" | ")} |`, `| ${Array.from({ length: width }, () => "---").join(" | ")} |`];
      for (const row of rows.slice(1)) {
        while (row.length < width) row.push("");
        lines.push(`| ${row.join(" | ")} |`);
      }
      return `\n\n${lines.join("\n")}\n\n`;
    }
    case "a": {
      const inner = markdownForChildren(node, options).trim() || nodeText(node);
      const href = node.getAttribute("href") ?? "";
      const safe = safeAbsoluteUrl(href, options.baseUrl);
      if (!safe || !inner) return inner;
      return `[${inner}](${safe})`;
    }
    case "img": {
      const source = imageSourceOf(node, options.baseUrl);
      const alt = (node.getAttribute("alt") ?? "").replace(/[\[\]\r\n]/g, " ").trim();
      if (!source.usable) {
        options.warnings.push({ code: "IMAGE_NEEDS_MANUAL", reference: source.reference });
        // 纯文本占位：绝不生成指向原站的 Markdown 图片语法
        return alt ? `（图片需手动上传：${alt}）` : "";
      }
      options.warnings.push({ code: "IMAGE_REMOTE", reference: source.reference });
      return `![${alt}](${source.reference})`;
    }
    case "source":
      return "";
    default: {
      const inner = markdownForChildren(node, options);
      if (!inner.trim()) return "";
      return EXTRA_BLOCK_TAGS.has(tag) ? `\n\n${inner.trim()}\n\n` : inner;
    }
  }
}

/** 解析正文图片；相对 URL 以原网页为基准，blob/data 等仍需用户手动补图。 */
function imageSourceOf(node, baseUrl = "") {
  const attributes = ["data-src", "data-original", "data-lazy-src", "data-full-src", "src"];
  let raw = "";
  for (const attribute of attributes) {
    const value = (node.getAttribute(attribute) ?? "").trim();
    if (value && !/^(data:|blob:|about:)/i.test(value)) {
      raw = value;
      break;
    }
  }
  if (!raw) {
    const srcset = (node.getAttribute("srcset") ?? "").trim();
    if (srcset) raw = srcset.split(",")[0].trim().split(/\s+/)[0] ?? "";
  }
  if (!raw) {
    const current = node.currentSrc ?? "";
    raw = typeof current === "string" ? current : "";
  }
  const reference = raw.slice(0, 2048);
  if (!reference) return { usable: false, reference: "" };
  if (/^(blob:|data:|file:)/i.test(reference)) return { usable: false, reference };
  const resolved = safeAbsoluteUrl(reference, baseUrl);
  return resolved ? { usable: true, reference: resolved } : { usable: false, reference };
}

/** 把克隆节点转成 Markdown，并收集图片/复杂内容警告。 */
function toMarkdown(root, options = {}) {
  const baseUrl = typeof options.baseUrl === "string" ? options.baseUrl : "";
  const warnings = [];
  const markdown = markdownForChildren(root, { baseUrl, warnings })
    .replace(/\[ \]\s*/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return { markdown, warnings: mergeWarnings(warnings) };
}

function mergeWarnings(warnings) {
  const counts = new Map();
  for (const warning of warnings) {
    const key = warning.code;
    const current = counts.get(key) ?? { code: key, count: 0 };
    current.count += 1;
    counts.set(key, current);
  }
  return [...counts.values()];
}

function safeAbsoluteUrl(raw, baseUrl) {
  const value = (raw ?? "").trim();
  if (!value || value.length > 2048) return "";
  if (/[\x00-\x1f\x7f]/.test(value)) return "";
  try {
    const resolved = new URL(value, baseUrl || "https://invalid.invalid/");
    if (resolved.protocol !== "http:" && resolved.protocol !== "https:") return "";
    if (resolved.username || resolved.password) return "";
    if (resolved.hostname === "invalid.invalid") return "";
    // 去掉常见跟踪参数
    for (const key of [...resolved.searchParams.keys()]) {
      if (/^utm_|^spm$|^from$|^share$|^scene$/i.test(key)) resolved.searchParams.delete(key);
    }
    return resolved.toString();
  } catch {
    return "";
  }
}

/** 标题候选：优先 og:title / <title> / H1。 */
function titleCandidateOf(doc) {
  const og = doc.querySelector('meta[property="og:title"]')?.getAttribute("content");
  if (og && og.trim()) return og.trim().slice(0, 200);
  const h1 = doc.querySelector("h1")?.textContent;
  if (h1 && h1.trim()) return h1.trim().slice(0, 200);
  const title = doc.title ?? "";
  return title.trim().slice(0, 200);
}

/** 站点/作者候选：og:site_name、canonical 主机。 */
function siteCandidateOf(doc, pageUrl) {
  const site = doc.querySelector('meta[property="og:site_name"]')?.getAttribute("content");
  if (site && site.trim()) return site.trim().slice(0, 120);
  try {
    return new URL(pageUrl).hostname.slice(0, 120);
  } catch {
    return "";
  }
}

function canonicalCandidateOf(doc, pageUrl) {
  const link = doc.querySelector('link[rel="canonical"]')?.getAttribute("href");
  const resolved = safeAbsoluteUrl(link, pageUrl);
  if (resolved) return resolved;
  return safeAbsoluteUrl(pageUrl, "") || pageUrl;
}


/**
 * 在页面的隔离世界执行：克隆 DOM → 抽取 → 转 Markdown。
 * mode: "article"（正文） | "selection"（用户选中） | "full"（整页降级）
 */
function extractFromDocument(doc, mode) {
  const titleCandidate = titleCandidateOf(doc);
  const siteCandidate = siteCandidateOf(doc, doc.location?.href ?? "");
  const canonicalUrl = canonicalCandidateOf(doc, doc.location?.href ?? "");
  const warnings = [];

  let root = null;
  if (mode === "selection") {
    const selection = doc.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      return { ok: false, code: "selection_empty", detail: "没有选中任何内容；请在页面上选中要剪藏的文本后重试。" };
    }
    const range = selection.getRangeAt(0);
    const fragment = range.cloneContents();
    const holder = doc.createElement("div");
    holder.appendChild(fragment);
    root = holder;
  } else {
    const clone = doc.documentElement.cloneNode(true);
    cleanClone(clone);
    if (mode === "article") {
      root = findArticleRoot(clone);
      if (!root) {
        warnings.push({ code: "NO_ARTICLE_BODY", count: 1 });
        root = clone.body ?? clone;
      }
    } else {
      root = clone.body ?? clone;
      warnings.push({ code: "FULL_PAGE_MODE", count: 1 });
    }
  }

  const converted = toMarkdown(root, { baseUrl: doc.location?.href ?? "" });
  if (!converted.markdown || converted.markdown.length < 10) {
    return { ok: false, code: "extract_empty", detail: "没有抽取出可用正文；该页可能是登录页、空页或纯动态内容。可改用“整页预览”或手动保存网页。" };
  }
  if (converted.markdown.length > MAX_TEXT_CHARS) {
    return { ok: false, code: "size_limit", detail: "正文过长，超出单次剪藏上限；请选中需要的部分，或使用手动保存 HTML。" };
  }

  // 生成交给站内的正文 HTML（保留结构，站内 HTML 预览再转一次）
  const holder = doc.createElement("div");
  const cloneRoot = root.cloneNode(true);
  cleanClone(cloneRoot);
  // HTML 预览在博客 origin 运行；相对图若不补全会指到博客域名。
  for (const img of [cloneRoot, ...cloneRoot.querySelectorAll("img")]) {
    if (img.tagName?.toLowerCase() !== "img") continue;
    const source = imageSourceOf(img, doc.location?.href ?? "");
    if (source.usable) img.setAttribute("src", source.reference);
    else img.removeAttribute("src");
    img.removeAttribute("srcset");
  }
  holder.appendChild(cloneRoot);
  const html = holder.innerHTML;
  if (utf8Length(html) > MAX_HTML_BYTES) {
    return { ok: false, code: "size_limit", detail: "正文 HTML 超过 2 MiB 上限；请缩小选中范围或改用整页预览。" };
  }
  return {
    ok: true,
    html,
    markdown: converted.markdown,
    warnings: [...warnings, ...converted.warnings],
    titleCandidate,
    siteCandidate,
    canonicalUrl,
    htmlBytes: utf8Length(html),
  };
}

// 经典脚本可由 chrome.scripting.executeScript({ files }) 注入隔离世界；
// ES module 的函数单独注入会丢失所有模块级依赖，导致普通网页采集 ReferenceError。
globalThis.__BLOG_WEBCLIP_EXTRACT__ = {
  EXTRACTOR_VERSION, MAX_HTML_BYTES, MAX_TEXT_CHARS, MAX_NODES,
  findArticleRoot, imageSourceOf, toMarkdown, titleCandidateOf,
  siteCandidateOf, canonicalCandidateOf, extractFromDocument,
};
})();
