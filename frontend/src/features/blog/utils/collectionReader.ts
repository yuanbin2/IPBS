/**
 * 领域阅读页（CollectionDetailView）的展示逻辑纯函数。
 *
 * 背景：旧实现把整棵树递归平铺成「所有节点 + 所有文章」一次性渲染，
 * 60 个节点的领域会渲染 60 个区块（多数还是空的空节点）。
 * 这里提供两件事：
 *   1. 通用分页（页码 clamp、切片、页码窗口），让「当前节点文章」只显示一页；
 *   2. 子节点卡片与搜索命中，让右侧始终只围绕「当前选中的那一个节点」。
 */

import type { CollectionArticleCard, CollectionPublicNode } from "../types";

/** 当前节点文章每页条数。 */
export const NODE_ARTICLE_PAGE_SIZE = 10;
/** 左侧目录树里每个节点最多直接列出的文章数，超出用「还有 N 篇」收敛。 */
export const TREE_ARTICLE_PREVIEW_SIZE = 5;

export interface PageSlice<T> {
  items: T[];
  /** 已 clamp 到 [1, totalPages] 的实际页码；空列表恒为 1。 */
  page: number;
  totalPages: number;
  total: number;
  /** 本页区间（1-based，便于直接展示）；无数据时为 0。 */
  from: number;
  to: number;
}

/** 页码窗口；`0` 代表省略号。总页数不足窗口宽度时直接全列。 */
export function pageWindow(page: number, totalPages: number, span = 5): number[] {
  if (!Number.isFinite(totalPages) || totalPages <= 0) return [];
  const last = Math.trunc(totalPages);
  if (last === 1) return [1];
  const size = Math.max(3, Math.trunc(span) || 5);
  if (last <= size) return Array.from({ length: last }, (_, index) => index + 1);

  const half = Math.floor(size / 2);
  let start = Math.max(1, Math.trunc(page) - half);
  let end = Math.min(last, start + size - 1);
  start = Math.max(1, end - size + 1);

  const pages: number[] = [];
  if (start > 1) {
    pages.push(1);
    if (start > 2) pages.push(0);
  }
  for (let current = start; current <= end; current += 1) pages.push(current);
  if (end < last) {
    if (end < last - 1) pages.push(0);
    pages.push(last);
  }
  return pages;
}

/** 把页码夹到合法区间：非法 / 小于 1 → 1，超过总页数 → 末页。 */
export function clampPage(page: number, totalPages: number): number {
  const requested = Number.isFinite(page) ? Math.trunc(page) : 1;
  if (requested < 1) return 1;
  if (!Number.isFinite(totalPages) || totalPages <= 0) return 1;
  return Math.min(requested, Math.trunc(totalPages));
}

/** 切片 + 元信息。pageSize 非法时退化为 1，避免除零或整页吞掉。 */
export function paginate<T>(items: readonly T[], page: number, pageSize: number): PageSlice<T> {
  const size = Math.max(1, Math.trunc(pageSize) || 1);
  const total = items.length;
  const totalPages = Math.ceil(total / size);
  const current = clampPage(page, totalPages);
  const start = (current - 1) * size;
  const slice = items.slice(start, start + size);
  return {
    items: slice,
    page: current,
    totalPages,
    total,
    from: total === 0 ? 0 : start + 1,
    to: total === 0 ? 0 : start + slice.length,
  };
}

/** 左侧目录树里的文章预览：只取前 limit 篇，并给出被折叠掉的数量。 */
export function treeArticlePreview<T>(
  articles: readonly T[],
  limit = TREE_ARTICLE_PREVIEW_SIZE,
): { shown: T[]; hidden: number } {
  const size = Math.max(0, Math.trunc(limit) || 0);
  return { shown: articles.slice(0, size), hidden: Math.max(0, articles.length - size) };
}

export interface ChildCard {
  node: CollectionPublicNode;
  /** 直属文章数（已按当前筛选条件过滤）。 */
  directCount: number;
  /** 含全部子孙的文章数（已按当前筛选条件过滤）。 */
  subtreeCount: number;
}

export type ArticleFilter = (article: CollectionArticleCard) => boolean;

/** 子树内满足条件的文章总数（含自身节点）。 */
export function subtreeArticleCount(node: CollectionPublicNode, filter: ArticleFilter): number {
  let total = 0;
  for (const article of node.articles) if (filter(article)) total += 1;
  for (const child of node.children) total += subtreeArticleCount(child, filter);
  return total;
}

/**
 * 节点导航卡片：只看直属篇数，但顺带给出含子孙的总数，便于判断值不值得点进去。
 *
 * 选中某节点时传它的 `children`，在领域根时传顶层节点列表。
 */
export function nodeCards(
  nodes: readonly CollectionPublicNode[],
  filter: ArticleFilter,
): ChildCard[] {
  return nodes.map((node) => ({
    node,
    directCount: node.articles.filter(filter).length,
    subtreeCount: subtreeArticleCount(node, filter),
  }));
}

export interface SearchHit {
  article: CollectionArticleCard;
  node: CollectionPublicNode;
  /** 从领域根到该节点的完整路径。 */
  path: CollectionPublicNode[];
}

/**
 * 搜索 / 标签筛选时的扁平命中列表：跨节点收集命中的文章，便于直接对结果分页。
 *
 * 命中判定沿用「节点标题、节点描述、文章标题」三处包含匹配，与左侧树的过滤口径一致，
 * 避免出现「树里显示有匹配、点进去却是空的」。
 */
export function collectSearchHits(
  nodes: readonly CollectionPublicNode[],
  query: string,
  filter: ArticleFilter,
): SearchHit[] {
  const raw = query.trim().toLowerCase();
  const hits: SearchHit[] = [];
  const walk = (list: readonly CollectionPublicNode[], path: CollectionPublicNode[]) => {
    for (const node of list) {
      const nextPath = [...path, node];
      const nodeTextHit =
        Boolean(raw) &&
        (node.title.toLowerCase().includes(raw) || node.description.toLowerCase().includes(raw));
      for (const article of node.articles) {
        if (!filter(article)) continue;
        const articleHit = !raw || nodeTextHit || article.title.toLowerCase().includes(raw);
        if (articleHit) hits.push({ article, node, path: nextPath });
      }
      walk(node.children, nextPath);
    }
  };
  walk(nodes, []);
  return hits;
}

/** 命中节点（含子孙命中）的数量，用于顶部提示「N 个节点有匹配」。 */
export function countMatchingNodes(
  nodes: readonly CollectionPublicNode[],
  query: string,
  filter: ArticleFilter,
): number {
  const raw = query.trim().toLowerCase();
  const count = (node: CollectionPublicNode): number => {
    const selfHit =
      Boolean(raw) &&
      (node.title.toLowerCase().includes(raw) || node.description.toLowerCase().includes(raw));
    let total = 0;
    for (const article of node.articles) {
      if (!filter(article)) continue;
      if (!raw || selfHit || article.title.toLowerCase().includes(raw)) {
        total = 1;
        break;
      }
    }
    for (const child of node.children) total += count(child);
    return total;
  };
  return nodes.reduce((sum, node) => sum + count(node), 0);
}
