<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, shallowRef } from "vue";
import Vditor from "vditor";
import "vditor/dist/index.css";

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
let isInternalUpdate = false;
let editorReady = false;

onMounted(() => {
  if (!editorContainerRef.value) return;

  vditorInstance.value = new Vditor(editorContainerRef.value, {
    value: props.modelValue,
    mode: props.visualOnly ? "wysiwyg" : props.mode,
    height: props.height,
    lang: "zh_CN",
    placeholder: props.visualOnly ? "直接在这里写和修改正文；用上方按钮排版。" : "用 Markdown 写正文，可插入标题、列表、代码块、表格、链接、图片、流程图和公式。",
    theme: "classic",
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
      "|",
      "code",
      "inline-code",
      "table",
      "|",
      ...(props.uploadHandler ? ["upload"] : []),
      "link",
      "|",
      "undo",
      "redo",
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
      isInternalUpdate = true;
      emit("update:modelValue", value);
      isInternalUpdate = false;
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
  vditorInstance.value?.destroy();
  vditorInstance.value = undefined;
});

watch(
  () => props.modelValue,
  (newVal) => {
    if (isInternalUpdate || !editorReady) return;
    if (vditorInstance.value && newVal !== vditorInstance.value.getValue()) {
      vditorInstance.value.setValue(newVal);
    }
  }
);

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
.vditor-editor-wrapper {
  border-radius: var(--radius-lg, 8px);
  overflow: hidden;
}

:deep(.vditor) {
  border: 1px solid var(--color-border, #dce4e1) !important;
  border-radius: var(--radius-lg, 8px);
}

:deep(.vditor-toolbar) {
  background: var(--color-bg-secondary, #f6f8f7) !important;
}
</style>
