import { buildExportUrl, parseContentDispositionFilename, type ImportPlan } from "../utils/archiveTransfer.ts";

export type ImportConflict = "skip" | "replace" | "rename";
export interface ImportResult {
  detail?: string;
  collections?: unknown[];
  totals?: { images?: number; articles?: number };
}

export async function fetchCollectionArchive(publicIds: string[]): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(buildExportUrl(publicIds), { credentials: "include" });
  if (!response.ok) {
    let detail = `导出失败（${response.status}）`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      // 非 JSON 错误体沿用状态码文案。
    }
    throw new Error(detail);
  }
  return {
    blob: await response.blob(),
    filename: parseContentDispositionFilename(response.headers.get("content-disposition")) || "blog-collections.zip",
  };
}

export async function uploadCollectionArchive(
  file: File,
  mode: "preview" | "apply",
  conflict?: ImportConflict,
): Promise<ImportPlan | ImportResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("mode", mode);
  if (mode === "apply" && conflict) form.append("conflict", conflict);
  const response = await fetch("/api/agent/blog/collections/import/", {
    method: "POST",
    credentials: "include",
    body: form,
  });
  const payload = (await response.json()) as (ImportPlan | ImportResult) & { detail?: string };
  if (!response.ok) throw new Error(payload.detail || `${mode === "preview" ? "预览" : "导入"}失败（${response.status}）`);
  return payload;
}
