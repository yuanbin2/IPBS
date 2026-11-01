/**
 * 领域目录「已加入文章」的排序纯函数（B-064 拖拽排序）。
 *
 * 后端 reorder 接口只接受**同一父节点下的完整顺序**（`ordered_ids`），
 * 所以拖拽落点必须换算成「同组全量 id 的新顺序」再提交，
 * 而不能只交换可见列表里相邻的两项——列表可能正被筛选框过滤。
 */

/** 与后端 `BlogCollectionEntry.Meta.ordering = ["position", "id"]` 保持一致。 */
export interface OrderableEntry {
  id: number;
  position: number;
}

export type DropPosition = "before" | "after";

/** 按 (position, id) 稳定排序，得到该组当前的真实顺序。 */
export function sortEntriesByPosition<T extends OrderableEntry>(entries: readonly T[]): T[] {
  return [...entries].sort((a, b) => a.position - b.position || a.id - b.id);
}

/**
 * 把 dragId 移动到 targetId 的前/后，返回新的 id 顺序。
 *
 * - 任一 id 不在列表中、或拖到自己身上 → 原样返回（调用方据此跳过请求）。
 * - 被筛选隐藏的项保持相对顺序，只是整体让位给被拖动项。
 */
export function moveEntryRelative(
  ids: readonly number[],
  dragId: number,
  targetId: number,
  position: DropPosition,
): number[] {
  if (dragId === targetId) return [...ids];
  const from = ids.indexOf(dragId);
  const to = ids.indexOf(targetId);
  if (from < 0 || to < 0) return [...ids];

  const next = [...ids];
  next.splice(from, 1);
  const anchor = next.indexOf(targetId);
  next.splice(anchor + (position === "after" ? 1 : 0), 0, dragId);
  return next;
}

/** 顺序没有发生实际变化时返回 true（避免无谓的 reorder 请求）。 */
export function isSameOrder(a: readonly number[], b: readonly number[]): boolean {
  return a.length === b.length && a.every((id, index) => id === b[index]);
}
