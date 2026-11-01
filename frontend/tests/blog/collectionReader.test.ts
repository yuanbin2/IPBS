import { test } from "node:test";
import assert from "node:assert/strict";
import {
  NODE_ARTICLE_PAGE_SIZE,
  TREE_ARTICLE_PREVIEW_SIZE,
  clampPage,
  collectSearchHits,
  countMatchingNodes,
  nodeCards,
  pageWindow,
  paginate,
  subtreeArticleCount,
  treeArticlePreview,
} from "../../src/features/blog/utils/collectionReader.ts";
import type { CollectionArticleCard, CollectionPublicNode } from "../../src/features/blog/types.ts";

function article(id: number, title: string, tags: string[] = []): CollectionArticleCard {
  return {
    id,
    title,
    slug: `a-${id}`,
    author_name: "wxbroute",
    summary: "",
    cover_image: "",
    published_at: null,
    tags,
    category: "",
  };
}

function node(
  id: number,
  title: string,
  articles: CollectionArticleCard[] = [],
  children: CollectionPublicNode[] = [],
  description = "",
): CollectionPublicNode {
  return { id, title, description, article_count: articles.length, articles, breadcrumb: [], children };
}

const always = () => true;

test("paginate：按页切片并给出 1-based 区间", () => {
  const items = Array.from({ length: 23 }, (_, index) => index + 1);
  const first = paginate(items, 1, 10);
  assert.equal(first.total, 23);
  assert.equal(first.totalPages, 3);
  assert.deepEqual(first.items, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  assert.equal(first.from, 1);
  assert.equal(first.to, 10);

  const last = paginate(items, 3, 10);
  assert.deepEqual(last.items, [21, 22, 23]);
  assert.equal(last.from, 21);
  assert.equal(last.to, 23);
});

test("paginate：页码越界夹到末页，空列表不产生 0 页", () => {
  const items = [1, 2, 3];
  assert.equal(paginate(items, 99, 2).page, 2);
  assert.equal(paginate([], 1, 10).totalPages, 0);
  assert.equal(paginate([], 5, 10).page, 1);
  assert.equal(paginate([], 1, 10).from, 0);
  // pageSize 非法时退化为 1，不至于把整页吞掉或除零
  assert.equal(paginate(items, 1, 0).totalPages, 3);
});

test("clampPage：非法值与边界", () => {
  assert.equal(clampPage(Number.NaN, 5), 1);
  assert.equal(clampPage(0, 5), 1);
  assert.equal(clampPage(-3, 5), 1);
  assert.equal(clampPage(2.7, 5), 2);
  assert.equal(clampPage(9, 5), 5);
  assert.equal(clampPage(9, 0), 1);
});

test("pageWindow：总页数不足窗口时全列，超出时首尾恒在并用 0 表示省略号", () => {
  assert.deepEqual(pageWindow(1, 1), [1]);
  assert.deepEqual(pageWindow(1, 0), []);
  assert.deepEqual(pageWindow(1, 4), [1, 2, 3, 4]);
  const middle = pageWindow(5, 10);
  assert.equal(middle[0], 1);
  assert.equal(middle[middle.length - 1], 10);
  assert.ok(middle.includes(5));
  assert.ok(middle.includes(0), "超范围时应出现省略号");
  // 靠首页时窗口右移，靠末页时左移，但都不丢首尾
  assert.equal(pageWindow(1, 10)[0], 1);
  assert.equal(pageWindow(10, 10)[pageWindow(10, 10).length - 1], 10);
});

test("treeArticlePreview：截断并给出隐藏数量", () => {
  assert.equal(TREE_ARTICLE_PREVIEW_SIZE, 5);
  const preview = treeArticlePreview([1, 2, 3, 4, 5, 6, 7], 5);
  assert.deepEqual(preview.shown, [1, 2, 3, 4, 5]);
  assert.equal(preview.hidden, 2);
  assert.deepEqual(treeArticlePreview([1, 2], 5), { shown: [1, 2], hidden: 0 });
});

test("subtreeArticleCount / nodeCards：按筛选条件统计直属与含子孙篇数", () => {
  const leaf = node(2, "排序", [article(1, "快排", ["算法"]), article(2, "归并", ["算法"])]);
  const mid = node(3, "树", [article(3, "线段树", ["数据结构"])], [leaf]);
  const root = node(1, "根", [article(4, "概览")], [mid]);

  assert.equal(subtreeArticleCount(root, always), 4);
  assert.equal(subtreeArticleCount(mid, always), 3);
  assert.equal(subtreeArticleCount(mid, (item) => item.tags.includes("算法")), 2);

  const cards = nodeCards([leaf, mid], always);
  assert.deepEqual(
    cards.map((card) => [card.node.id, card.directCount, card.subtreeCount]),
    [
      [2, 2, 2],
      [3, 1, 3],
    ],
  );
});

test("collectSearchHits：跨节点收集命中，节点标题命中时带上整节点文章", () => {
  const a = article(1, "快速排序详解");
  const b = article(2, "二叉树遍历", ["树"]);
  const c = article(3, "哈希表", ["哈希"]);
  const tree = [node(1, "排序", [a]), node(2, "树结构", [b, c], [node(3, "高级树", [article(4, "红黑树")])])];

  assert.equal(collectSearchHits(tree, "", always).length, 4);

  const sortHits = collectSearchHits(tree, "快速", always);
  assert.equal(sortHits.length, 1);
  assert.equal(sortHits[0].article.id, 1);

  // 节点标题命中 → 该节点下全部文章都算命中（含被标签筛掉的也要先过 filter）
  const treeHits = collectSearchHits(tree, "树结构", always);
  assert.deepEqual(treeHits.map((hit) => hit.article.id), [2, 3]);

  // 路径信息完整，便于在结果里直接跳回节点
  assert.deepEqual(treeHits[0].path.map((item) => item.id), [2]);
  const deep = collectSearchHits(tree, "红黑", always);
  assert.deepEqual(deep[0].path.map((item) => item.id), [2, 3]);

  // 标签筛选与关键词叠加
  assert.equal(collectSearchHits(tree, "", (item) => item.tags.includes("哈希")).length, 1);
  assert.equal(collectSearchHits(tree, "树", (item) => item.tags.includes("哈希")).length, 1);
});

test("countMatchingNodes：统计有命中的节点数（含子孙命中）", () => {
  const tree = [
    node(1, "排序", [article(1, "快排")]),
    node(2, "树结构", [article(2, "遍历")], [node(3, "高级树", [article(3, "红黑树")])]),
    node(4, "图论", [article(4, "最短路")]),
  ];
  assert.equal(countMatchingNodes(tree, "", always), 4);
  assert.equal(countMatchingNodes(tree, "红黑", always), 1);
  assert.equal(countMatchingNodes(tree, "树", always), 2); // 树结构 + 高级树
});

test("每页条数常量符合阅读页设定", () => {
  assert.equal(NODE_ARTICLE_PAGE_SIZE, 10);
});
