<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, shallowRef } from "vue";
import Vditor from "vditor";
import "vditor/dist/index.css";
import { isEditorFocused, shouldSyncExternalValue } from "../utils/editorSync";

const props = withDefaults(
  defineProps<{
    modelValue?: string;
    cacheId: string;
    mode?: "wysiwyg" | "ir" | "sv";
    visualOnly?: boolean;
    externalOutline?: boolean;
    height?: number | string;
    uploadHandler?: (files: File[]) => Promise<Array<{ url: string; alt?: string; title?: string }>>;
  }>(),
  {
    modelValue: "",
    cacheId: "blog-v2-unscoped",
    mode: "wysiwyg",
    visualOnly: false,
    externalOutline: false,
    height: 600,
  }
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
  uploadError: [message: string];
  ready: [];
}>();

const editorContainerRef = ref<HTMLDivElement>();
const vditorInstance = shallowRef<Vditor>();
let editorReady = false;

/** 行内公式按钮的图标：Σ 符号，与内置线性图标风格一致。 */
const FORMULA_ICON_SVG =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">' +
  '<path d="M17.7 5.6V3H6.2l6 9-6 9h11.5v-2.6h-6.6l4.6-6.4-4.6-6.4h6.6z"/></svg>';

onMounted(() => {
  if (!editorContainerRef.value) return;

  vditorInstance.value = new Vditor(editorContainerRef.value, {
    value: props.modelValue,
    mode: props.visualOnly ? "wysiwyg" : props.mode,
    height: props.height,
    lang: "zh_CN",
    placeholder: props.visualOnly ? "直接在这里写和修改正文；用上方按钮排版。" : "用 Markdown 写正文，可插入标题、列表、代码块、表格、链接、图片、流程图和公式。",
    theme: "classic",
    // lute（核心解析器）、KaTeX、mermaid、代码高亮都在运行时按 cdn 拉取；
    // 指向本站同源副本（scripts/sync-editor-assets.mjs 生成），不再依赖 unpkg。
    cdn: "/vendor/vditor",
    toolbar: [
      "emoji",
      "headings",
      "bold",
      "italic",
      "strike",
      "|",
      "line",
      "quote",
      "list",
      "ordered-list",
      "check",
      "outdent",
      "indent",
      "|",
      "code",
      "inline-code",
      {
        // 声明式前后缀：未选中时插入 $..$ 光标居中；选中文字则直接包成行内公式
        name: "insert-inline-formula",
        icon: FORMULA_ICON_SVG,
        tip: "行内公式",
        prefix: "$",
        suffix: "$",
      },
      "table",
      "insert-before",
      "insert-after",
      "|",
      ...(props.uploadHandler ? ["upload"] : []),
      "link",
      "|",
      "undo",
      "redo",
      "format",
      "|",
      ...(props.visualOnly ? [] : ["edit-mode"]),
      "fullscreen",
      ...(props.visualOnly ? [] : ["preview"]),
      ...(props.externalOutline ? [] : ["outline"]),
    ],
    toolbarConfig: {
      hide: false,
      pin: true,
    },
    outline: {
      enable: !props.externalOutline,
      position: "left",
    },
    cache: {
      // The page-level, owner-scoped draft record is authoritative. Vditor's
      // separate cache could race with async restoration and revive stale text.
      enable: false,
      id: props.cacheId,
    },
    upload: {
      max: 5 * 1024 * 1024,
      accept: "image/*",
      handler: props.uploadHandler
        ? async (files: File[]) => {
            try {
              const results = await props.uploadHandler!(Array.from(files));
              results.forEach((item) => {
                vditorInstance.value?.insertValue(`![${item.alt || "image"}](${item.url})`);
              });
            } catch (err) {
              console.error("Image upload failed:", err);
              emit("uploadError", err instanceof Error ? err.message : "图片上传失败");
            }
            return null;
          }
        : undefined,
    },
    input: (value: string) => {
      emit("update:modelValue", value);
    },
    after: () => {
      editorReady = true;
      // A draft can be restored while Vditor is still initializing. Apply the
      // latest prop only after its internal WYSIWYG state is ready.
      if (vditorInstance.value && vditorInstance.value.getValue() !== props.modelValue) {
        vditorInstance.value.setValue(props.modelValue);
      }
      emit("ready");
    },
  });
});

onBeforeUnmount(() => {
  editorReady = false;
  editorContainerRef.value?.removeEventListener("focusout", onEditorFocusOut);
  vditorInstance.value?.destroy();
  vditorInstance.value = undefined;
});

/**
 * 把外部值写回编辑器。仅在「值确实不同」且「编辑器未持有焦点」时执行：
 * setValue 会重建可编辑 DOM 并把光标丢回文档开头，用户输入过程中
 * （尤其 vditor 在空行回车等场景存在 Markdown 往返抖动）绝不能回写。
 */
function applyExternalValue() {
  const instance = vditorInstance.value;
  if (!instance || !editorReady) return;
  if (!shouldSyncExternalValue(props.modelValue, instance.getValue(), isEditorFocused(instance.vditor?.element))) {
    return;
  }
  instance.setValue(props.modelValue);
}

/** 焦点离开编辑器后补一次同步，保证聚焦期间被搁置的外部更新不丢失。 */
function onEditorFocusOut(event: FocusEvent) {
  const wrapper = editorContainerRef.value;
  if (!wrapper) return;
  const next = event.relatedTarget as Node | null;
  if (next && wrapper.contains(next)) return;
  applyExternalValue();
}

watch(
  () => props.modelValue,
  (newVal) => {
    if (!editorReady) return;
    if (vditorInstance.value && newVal !== vditorInstance.value.getValue()) {
      vditorInstance.value.setValue(newVal);
    }
  }
);

/* A/B 临时基线：旧逻辑（无焦点保护） */

onMounted(() => {
  editorContainerRef.value?.addEventListener("focusout", onEditorFocusOut);
});

// Expose instance methods for parent
defineExpose({
  getInstance: () => vditorInstance.value,
  isReady: () => editorReady,
  getValue: () => vditorInstance.value?.getValue() ?? "",
  getHTML: () => vditorInstance.value?.getHTML() ?? "",
  setValue: (value: string) => vditorInstance.value?.setValue(value),
});
</script>

<template>
  <div ref="editorContainerRef" class="vditor-editor-wrapper" />
</template>

<style scoped>
/* 组件根元素会被 Vditor 加上 .vditor 类，因此根样式直接写在 wrapper 上。
 * 关键：wrapper 不能 overflow:hidden——工具栏的 pin 依赖 position:sticky，
 * sticky 的约束盒是最近的 overflow 容器，hidden 会把吸附限制在这个
 * 从不滚动的盒子里导致失效。下侧圆角由内容区自行裁剪。 */
.vditor-editor-wrapper {
  border-radius: var(--radius-lg, 8px);
  overflow: visible;
  min-height: 480px;
}

:deep(.vditor-content) {
  border-radius: 0 0 var(--radius-lg, 8px) var(--radius-lg);
  overflow: hidden;
}

:deep(.vditor-toolbar) {
  background: var(--color-bg-secondary, #f6f8f7) !important;
  border-radius: var(--radius-lg, 8px) var(--radius-lg, 8px) 0 0;
  /* 编辑器随页面滚动时工具栏吸附在可视区顶部（编辑器仍在视口内即可见） */
  position: sticky;
  top: 0;
  z-index: 20;
}
</style>
