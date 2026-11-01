/**
 * 安全审计流的纯逻辑（滚动到底再加载下一页）。
 *
 * 抽出来的原因：这个页面没有组件挂载基建，分页合并与底部文案只能靠纯函数兜住。
 * 运行：npm run test:unit
 */

export interface IdentifiableRow {
  id: number;
}

export interface AuditFeedState {
  /** 已渲染条数 */
  loaded: number;
  /** 服务端总量 */
  total: number;
  hasMore: boolean;
  loading: boolean;
}

/**
 * 追加下一页：按 id 去重（首次判决即可，重复的后台事件不会被渲染两次），
 * 且不改动原数组顺序——服务端已是 -created_at 倒序。
 */
export function mergeAuditEvents<T extends IdentifiableRow>(existing: T[], incoming: T[]): T[] {
  if (!incoming.length) return existing;
  const seen = new Set(existing.map((item) => item.id));
  const appended: T[] = [];
  for (const item of incoming) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    appended.push(item);
  }
  return appended.length ? [...existing, ...appended] : existing;
}

/**
 * 独立滚动框的兜底判定：离底部 threshold 像素内就该补一页。
 * 不能只看 scrollTop（内容不足一屏时永远为 0），也不能只用 scrollHeight（还没铺开）。
 */
export function shouldLoadOnScroll(
  scrollTop: number,
  clientHeight: number,
  scrollHeight: number,
  threshold = 60,
): boolean {
  if (scrollHeight <= 0) return false;
  return scrollTop + clientHeight >= scrollHeight - Math.max(0, threshold);
}

/** 底部提示文案；loading 优先，其次空态 / 未加载完 / 已到底。 */
export function auditFeedHint(state: AuditFeedState): string {
  if (state.loading) return "正在加载…";
  if (!state.loaded) return state.hasMore || state.total > 0 ? "正在加载…" : "暂无安全审计事件";
  if (state.hasMore) return `已显示 ${state.loaded} / ${state.total} 条，下滑加载更多`;
  return `已全部加载，共 ${state.total} 条`;
}
