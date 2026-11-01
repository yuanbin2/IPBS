import { computed, ref, type ComputedRef } from "vue";
import { ElMessage } from "element-plus";
import type { CollectionDraft } from "../types";
import { countImported, summarizeImportPlan, validateArchiveFile, type ImportPlan } from "../utils/archiveTransfer";
import { fetchCollectionArchive, uploadCollectionArchive, type ImportConflict, type ImportResult } from "../api/archiveApi";

/** 归档选择、导入预览与下载的唯一状态来源；领域列表由页面提供。 */
export function useCollectionArchiveTransfer(
  visibleCollections: ComputedRef<CollectionDraft[]>,
  reloadCollections: () => Promise<void>,
) {
  const selectedIds = ref<string[]>([]);
  const exportBusy = ref(false);
  const importDialog = ref(false);
  const importFile = ref<File | null>(null);
  const importPlan = ref<ImportPlan | null>(null);
  const importConflict = ref<ImportConflict>("skip");
  const importBusy = ref(false);
  const importApplying = ref(false);

  const selectedCount = computed(() => selectedIds.value.length);
  const allVisibleSelected = computed(() =>
    visibleCollections.value.length > 0 &&
    visibleCollections.value.every((item) => selectedIds.value.includes(item.public_id)),
  );
  const importSummary = computed(() => summarizeImportPlan(importPlan.value));

  function isSelected(publicId: string): boolean { return selectedIds.value.includes(publicId); }
  function toggleSelect(publicId: string, checked: boolean): void {
    if (checked) {
      if (!selectedIds.value.includes(publicId)) selectedIds.value.push(publicId);
    } else {
      selectedIds.value = selectedIds.value.filter((id) => id !== publicId);
    }
  }
  function toggleSelectAll(checked: boolean): void {
    selectedIds.value = checked ? visibleCollections.value.map((item) => item.public_id) : [];
  }

  async function downloadArchive(publicIds: string[]): Promise<void> {
    if (!publicIds.length) return;
    exportBusy.value = true;
    try {
      const { blob, filename } = await fetchCollectionArchive(publicIds);
      const href = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement("a");
        anchor.href = href;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        URL.revokeObjectURL(href);
      }
      ElMessage.success(`已导出 ${publicIds.length} 个领域`);
    } finally {
      exportBusy.value = false;
    }
  }
  function exportOne(item: CollectionDraft): void {
    void downloadArchive([item.public_id]).catch((cause: unknown) =>
      ElMessage.error(cause instanceof Error ? cause.message : "导出失败"));
  }
  function exportSelected(): void {
    if (!selectedIds.value.length) { ElMessage.warning("请先勾选要导出的领域"); return; }
    void downloadArchive(selectedIds.value).catch((cause: unknown) =>
      ElMessage.error(cause instanceof Error ? cause.message : "导出失败"));
  }

  function openImportDialog(): void {
    importFile.value = null;
    importPlan.value = null;
    importConflict.value = "skip";
    importDialog.value = true;
  }
  function pickImportFile(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    const check = validateArchiveFile(file);
    if (!check.ok) {
      importFile.value = null;
      importPlan.value = null;
      if (file) ElMessage.error(check.reason);
      return;
    }
    importFile.value = file;
    importPlan.value = null;
    void previewImport();
  }
  async function previewImport(): Promise<void> {
    const file = importFile.value;
    const check = validateArchiveFile(file);
    if (!file || !check.ok) { ElMessage.error(check.reason || "请选择导出的压缩包"); return; }
    importBusy.value = true;
    try {
      importPlan.value = await uploadCollectionArchive(file, "preview") as ImportPlan;
    } catch (cause) {
      importPlan.value = null;
      ElMessage.error(cause instanceof Error ? cause.message : "预览失败");
    } finally {
      importBusy.value = false;
    }
  }
  async function applyImport(): Promise<void> {
    const file = importFile.value;
    const check = validateArchiveFile(file);
    if (!file || !check.ok) { ElMessage.error(check.reason || "请选择导出的压缩包"); return; }
    importApplying.value = true;
    try {
      const payload = await uploadCollectionArchive(file, "apply", importConflict.value) as ImportResult;
      const created = countImported(payload.collections);
      const skipped = (payload.collections?.length ?? 0) - created;
      ElMessage.success(
        `已导入 ${created} 个领域（${payload.totals?.articles ?? 0} 篇文章、${payload.totals?.images ?? 0} 张图片）` +
        (skipped ? `，跳过 ${skipped} 个已存在的领域` : ""),
      );
      importDialog.value = false;
      selectedIds.value = [];
      await reloadCollections();
    } catch (cause) {
      ElMessage.error(cause instanceof Error ? cause.message : "导入失败");
    } finally {
      importApplying.value = false;
    }
  }
  return {
    selectedIds, exportBusy, importDialog, importFile, importPlan, importConflict, importBusy,
    importApplying, selectedCount, allVisibleSelected, importSummary, isSelected, toggleSelect,
    toggleSelectAll, exportOne, exportSelected, openImportDialog, pickImportFile, applyImport,
  };
}
