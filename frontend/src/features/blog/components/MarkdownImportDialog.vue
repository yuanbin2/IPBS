<script setup lang="ts">
/**
 * Markdown 文件导入的图片配套对话框。
 *
 * 纯 .md 导入只搬文本：图片引用（本机相对路径或防外链地址）在博客里无法显示。
 * 这里让用户把图片文件夹/文件一并提供，按相对路径或唯一文件名匹配（与 HTML
 * 导入共用 matchImageFile），匹配上的通过现有媒体接口上传后改写正文地址；
 * 远程引用可选由服务器抓取（复用 B-040 端点，上限 20 张）；未匹配的保留原
 * 地址并明确提示，不会静默丢弃或编造图片。
 */
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { findMarkdownImages, planMarkdownImageImport } from "../utils/imageFileMatching";
import type { ParsedMarkdown } from "../utils/parseMarkdownFile";

const props = defineProps<{
  visible: boolean;
  applying: boolean;
  parsed: ParsedMarkdown | null;
  filename: string;
}>();

const emit = defineEmits<{
  close: [];
  apply: [
    data: ParsedMarkdown,
    images: Array<{ reference: string; remote: boolean; alt: string; token: string; file: File }>,
    remoteImages: Array<{ reference: string; alt: string; token: string }>,
  ];
}>();

const MAX_IMAGES = 100;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

const localFiles = ref<File[]>([]);
const fetchRemote = ref(true);
const fileInputRef = ref<HTMLInputElement | null>(null);
const folderInputRef = ref<HTMLInputElement | null>(null);

const imageRefs = computed(() => (props.parsed ? findMarkdownImages(props.parsed.content) : []));

const plan = computed(() =>
  imageRefs.value.length
    ? planMarkdownImageImport(imageRefs.value, localFiles.value, { fetchRemote: fetchRemote.value })
    : { matched: [], remoteUnmatched: [], unmatched: [] },
);

type RefRow = {
  reference: string;
  remote: boolean;
  alt: string;
  status: "matched" | "fetch" | "keep";
  fileName: string;
};

const refRows = computed<RefRow[]>(() => {
  const matchedByRef = new Map(plan.value.matched.map((item) => [item.reference, item]));
  const fetchByRef = new Set(plan.value.remoteUnmatched.map((item) => item.reference));
  return imageRefs.value.map((ref) => {
    const matched = matchedByRef.get(ref.reference);
    if (matched) {
      return { reference: ref.reference, remote: ref.remote, alt: ref.alt, status: "matched", fileName: matched.file.name };
    }
    if (fetchByRef.has(ref.reference)) {
      return { reference: ref.reference, remote: ref.remote, alt: ref.alt, status: "fetch", fileName: "" };
    }
    return { reference: ref.reference, remote: ref.remote, alt: ref.alt, status: "keep", fileName: "" };
  });
});

const statusLabels: Record<RefRow["status"], string> = {
  matched: "已匹配本地图片",
  fetch: "由服务器抓取",
  keep: "保留原地址",
};

function addLocalFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  const incoming = [...(input.files ?? [])].filter((file) => /\.(png|jpe?g|gif|webp)$/i.test(file.name));
  input.value = "";
  if (!incoming.length) return;
  // 以文件名去重（文件夹与单选可能重叠），相对路径保留在 webkitRelativePath
  const byKey = new Map(localFiles.value.map((file) => [`${file.webkitRelativePath || file.name}`, file]));
  for (const file of incoming) byKey.set(`${file.webkitRelativePath || file.name}`, file);
  const merged = [...byKey.values()];
  if (merged.length > MAX_IMAGES) {
    ElMessage.error(`最多选择 ${MAX_IMAGES} 张图片`);
    return;
  }
  if (merged.some((file) => file.size > MAX_IMAGE_BYTES)) {
    ElMessage.error("单张图片不能超过 5 MiB");
    return;
  }
  localFiles.value = merged;
}

function clearLocalFiles() {
  localFiles.value = [];
}

function submit() {
  if (!props.parsed) return;
  // plan 阶段已把远程抓取限制在 20 张，超出的自动落入“保留原地址”
  emit("apply", props.parsed, plan.value.matched, plan.value.remoteUnmatched);
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="导入 Markdown：配套图片"
    width="640px"
    align-center
    :close-on-click-modal="false"
    @update:model-value="emit('close')"
  >
    <p class="md-import-intro">
      「{{ filename }}」里引用了 <strong>{{ imageRefs.length }}</strong> 张图片。
      博客无法直接显示你电脑里的路径或防外链地址——把图片文件（或整个图片文件夹）一并提供，
      匹配上的会自动上传并替换正文地址；远程地址可由服务器抓取；未匹配的保留原地址。
    </p>

    <div class="md-import-picker">
      <input ref="folderInputRef" type="file" multiple webkitdirectory aria-label="选择图片文件夹" @change="addLocalFiles" />
      <el-button size="small" @click="folderInputRef?.click()">选择图片文件夹</el-button>
      <input ref="fileInputRef" type="file" multiple accept="image/*" aria-label="选择图片文件" @change="addLocalFiles" />
      <el-button size="small" @click="fileInputRef?.click()">选择图片文件</el-button>
      <span v-if="localFiles.length" class="md-import-count">已选 {{ localFiles.length }} 张</span>
      <el-button v-if="localFiles.length" size="small" text type="danger" @click="clearLocalFiles">清空</el-button>
    </div>

    <div class="md-import-list">
      <div v-for="row in refRows" :key="row.reference" class="md-import-row">
        <span class="md-import-alt">{{ row.alt }}</span>
        <span class="md-import-ref" :title="row.reference">{{ row.reference }}</span>
        <span
          :class="['md-import-status', row.status]"
        >{{ statusLabels[row.status] }}<template v-if="row.fileName">：{{ row.fileName }}</template></span>
      </div>
    </div>

    <div class="md-import-summary">
      <span>
        上传 {{ plan.matched.length }} 张 · 抓取 {{ plan.remoteUnmatched.length }} 张 ·
        保留原地址 {{ plan.unmatched.length }} 张
      </span>
      <el-checkbox v-model="fetchRemote">远程图片由服务器抓取（最多 20 张）</el-checkbox>
    </div>

    <template #footer>
      <el-button @click="emit('close')">取消</el-button>
      <el-button type="primary" :loading="applying" :disabled="!imageRefs.length" @click="submit">
        导入文档与 {{ plan.matched.length + plan.remoteUnmatched.length }} 张图片
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.md-import-intro { margin: 0 0 10px; font-size: 13px; line-height: 1.7; color: var(--el-text-color-regular); }
.md-import-picker { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.md-import-picker input[type="file"] { display: none; }
.md-import-count { font-size: 12px; color: var(--el-text-color-secondary); }
.md-import-list { max-height: 240px; overflow: auto; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 6px 10px; }
.md-import-row { display: flex; align-items: baseline; gap: 10px; padding: 5px 0; font-size: 12px; border-bottom: 1px dashed var(--el-border-color-lighter); }
.md-import-row:last-child { border-bottom: 0; }
.md-import-alt { flex: 0 0 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--el-text-color-primary); }
.md-import-ref { flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--el-text-color-secondary); direction: rtl; text-align: left; }
.md-import-status { flex: 0 0 auto; }
.md-import-status.matched { color: var(--el-color-success); }
.md-import-status.fetch { color: var(--el-color-primary); }
.md-import-status.keep { color: var(--el-color-warning); }
.md-import-summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 10px; font-size: 12px; color: var(--el-text-color-regular); flex-wrap: wrap; }
</style>
