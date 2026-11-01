/**
 * 文章标签输入的解析工具。
 *
 * 背景：原实现用 `raw.split(",")`，只认**英文逗号**。中文输入法下逗号默认是全角
 * `，`，于是「算法，基础算法，快速排序」会被整串当成**一个**标签（库里已留下
 * `ArticleTag.name = '算法，基础算法，快速排序'` 这样的脏数据）。
 *
 * 这里统一收口：中英文逗号、顿号、分号、换行都算分隔符；
 * **空格不算**，因为「Agentic RAG」这类标签本身带空格。
 */

/** 允许的分隔符：英文逗号、中文逗号、顿号、中英文分号、换行。 */
const TAG_SEPARATOR = /[,，、;；\n\r]+/;

/** `ArticleTag.name` 的库表上限。 */
export const TAG_NAME_MAX_LENGTH = 60;

/** 一次输入允许的标签数量上限，防止粘贴超长文本撑爆选项。 */
export const TAG_COUNT_LIMIT = 30;

/**
 * 把「用户输入的一个字符串」拆成标签数组。
 *
 * - 中英文逗号 / 顿号 / 分号 / 换行都作为分隔符
 * - 去掉首尾空白与 `#` 前缀（顺手兼容粘贴带井号的写法）
 * - 丢弃空项、超长项
 * - 大小写不敏感去重（保留首次出现的写法）
 */
export function parseTagInput(raw: string): string[] {
  if (typeof raw !== "string" || !raw) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const piece of raw.split(TAG_SEPARATOR)) {
    const name = piece.trim().replace(/^#+/, "").trim();
    if (!name) continue;
    if (name.length > TAG_NAME_MAX_LENGTH) continue;
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(name);
    if (out.length >= TAG_COUNT_LIMIT) break;
  }
  return out;
}

/**
 * 把任意历史形态的标签值规整成字符串数组。
 *
 * 兼容两种输入：数组（当前形态），以及逗号分隔的字符串（旧草稿缓存、
 * 旧版 `draft.tags` 都是这种，localStorage 里可能还留着）。
 */
export function normalizeTagList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return parseTagInput(value.map((item) => String(item ?? "")).join(","));
  }
  if (typeof value === "string") return parseTagInput(value);
  return [];
}

/** 合并两批标签（用于把新输入并进已有选项），同样去重。 */
export function mergeTagNames(...groups: Array<readonly string[]>): string[] {
  return parseTagInput(groups.flat().join(","));
}
