/** 批量加入文章与自动收录规则的纯逻辑（B-065）：无副作用，便于单测。 */

export interface AutoRuleLike {
  id?: number;
  node: number | null;
  node_label?: string;
  category: { id: number; name: string; slug?: string } | null;
  tag?: { id: number; name: string } | null;
  enabled?: boolean;
}

/** 把任意来源的选择值规整成正数 ID 列表，保持首次出现顺序并去重。 */
export function dedupeArticleIds(values: unknown): number[] {
  if (!Array.isArray(values)) return [];
  const seen = new Set<number>();
  const result: number[] = [];
  for (const value of values) {
    const id = typeof value === "number" ? value : Number(value);
    if (!Number.isInteger(id) || id <= 0) continue;
    if (seen.has(id)) continue;
    seen.add(id);
    result.push(id);
  }
  return result;
}

/** 过滤掉目录中已收录的文章，避免无谓请求（后端也会跳过，这里只是提前反馈）。 */
export function pendingArticleIds(selected: unknown, collected: unknown): number[] {
  const existing = new Set(dedupeArticleIds(collected));
  return dedupeArticleIds(selected).filter((id) => !existing.has(id));
}

/** 批量加入结果的人话提示。 */
export function summarizeBatchResult(added: number, skipped: number): string {
  if (added > 0 && skipped > 0) return `已加入 ${added} 篇，${skipped} 篇此前已在目录中`;
  if (added > 0) return `已加入 ${added} 篇`;
  if (skipped > 0) return `这 ${skipped} 篇已经在该目录中了`;
  return "没有可加入的文章";
}

/** 规则的可读描述，例如「算法 #动态规划 → 第一章」。 */
export function autoRuleLabel(rule: AutoRuleLike): string {
  const category = rule.category?.name ?? "全部分类";
  const tag = rule.tag?.name ? ` #${rule.tag.name}` : "";
  const target = rule.node_label ?? (rule.node === null ? "领域根" : `节点 ${rule.node}`);
  return `${category}${tag} → ${target}`;
}

/** 规则去重键：同一节点下的同一「分类 + 标签」组合只允许一条。 */
export function autoRuleKey(node: number | null, categoryId: number | null, tagId: number | null): string {
  return `${node ?? "root"}/${categoryId ?? "-"}/${tagId ?? "-"}`;
}

/** 表单是否可提交：必须选分类（标签可选，节点为空表示领域根）。 */
export function canCreateRule(categoryId: number | null | undefined): boolean {
  return typeof categoryId === "number" && Number.isInteger(categoryId) && categoryId > 0;
}
