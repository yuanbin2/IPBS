<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, shallowRef } from "vue";
import Vditor from "vditor";
import "vditor/dist/index.css";

const props = withDefaults(
  defineProps<{
    modelValue?: string;
    mode?: "wysiwyg" | "ir" | "sv";
    height?: number;
    uploadHandler?: (files: File[]) => Promise<Array<{ url: string; alt?: string; title?: string }>>;
  }>(),
  {
    modelValue: "",
    mode: "wysiwyg",
    height: 600,
  }
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const editorContainerRef = ref<HTMLDivElement>();
const vditorInstance = shallowRef<Vditor>();
let isInternalUpdate = false;

onMounted(() => {
  if (!editorContainerRef.value) return;

  vditorInstance.value = new Vditor(editorContainerRef.value, {
    value: props.modelValue,
    mode: props.mode,
    height: props.height,
    lang: "zh_CN",
    placeholder: "用 Markdown 写正文，可插入标题、列表、代码块、表格、链接、图片、流程图和公式。",
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
      "upload",
      "link",
      "|",
      "undo",
      "redo",
      "|",
      "edit-mode",
      "fullscreen",
      "preview",
      "outline",
    ],
    toolbarConfig: {
      hide: false,
      pin: true,
    },
    outline: {
      enable: true,
      position: "left",
    },
    cache: {
      enable: true,
      id: "blog-vditor-cache",
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
      // Editor ready
    },
  });
});

onBeforeUnmount(() => {
  vditorInstance.value?.destroy();
});

watch(
  () => props.modelValue,
  (newVal) => {
    if (isInternalUpdate) return;
    if (vditorInstance.value && newVal !== vditorInstance.value.getValue()) {
      vditorInstance.value.setValue(newVal);
    }
  }
);

// Expose instance methods for parent
defineExpose({
  getInstance: () => vditorInstance.value,
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
  border: 1px solid var(--color-border, #dcdfe6) !important;
  border-radius: var(--radius-lg, 8px);
}

:deep(.vditor-toolbar) {
  background: var(--color-bg-secondary, #fafafa) !important;
}
</style>