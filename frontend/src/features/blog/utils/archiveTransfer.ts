/** 领域归档导出/导入（B-067）的纯逻辑：URL 组装、文件名解析、导入预览摘要。 */

export const MAX_ARCHIVE_BYTES = 200 * 1024 * 1024;
export const MAX_EXPORT_SELECTION = 20;

/** 批量导出链接：多个 public_id 用逗号拼接，单个也走同一条接口。 */
export function buildExportUrl(publicIds: string[]): string {
  const ids = publicIds.map((id) => id.trim()).filter(Boolean);
  if (!ids.length) return "";
  return `/api/agent/blog/collections/export/?ids=${encodeURIComponent(ids.join(","))}`;
}

/** 从 Content-Disposition 里取出文件名，兼容 RFC 5987 的 filename* 形式。 */
export function parseContentDispositionFilename(header: string | null): string {
  if (!header) return "";
  const match = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(header);
  if (match) {
    try {
      return decodeURIComponent(match[1].replace(/^"|"$/g, "").trim());
    } catch {
      return match[1].replace(/^"|"$/g, "").trim();
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1].trim() : "";
}

export interface ArchiveFileCheck {
  ok: boolean;
  reason: string;
}

/** 导入前的文件级校验：只认 zip，且不超过后端 200 MiB 上限。 */
export function validateArchiveFile(file: { name: string; size: number } | null): ArchiveFileCheck {
  if (!file) return { ok: false, reason: "请选择导出的压缩包" };
  if (!/\.zip$/i.test(file.name)) return { ok: false, reason: "只支持 .zip 格式的导出包" };
  if (file.size && file.size > MAX_ARCHIVE_BYTES) return { ok: false, reason: "压缩包不能超过 200 MiB" };
  return { ok: true, reason: "" };
}

export interface ImportPlan {
  collections?: Array<{
    title?: string;
    slug?: string;
    directory?: string;
    collection_exists?: boolean;
    articles?: number;
    new_articles?: number;
    skipped_articles?: number;
    images?: number;
    missing_images?: string[];
    nodes?: number;
    entries?: number;
  }>;
  totals?: {
    collections?: number;
    articles?: number;
    images?: number;
    nodes?: number;
    entries?: number;
    skipped_articles?: number;
  };
  warnings?: string[];
}

export interface ImportSummary {
  lines: string[];
  warnings: string[];
  hasConflict: boolean;
}

/** 把后端预览结果整理成可直接展示的文案。 */
export function summarizeImportPlan(plan: ImportPlan | null): ImportSummary {
  if (!plan) return { lines: [], warnings: [], hasConflict: false };
  const lines: string[] = [];
  const totals = plan.totals ?? {};
  lines.push(
    `共 ${totals.collections ?? 0} 个领域 · ${totals.articles ?? 0} 篇文章 · ${totals.images ?? 0} 张图片 · ${totals.nodes ?? 0} 个节点`,
  );
  for (const item of plan.collections ?? []) {
    const parts: string[] = [];
    parts.push(`${item.articles ?? 0} 篇`);
    if (item.images) parts.push(`${item.images} 张图`);
    if (item.skipped_articles) parts.push(`${item.skipped_articles} 篇已存在`);
    if (item.missing_images?.length) parts.push(`${item.missing_images.length} 张图缺失`);
    lines.push(`· ${item.title || item.slug || item.directory || "未命名"}：${parts.join(" · ")}`);
  }
  const hasConflict = Boolean(totals.skipped_articles) || (plan.collections ?? []).some((item) => item.collection_exists);
  return { lines, warnings: plan.warnings ?? [], hasConflict };
}

/** 导入结果里成功创建的领域数量，用于提示文案。 */
export function countImported(collectionResults: unknown[] | undefined): number {
  if (!Array.isArray(collectionResults)) return 0;
  return collectionResults.filter((item) => {
    const value = item as { status?: string } | null;
    return value?.status === "created";
  }).length;
}
