<script setup lang="ts">
import { ChatDotRound } from "@element-plus/icons-vue";
import type { BlogAgentChatMessage } from "../types";

defineProps<{
  open: boolean;
  input: string;
  loading: boolean;
  messages: BlogAgentChatMessage[];
  suggestions: string[];
  source: "legacy" | "ragagent";
  /** 是否还有更早的历史消息（决定「加载更早消息」按钮显隐）。 */
  hasMoreBefore: boolean;
  /** 更早历史消息加载中（防重入 + 按钮态）。 */
  loadingOlder: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
  "update:input": [value: string];
  "update:source": [value: "legacy" | "ragagent"];
  send: [prompt?: string];
  keydown: [event: KeyboardEvent];
  "load-older": [];
}>();
</script>

<template>
  <section class="blog-agent-widget" :class="{ open }">
    <button class="blog-agent-fab" type="button" @click="emit('update:open', !open)">
      <el-icon><ChatDotRound /></el-icon>
      <span>问博客智能体</span>
    </button>

    <section v-if="open" class="blog-agent-panel">
      <header>
        <div><strong>博客智能体</strong><small>仅回答公开博客、简历和 README 内容</small></div>
        <button type="button" @click="emit('update:open', false)">×</button>
      </header>

      <div class="blog-agent-source-toggle" role="group" aria-label="知识来源切换">
        <button
          type="button"
          :class="{ active: source === 'legacy' }"
          title="使用博客站内知识库检索"
          @click="emit('update:source', 'legacy')"
        >
          站内检索
        </button>
        <button
          type="button"
          :class="{ active: source === 'ragagent' }"
          title="使用 RAG-Agent 服务检索本站隔离知识（需本机 18080 服务在线）"
          @click="emit('update:source', 'ragagent')"
        >
          RAG-Agent
        </button>
      </div>

      <div class="blog-agent-messages">
        <button
          v-if="hasMoreBefore"
          type="button"
          class="blog-agent-load-older"
          :disabled="loadingOlder"
          @click="emit('load-older')"
        >
          {{ loadingOlder ? "加载中…" : "加载更早消息" }}
        </button>
        <article
          v-for="(message, index) in messages"
          :key="message.id ?? `local-${index}`"
          class="blog-agent-message"
          :class="[message.role, { blocked: message.blocked, pending: message.pending }]"
        >
          <p>{{ message.content }}</p>
          <div v-if="message.degraded" class="blog-agent-degraded" role="status">
            ⚠ RAG-Agent 未响应，本次回答已自动回退站内检索{{ message.degraded_reason ? `（${message.degraded_reason}）` : "" }}
          </div>
          <div v-else-if="message.rag_source_effective === 'ragagent'" class="blog-agent-source-badge">来源：RAG-Agent</div>
          <div v-if="message.sources?.length" class="blog-agent-sources">
            <span v-for="(source, sourceIndex) in message.sources" :key="source.title + sourceIndex">
              [{{ sourceIndex + 1 }}] {{ source.title }}
            </span>
          </div>
        </article>
      </div>

      <div class="blog-agent-suggestions">
        <button v-for="item in suggestions" :key="item" type="button" @click="emit('send', item)">
          {{ item }}
        </button>
      </div>

      <form class="blog-agent-composer" @submit.prevent="emit('send')">
        <el-input
          :model-value="input"
          type="textarea"
          :rows="2"
          resize="none"
          placeholder="问公开博客内容，例如：这个项目架构是什么？"
          @update:model-value="emit('update:input', String($event))"
          @keydown="emit('keydown', $event)"
        />
        <el-button type="primary" native-type="submit" :loading="loading">发送</el-button>
      </form>
    </section>
  </section>
</template>
