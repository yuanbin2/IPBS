<script setup lang="ts">
import { computed, ref } from "vue";
import { MagicStick } from "@element-plus/icons-vue";
import type {
  WritingAssistantMode,
  WritingAssistantRequest,
  WritingAssistantResult
} from "../types";

const props = defineProps<{
  authenticated: boolean;
  hasContent: boolean;
  loading: boolean;
  error: string;
  result: WritingAssistantResult | null;
}>();

const emit = defineEmits<{
  generate: [request: WritingAssistantRequest];
  apply: [strategy: "append" | "replace"];
  clear: [];
}>();

const open = ref(false);
const mode = ref<WritingAssistantMode>("task_list");
const instruction = ref("");

const modes: Array<{ value: WritingAssistantMode; label: string; hint: string }> = [
  { value: "task_list", label: "任务列表", hint: "把想法拆成可勾选的写作步骤" },
  { value: "outline", label: "文章大纲", hint: "生成标题层级与每节写作提示" },
  { value: "draft", label: "Markdown 草稿", hint: "根据要求和已有内容形成初稿" },
  { value: "improve", label: "润色全文", hint: "保留事实并优化现有 Markdown" }
];

const activeMode = computed(() => modes.find((item) => item.value === mode.value) ?? modes[0]);
const canGenerate = computed(() => props.authenticated && !props.loading);

function selectAndGenerate(nextMode: WritingAssistantMode) {
  mode.value = nextMode;
  emit("generate", { mode: nextMode, instruction: instruction.value.trim() });
}

function generate() {
  emit("generate", { mode: mode.value, instruction: instruction.value.trim() });
}
</script>

<template>
  <section class="writing-assistant" :class="{ open }">
    <button class="writing-assistant-toggle" type="button" @click="open = !open">
      <span class="writing-assistant-title">
        <el-icon><MagicStick /></el-icon>
        <strong>AI 写作助手</strong>
        <small>生成 Markdown，由你确认后写入</small>
      </span>
      <span>{{ open ? "收起" : "展开" }}</span>
    </button>

    <div v-if="open" class="writing-assistant-body">
      <el-alert
        v-if="!authenticated"
        title="登录后可使用写作助手"
        description="模型调用只在服务端进行，API Key 不会发送到浏览器。"
        type="info"
        :closable="false"
        show-icon
      />

      <div class="writing-assistant-modes">
        <button
          v-for="item in modes"
          :key="item.value"
          type="button"
          :class="{ active: mode === item.value }"
          :disabled="!canGenerate || (item.value === 'improve' && !hasContent)"
          @click="selectAndGenerate(item.value)"
        >
          <strong>{{ item.label }}</strong>
          <span>{{ item.hint }}</span>
        </button>
      </div>

      <div class="writing-assistant-prompt">
        <el-input
          v-model="instruction"
          type="textarea"
          :rows="2"
          resize="vertical"
          maxlength="2000"
          show-word-limit
          placeholder="补充你的要求，例如：面向初学者，重点讲清楚实现步骤，并保留待补充的数据位置。"
          @keydown.ctrl.enter.prevent="generate"
          @keydown.meta.enter.prevent="generate"
        />
        <div class="writing-assistant-submit">
          <span>{{ activeMode.hint }} · Ctrl / ⌘ + Enter</span>
          <el-button type="primary" :icon="MagicStick" :loading="loading" :disabled="!canGenerate" @click="generate">
            生成{{ activeMode.label }}
          </el-button>
        </div>
      </div>

      <p v-if="error" class="writing-assistant-error">{{ error }}</p>

      <div v-if="result" class="writing-assistant-result">
        <header>
          <div>
            <strong>生成结果</strong>
            <span>{{ result.model }} · {{ result.apiKeySource === "dedicated" ? "专用 Key" : "沿用现有 Key" }}</span>
          </div>
          <el-button text @click="emit('clear')">清除</el-button>
        </header>
        <el-input :model-value="result.markdown" type="textarea" :rows="10" resize="vertical" readonly />
        <footer>
          <span>结果不会自动发布，请写入编辑器后继续修改。</span>
          <div>
            <el-button @click="emit('apply', 'replace')">替换正文</el-button>
            <el-button type="primary" @click="emit('apply', 'append')">追加到正文</el-button>
          </div>
        </footer>
      </div>
    </div>
  </section>
</template>
