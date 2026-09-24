<script setup lang="ts">
import { ChatDotRound, CopyDocument, Promotion } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { MdPreview } from "md-editor-v3";
import "md-editor-v3/lib/style.css";
import ChatThinkingPanel from "./ChatThinkingPanel.vue";
import type { ChatMessage, ToolCall } from "../types";
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{
  messages: ChatMessage[];
  hasMoreBefore: boolean;
  loadingOlder: boolean;
}>();

defineEmits<{ loadOlder: []; scroll: [event: Event] }>();

// 超长回答收成固定高度窗口，避免一条长回答把会话流撑得很长。
const ANSWER_WINDOW_HEIGHT = 380;
const OVERFLOW_TOLERANCE = 8;

const clampableKeys = ref<Set<string>>(new Set());
const expandedKeys = ref<Set<string>>(new Set());
const listRef = ref<HTMLElement | null>(null);
let observer: ResizeObserver | null = null;

function answerKey(message: ChatMessage, index: number): string {
  return message.id ? String(message.id) : `local-${index}`;
}

function isClampable(message: ChatMessage, index: number): boolean {
  return !message.pending && clampableKeys.value.has(answerKey(message, index));
}

function isExpanded(message: ChatMessage, index: number): boolean {
  return expandedKeys.value.has(answerKey(message, index));
}

function toggleExpanded(message: ChatMessage, index: number): void {
  const key = answerKey(message, index);
  const next = new Set(expandedKeys.value);
  if (next.has(key)) {
    next.delete(key);
  } else {
    next.add(key);
  }
  expandedKeys.value = next;
}

function measureEntry(target: HTMLElement): void {
  const key = target.dataset.answerKey;
  if (!key) return;
  const next = new Set(clampableKeys.value);
  if (target.scrollHeight > ANSWER_WINDOW_HEIGHT + OVERFLOW_TOLERANCE) {
    next.add(key);
  } else {
    next.delete(key);
  }
  clampableKeys.value = next;
}

function attachObservers(): void {
  const root = listRef.value;
  if (!root || !observer) return;
  root.querySelectorAll<HTMLElement>(".answer-inner").forEach((element) => observer?.observe(element));
}

onMounted(() => {
  observer = new ResizeObserver((entries) => {
    entries.forEach((entry) => measureEntry(entry.target as HTMLElement));
  });
  nextTick(attachObservers);
});

watch(
  () => props.messages.length,
  () => nextTick(attachObservers),
  { flush: "post" }
);

onBeforeUnmount(() => {
  observer?.disconnect();
  observer = null;
});

function isRetrievalTool(call: ToolCall) {
  return ["knowledge_search", "blog_search", "blog_agent_search"].includes(call.name);
}

function toolPanelTitle(call: ToolCall) {
  if (isRetrievalTool(call)) return "检索到的相关内容";
  const titles: Record<string, string> = {
    calculator: "计算工具结果",
    current_user_profile: "用户资料上下文",
    safe_sql_analytics: "SQL Analysis Agent 统计结果",
    writing_outline: "Writing Agent 写作结构",
    answer_review: "Review Agent 审查结果",
    admin_approval: "Admin Approval Agent 审批建议"
  };
  if (call.name.startsWith("mcp:")) return "MCP 工具调用结果";
  return titles[call.name] ?? call.name;
}

async function copyMessage(content: string) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(content);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = content;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      const copied = document.execCommand("copy");
      textarea.remove();
      if (!copied) throw new Error("copy failed");
    }
    ElMessage.success("消息内容已复制");
  } catch {
    ElMessage.error("复制失败，请手动选择内容");
  }
}
</script>

<template>
  <div ref="listRef" class="conversation" @scroll="$emit('scroll', $event)">
    <button
      v-if="hasMoreBefore"
      type="button"
      class="load-older"
      :disabled="loadingOlder"
      @click="$emit('loadOlder')"
    >
      {{ loadingOlder ? "加载中..." : "加载更早消息" }}
    </button>
    <article
      v-for="(message, index) in messages"
      :key="message.id ?? index"
      class="message"
      :class="message.role"
      :data-message-id="message.id"
    >
      <div class="message-icon">
        <el-icon><ChatDotRound v-if="message.role === 'agent'" /><Promotion v-else /></el-icon>
      </div>
      <div class="message-body" :class="{ pending: message.pending }">
        <button
          v-if="!message.pending"
          class="message-copy"
          type="button"
          :aria-label="message.role === 'user' ? '复制问题' : '复制回答'"
          :title="message.role === 'user' ? '复制问题' : '复制回答'"
          @click="copyMessage(message.content)"
        >
          <el-icon><CopyDocument /></el-icon>
        </button>
        <div
          class="answer-window"
          :class="{ clamped: isClampable(message, index) && !isExpanded(message, index) }"
        >
          <div class="answer-inner" :data-answer-key="answerKey(message, index)">
            <MdPreview
              v-if="message.role === 'agent'"
              :model-value="message.content"
              language="zh-CN"
              preview-theme="github"
              code-theme="github"
              :show-code-row-number="false"
              class="agent-md-preview"
            />
            <p v-else>{{ message.content }}</p>
            <ChatThinkingPanel
              v-if="message.role === 'agent' && (message.streamingTrace?.length || message.trace?.length)"
              :traces="message.streamingTrace?.length ? message.streamingTrace : (message.trace ?? [])"
              :is-streaming="!!message.pending"
              :is-complete="!message.pending"
            />
            <section v-if="message.role === 'agent' && message.supervisor" class="supervisor-card">
              <header>
                <strong>{{ message.supervisor.display_name }}</strong>
                <span v-if="message.supervisor.confidence">confidence {{ message.supervisor.confidence.toFixed(2) }}</span>
              </header>
              <p>{{ message.supervisor.reason }}</p>
              <small>{{ message.supervisor.handoff }}</small>
            </section>
            <div v-if="message.role === 'agent' && message.tokenUsage" class="token-usage">
              <span>Prompt {{ message.tokenUsage.prompt_tokens }}</span>
              <span>Completion {{ message.tokenUsage.completion_tokens }}</span>
              <strong>Total {{ message.tokenUsage.total_tokens }}</strong>
            </div>
            <section v-if="message.sources?.length" class="source-list">
              <header>引用来源</header>
              <article v-for="(source, sourceIndex) in message.sources" :key="source.chunk_id">
                <div>
                  <strong>[{{ sourceIndex + 1 }}] {{ source.document_title }}</strong>
                  <span>score {{ source.score.toFixed(3) }} / chunk {{ source.chunk_index }}</span>
                </div>
                <p>{{ source.content }}</p>
              </article>
            </section>
            <el-collapse v-if="message.toolCalls?.length" class="retrieval-collapse">
              <el-collapse-item
                v-for="(call, callIndex) in message.toolCalls"
                :key="call.name + call.input + callIndex"
                :name="`${message.id ?? index}-${callIndex}`"
              >
                <template #title>
                  <span class="retrieval-title"><strong>{{ toolPanelTitle(call) }}</strong><small>{{ call.name }}</small></span>
                </template>
                <section class="retrieval-panel" :class="{ highlight: isRetrievalTool(call) }">
                  <div class="retrieval-query"><span>查询</span><p>{{ call.input || "无输入参数" }}</p></div>
                  <div class="retrieval-content">
                    <span>{{ isRetrievalTool(call) ? "数据库 / 知识库上下文" : "工具输出" }}</span>
                    <pre>{{ call.output }}</pre>
                  </div>
                </section>
              </el-collapse-item>
            </el-collapse>
            <div v-if="message.trace?.length" class="trace-list">
              <span v-for="item in message.trace" :key="item">{{ item }}</span>
            </div>
          </div>
        </div>
        <button
          v-if="isClampable(message, index)"
          type="button"
          class="answer-toggle"
          @click="toggleExpanded(message, index)"
        >
          {{ isExpanded(message, index) ? "收起" : "展开全文" }}
        </button>
      </div>
    </article>
  </div>
</template>
