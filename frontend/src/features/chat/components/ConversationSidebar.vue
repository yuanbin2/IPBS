<script setup lang="ts">
import { Cpu, Plus, Refresh, Search } from "@element-plus/icons-vue";
import type { Conversation, TokenUsage } from "../types";

defineProps<{
  historySearch: string;
  conversations: Conversation[];
  currentConversationId: number | null;
  conversationsLoading: boolean;
  chatLoading: boolean;
  latestTokenUsage: TokenUsage | null;
  agents: Array<{ name: string; detail: string }>;
  suggestions: string[];
}>();

const emit = defineEmits<{
  "update:historySearch": [value: string];
  refresh: [];
  create: [];
  select: [conversation: Conversation];
  suggest: [value: string];
}>();
</script>

<template>
  <aside class="agent-panel">
    <div class="panel-actions">
      <h2><el-icon><Cpu /></el-icon> 会话历史</h2>
      <div>
        <el-button :icon="Refresh" circle :loading="conversationsLoading" @click="emit('refresh')" />
        <el-button :icon="Plus" circle @click="emit('create')" />
      </div>
    </div>

    <el-input
      :model-value="historySearch"
      class="history-search"
      clearable
      :prefix-icon="Search"
      placeholder="搜索历史消息"
      @update:model-value="emit('update:historySearch', String($event))"
      @keyup.enter="emit('refresh')"
      @clear="emit('refresh')"
    />

    <section class="token-card">
      <span>本轮 Token</span>
      <strong v-if="latestTokenUsage">{{ latestTokenUsage.total_tokens }}</strong>
      <strong v-else-if="chatLoading">统计中</strong>
      <strong v-else>0</strong>
      <small v-if="latestTokenUsage">
        prompt {{ latestTokenUsage.prompt_tokens }} / completion {{ latestTokenUsage.completion_tokens }}
      </small>
      <small v-else>等待下一次回答</small>
    </section>

    <section class="agent-roster">
      <h3>Multi-Agent</h3>
      <article v-for="agent in agents" :key="agent.name">
        <strong>{{ agent.name }}</strong><span>{{ agent.detail }}</span>
      </article>
    </section>

    <div class="history-list">
      <button
        v-for="conversation in conversations"
        :key="conversation.id"
        type="button"
        :class="{ active: conversation.id === currentConversationId }"
        @click="emit('select', conversation)"
      >
        {{ conversation.title || `会话 ${conversation.id}` }}
      </button>
    </div>

    <ol class="graph-flow">
      <li>query_analyzer</li><li>retrieve</li><li>grade_documents</li>
      <li>rewrite_query</li><li>generate</li><li>cite_sources</li>
    </ol>

    <div class="suggestions">
      <button v-for="item in suggestions" :key="item" type="button" @click="emit('suggest', item)">
        {{ item }}
      </button>
    </div>
  </aside>
</template>
