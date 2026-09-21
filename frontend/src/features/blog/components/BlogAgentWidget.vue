<script setup lang="ts">
import { ChatDotRound } from "@element-plus/icons-vue";
import type { BlogAgentChatMessage } from "../types";

defineProps<{
  open: boolean;
  input: string;
  loading: boolean;
  messages: BlogAgentChatMessage[];
  suggestions: string[];
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
  "update:input": [value: string];
  send: [prompt?: string];
  keydown: [event: KeyboardEvent];
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

      <div class="blog-agent-messages">
        <article
          v-for="(message, index) in messages"
          :key="index"
          class="blog-agent-message"
          :class="[message.role, { blocked: message.blocked, pending: message.pending }]"
        >
          <p>{{ message.content }}</p>
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
