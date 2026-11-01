/**
 * 领域目录树的公共纯函数。
 *
 * 抽出来的原因：查看页与编辑页都需要「扁平节点 → 树 → 按折叠状态展开成可见行」，
 * 而原实现把「自身被折叠」也算进「处于折叠分支」，导致**折叠父节点时父节点自己
 * 也消失、无法再展开**（B-059）。这里用递归结构从根本上规避：折叠只影响子级。
 */

/** 扁平节点（来自领域草稿接口）。 */
export interface FlatCollectionNode {
  id: number;
  title: string;
  description: string;
  position: number;
  parent: number | null;
}

export interface CollectionTreeNode<T extends FlatCollectionNode = FlatCollectionNode> {
  node: T;
  children: CollectionTreeNode<T>[];
  /** 从 1 开始：1 = 领域根下的第一级。 */
  depth: number;
}

export interface CollectionTreeRow<T extends FlatCollectionNode = FlatCollectionNode> {
  node: T;
  depth: number;
  hasChildren: boolean;
  childCount: number;
}

/**
 * 由 `parent` 引用构建树，并按 `position` 稳定排序。
 *
 * 容错：父引用不存在、自引用、或父子互相引用形成环时，该节点按**根**处理，
 * 保证任何节点都不会在界面上凭空消失。
 */
export function buildCollectionTree<T extends FlatCollectionNode>(
  nodes: readonly T[],
): CollectionTreeNode<T>[] {
  const byId = new Map<number, T>();
  for (const node of nodes) byId.set(node.id, node);

  const wrappers = new Map<number, CollectionTreeNode<T>>();
  for (const node of nodes) wrappers.set(node.id, { node, children: [], depth: 1 });

  const roots: CollectionTreeNode<T>[] = [];
  for (const node of nodes) {
    const wrapper = wrappers.get(node.id)!;
    const parentId = node.parent;
    const parentNode = parentId == null ? undefined : byId.get(parentId);
    const usableParent =
      parentNode && parentId !== node.id ? wrappers.get(parentId!) : undefined;

    if (usableParent && !createsCycle(node.id, byId)) {
      usableParent.children.push(wrapper);
    } else {
      roots.push(wrapper);
    }
  }

  const assignDepth = (list: CollectionTreeNode<T>[], depth: number) => {
    list.sort(
      (a, b) => a.node.position - b.node.position || a.node.id - b.node.id,
    );
    for (const item of list) {
      item.depth = depth;
      assignDepth(item.children, depth + 1);
    }
  };
  assignDepth(roots, 1);
  return roots;
}

/** 沿 parent 链上溯，若回到自身（或遇到重复）则说明存在环。 */
function createsCycle(startId: number, byId: Map<number, FlatCollectionNode>): boolean {
  const seen = new Set<number>();
  let cursor = byId.get(startId)?.parent ?? null;
  while (cursor != null) {
    if (cursor === startId || seen.has(cursor)) return true;
    seen.add(cursor);
    cursor = byId.get(cursor)?.parent ?? null;
  }
  return false;
}

/**
 * 节点是否因**祖先**被折叠而隐藏。
 *
 * 注意：只看祖先，**不含自身**。折叠父节点时父节点自身必须仍然可见，否则用户
 * 无法把它重新展开。
 */
export function isHiddenByAncestors(
  ancestorIds: readonly number[],
  collapsed: ReadonlySet<number>,
): boolean {
  return ancestorIds.some((id) => collapsed.has(id));
}

/**
 * 按折叠状态把树展开成可见行列表。
 *
 * 被折叠的节点**自身保留**（可再次点击展开），只跳过它的子树。
 */
export function flattenCollectionTree<T extends FlatCollectionNode>(
  tree: readonly CollectionTreeNode<T>[],
  collapsed: ReadonlySet<number>,
): CollectionTreeRow<T>[] {
  const rows: CollectionTreeRow<T>[] = [];
  const walk = (list: readonly CollectionTreeNode<T>[]) => {
    for (const item of list) {
      rows.push({
        node: item.node,
        depth: item.depth,
        hasChildren: item.children.length > 0,
        childCount: item.children.length,
      });
      if (collapsed.has(item.node.id)) continue; // 只跳过子级
      walk(item.children);
    }
  };
  walk(tree);
  return rows;
}

/** 树中所有节点 id（用于「全部折叠」）。 */
export function collectTreeIds<T extends FlatCollectionNode>(
  tree: readonly CollectionTreeNode<T>[],
): number[] {
  const ids: number[] = [];
  const walk = (list: readonly CollectionTreeNode<T>[]) => {
    for (const item of list) {
      ids.push(item.node.id);
      walk(item.children);
    }
  };
  walk(tree);
  return ids;
}

/** 某节点的后代 id（不含自身）。 */
export function collectDescendantIds<T extends FlatCollectionNode>(
  node: CollectionTreeNode<T>,
): number[] {
  const ids: number[] = [];
  const walk = (list: readonly CollectionTreeNode<T>[]) => {
    for (const item of list) {
      ids.push(item.node.id);
      walk(item.children);
    }
  };
  walk(node.children);
  return ids;
}

/** 只有存在子节点的节点才值得放进折叠集合（避免无意义的折叠标记）。 */
export function collapsibleIds<T extends FlatCollectionNode>(
  tree: readonly CollectionTreeNode<T>[],
): number[] {
  const ids: number[] = [];
  const walk = (list: readonly CollectionTreeNode<T>[]) => {
    for (const item of list) {
      if (item.children.length) ids.push(item.node.id);
      walk(item.children);
    }
  };
  walk(tree);
  return ids;
}
