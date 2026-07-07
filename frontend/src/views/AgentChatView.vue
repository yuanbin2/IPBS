<script setup lang="ts">
import { computed, ref } from "vue";
import { Back, ChatDotRound, Cpu, Promotion } from "@element-plus/icons-vue";
import { RouterLink } from "vue-router";

interface ToolCall {
  name: string;
  input: string;
  output: string;
}

interface ChatMessage {
  role: "user" | "agent";
  content: string;
  toolCalls?: ToolCall[];
  trace?: string[];
}

const input = ref("帮我检索 LangGraph 和 RAG 的关系");
const loading = ref(false);
const messages = ref<ChatMessage[]>([
  {
    role: "agent",
    content: "我已经接入 3 个工具：博客文章检索、当前用户资料、简单计算器。你可以直接问我。"
  }
]);

const suggestions = ["帮我计算 12 * 8", "当前用户是谁", "检索 MCP 工具接入"];
const canSend = computed(() => input.value.trim().length > 0 && !loading.value);

async function sendMessage(prompt?: string) {
  const message = (prompt ?? input.value).trim();
  if (!message || loading.value) return;

  messages.value.push({ role: "user", content: message });
  input.value = "";
  loading.value = true;

  try {
    const response = await fetch("/api/agent/chat/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message })
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail ?? "Agent request failed");
    }

    messages.value.push({
      role: "agent",
      content: payload.answer,
      toolCalls: payload.tool_calls,
      trace: payload.trace
    });
  } catch (error) {
    messages.value.push({
      role: "agent",
      content: `请求失败：${error instanceof Error ? error.message : "未知错误"}`
    });
  } finally {
    loading.value = false;
  }
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
    return;
  }

  event.preventDefault();
  void sendMessage();
}
</script>

<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">Knowledge Agent</div>
      <nav class="nav">
        <RouterLink to="/">概览</RouterLink>
        <a>博客</a>
        <a>知识库</a>
        <RouterLink class="active" to="/chat">对话</RouterLink>
        <a>评估</a>
      </nav>
    </aside>

    <section class="workspace chat-workspace">
      <header class="topbar">
        <div>
          <p class="eyebrow">LangChain Agent + Tool Calling</p>
          <h1>Agent 聊天页面</h1>
        </div>
        <RouterLink to="/">
          <el-button :icon="Back">返回概览</el-button>
        </RouterLink>
      </header>

      <section class="chat-layout">
        <div class="conversation">
          <article
            v-for="(message, index) in messages"
            :key="index"
            class="message"
            :class="message.role"
          >
            <div class="message-icon">
              <el-icon><ChatDotRound v-if="message.role === 'agent'" /><Promotion v-else /></el-icon>
            </div>
            <div class="message-body">
              <p>{{ message.content }}</p>
              <div v-if="message.toolCalls?.length" class="tool-list">
                <section v-for="call in message.toolCalls" :key="call.name + call.input">
                  <strong>{{ call.name }}</strong>
                  <span>{{ call.input }}</span>
                  <pre>{{ call.output }}</pre>
                </section>
              </div>
            </div>
          </article>
        </div>

        <aside class="agent-panel">
          <h2><el-icon><Cpu /></el-icon> 工具轨迹</h2>
          <ol>
            <li>用户输入</li>
            <li>Agent 判断需要的工具</li>
            <li>调用工具并收集结果</li>
            <li>返回最终回答</li>
          </ol>
          <div class="suggestions">
            <button v-for="item in suggestions" :key="item" type="button" @click="sendMessage(item)">
              {{ item }}
            </button>
          </div>
        </aside>
      </section>

      <form class="composer" @submit.prevent="sendMessage()">
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          resize="none"
          placeholder="向 Agent 提问，例如：帮我计算 12 * 8"
          @keydown="handleComposerKeydown"
        />
        <el-button type="primary" native-type="submit" :loading="loading" :disabled="!canSend">
          发送
        </el-button>
      </form>
    </section>
  </main>
</template>

