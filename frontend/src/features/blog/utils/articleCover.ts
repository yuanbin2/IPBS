/** 封面兜底的纯逻辑（B-066）：与后端 services/blog.py 保持同一套判定规则。 */

const MARKDOWN_IMAGE = /!\[[^\]]*\]\(\s*<?([^\s)>]+)>?/g;
const HTML_IMAGE = /<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']/gi;
const UNSAFE_PREFIXES = ["javascript:", "vbscript:", "data:", "file:"];
const MAX_URL_LENGTH = 2048;

/** 只接受 http(s) 绝对地址与站内相对路径。 */
export function isSafeImageUrl(url: string): boolean {
  const value = (url ?? "").trim();
  if (!value || value.length > MAX_URL_LENGTH) return false;
  const lowered = value.toLowerCase();
  if (UNSAFE_PREFIXES.some((prefix) => lowered.startsWith(prefix))) return false;
  return lowered.startsWith("http://") || lowered.startsWith("https://") || lowered.startsWith("/") || lowered.startsWith("./") || lowered.startsWith("../");
}

/** 正文里出现的第一张图片链接（Markdown 与 <img> 按位置竞争，不安全协议跳过）。 */
export function firstImageUrl(content: string): string | null {
  if (!content) return null;
  const candidates: Array<{ index: number; url: string }> = [];
  for (const pattern of [MARKDOWN_IMAGE, HTML_IMAGE]) {
    pattern.lastIndex = 0;
    for (const match of content.matchAll(pattern)) {
      const url = match[1];
      if (url) candidates.push({ index: match.index ?? 0, url });
    }
  }
  candidates.sort((a, b) => a.index - b.index);
  for (const candidate of candidates) {
    const url = candidate.url.trim().replace(/^["']|["']$/g, "").trim();
    if (!isSafeImageUrl(url)) continue;
    return url;
  }
  return null;
}

/** 未填封面时用正文首图兜底，返回补上的链接（没补返回 null）。 */
export function defaultCoverImage(coverImage: string, content: string): string | null {
  if ((coverImage ?? "").trim()) return null;
  return firstImageUrl(content ?? "");
}
