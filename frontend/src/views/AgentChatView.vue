<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { Back, ChatDotRound, Cpu, Plus, Promotion, Refresh, Search } from "@element-plus/icons-vue";
import { RouterLink } from "vue-router";

const MESSAGE_PAGE_SIZE = 30;

interface ToolCall {
  name: string;
  input: string;
  output: string;
}

interface SourceCitation {
  document_id: number;
  document_title: string;
  chunk_id: number;
  chunk_index: number;
  score: number;
  content: string;
}

interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

interface ChatMessage {
  id?: number;
  role: "user" | "agent";
  content: string;
  toolCalls?: ToolCall[];
  sources?: SourceCitation[];
  trace?: string[];
  tokenUsage?: TokenUsage;
  pending?: boolean;
}

interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  matched_message_id?: number;
}

interface ConversationDetail extends Conversation {
  messages: Array<{
    id: number;
    role: "user" | "agent";
    content: string;
    tool_calls: ToolCall[];
    sources: SourceCitation[];
    trace: string[];
    token_usage: TokenUsage;
  }>;
  has_more_before: boolean;
  has_more_after: boolean;
}

const emptyUsage: TokenUsage = {
  prompt_tokens: 0,
  completion_tokens: 0,
  total_tokens: 0
};

const welcomeMessage: ChatMessage = {
  role: "agent",
  content: "我现在是一个 LangGraph 状态图 Agent。你可以普通提问，也可以让我检索项目文档、读取当前用户资料或做简单计算。",
  tokenUsage: emptyUsage
};

const input = ref("帮我检索 LangGraph 和 RAG 的关系");
const historySearch = ref("");
const loading = ref(false);
const conversationsLoading = ref(false);
const messagesLoading = ref(false);
const hasMoreBefore = ref(false);
const currentConversationId = ref<number | null>(null);
const conversations = ref<Conversation[]>([]);
const messages = ref<ChatMessage[]>([welcomeMessage]);
const latestTokenUsage = ref<TokenUsage | null>(null);
const conversationScroller = ref<HTMLElement | null>(null);

const suggestions = ["什么是 LangGraph？", "帮我计算 12 * 8", "检索 MCP 工具接入"];
const canSend = computed(() => input.value.trim().length > 0 && !loading.value);

onMounted(() => {
  void loadConversations();
});

async function loadConversations() {
  conversationsLoading.value = true;
  try {
    const params = new URLSearchParams();
    if (historySearch.value.trim()) {
      params.set("q", historySearch.value.trim());
    }
    const query = params.toString();
    const response = await fetch(`/api/agent/conversations/${query ? `?${query}` : ""}`);
    conversations.value = await response.json();
    if (!currentConversationId.value && conversations.value.length > 0) {
      await loadConversation(conversations.value[0]);
    }
  } finally {
    conversationsLoading.value = false;
  }
}

async function loadConversation(conversation: Conversation) {
  const params = new URLSearchParams({ limit: String(MESSAGE_PAGE_SIZE) });
  if (conversation.matched_message_id) {
    params.set("anchor", String(conversation.matched_message_id));
  }
  const response = await fetch(`/api/agent/conversations/${conversation.id}/?${params.toString()}`);
  const detail: ConversationDetail = await response.json();
  currentConversationId.value = detail.id;
  messages.value = detail.messages.map(mapApiMessage);
  hasMoreBefore.value = detail.has_more_before;
  latestTokenUsage.value = [...messages.value].reverse().find((message) => message.tokenUsage)?.tokenUsage ?? null;
  await nextTick();
  if (conversation.matched_message_id) {
    scrollToMessage(conversation.matched_message_id);
  } else {
    scrollToBottom();
  }
}

async function loadOlderMessages() {
  if (!currentConversationId.value || !hasMoreBefore.value || messagesLoading.value) return;
  const firstPersistedMessage = messages.value.find((message) => message.id);
  if (!firstPersistedMessage?.id) return;

  const scroller = conversationScroller.value;
  const previousHeight = scroller?.scrollHeight ?? 0;
  messagesLoading.value = true;

  try {
    const params = new URLSearchParams({
      limit: String(MESSAGE_PAGE_SIZE),
      before: String(firstPersistedMessage.id)
    });
    const response = await fetch(`/api/agent/conversations/${currentConversationId.value}/?${params.toString()}`);
    const detail: ConversationDetail = await response.json();
    const olderMessages = detail.messages.map(mapApiMessage);
    messages.value = [...olderMessages, ...messages.value];
    hasMoreBefore.value = detail.has_more_before;
    await nextTick();
    if (scroller) {
      scroller.scrollTop = scroller.scrollHeight - previousHeight;
    }
  } finally {
    messagesLoading.value = false;
  }
}

function handleConversationScroll() {
  if ((conversationScroller.value?.scrollTop ?? 0) < 40) {
    void loadOlderMessages();
  }
}

function mapApiMessage(message: ConversationDetail["messages"][number]): ChatMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    toolCalls: message.tool_calls,
    sources: message.sources,
    trace: message.trace,
    tokenUsage: message.token_usage
  };
}

function scrollToBottom() {
  const scroller = conversationScroller.value;
  if (scroller) {
    scroller.scrollTop = scroller.scrollHeight;
  }
}

function scrollToMessage(messageId: number) {
  const element = document.querySelector(`[data-message-id="${messageId}"]`);
  element?.scrollIntoView({ block: "center" });
}

function startNewConversation() {
  currentConversationId.value = null;
  hasMoreBefore.value = false;
  messages.value = [welcomeMessage];
  latestTokenUsage.value = null;
  input.value = "";
}

async function sendMessage(prompt?: string) {
  const message = (prompt ?? input.value).trim();
  if (!message || loading.value) return;

  messages.value.push({ role: "user", content: message });
  const pendingMessage: ChatMessage = {
    role: "agent",
    content: "正在生成回答，token 消耗统计中...",
    tokenUsage: emptyUsage,
    pending: true
  };
  messages.value.push(pendingMessage);
  latestTokenUsage.value = null;
  input.value = "";
  loading.value = true;
  await nextTick();
  scrollToBottom();

  try {
    const response = await fetch("/api/agent/chat/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        conversation_id: currentConversationId.value
      })
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail ?? "Agent request failed");
    }

    currentConversationId.value = payload.conversation.id;
    Object.assign(pendingMessage, {
      content: payload.answer,
      toolCalls: payload.tool_calls,
      sources: payload.sources,
      trace: payload.trace,
      tokenUsage: payload.token_usage,
      pending: false
    });
    latestTokenUsage.value = payload.token_usage;
    await loadConversations();
    await nextTick();
    scrollToBottom();
  } catch (error) {
    Object.assign(pendingMessage, {
      content: `请求失败：${error instanceof Error ? error.message : "未知错误"}`,
      pending: false
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

function isRetrievalTool(call: ToolCall) {
  return call.name === "knowledge_search" || call.name === "blog_search";
}

function toolPanelTitle(call: ToolCall) {
  if (isRetrievalTool(call)) {
    return "检索到的相关内容";
  }
  if (call.name === "calculator") {
    return "计算工具结果";
  }
  if (call.name === "current_user_profile") {
    return "用户资料上下文";
  }
  return call.name;
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
          <p class="eyebrow">LangGraph StateGraph Workflow</p>
          <h1>Agent 聊天页面</h1>
        </div>
        <RouterLink to="/">
          <el-button :icon="Back">返回概览</el-button>
        </RouterLink>
      </header>

      <section class="chat-layout">
        <div ref="conversationScroller" class="conversation" @scroll="handleConversationScroll">
          <button v-if="hasMoreBefore" type="button" class="load-older" :disabled="messagesLoading" @click="loadOlderMessages">
            {{ messagesLoading ? "加载中..." : "加载更早消息" }}
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
              <p>{{ message.content }}</p>
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
                    <span class="retrieval-title">
                      <strong>{{ toolPanelTitle(call) }}</strong>
                      <small>{{ call.name }}</small>
                    </span>
                  </template>
                  <section class="retrieval-panel" :class="{ highlight: isRetrievalTool(call) }">
                    <div class="retrieval-query">
                      <span>查询</span>
                      <p>{{ call.input || "无输入参数" }}</p>
                    </div>
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
          </article>
        </div>

        <aside class="agent-panel">
          <div class="panel-actions">
            <h2><el-icon><Cpu /></el-icon> 会话历史</h2>
            <div>
              <el-button :icon="Refresh" circle :loading="conversationsLoading" @click="loadConversations" />
              <el-button :icon="Plus" circle @click="startNewConversation" />
            </div>
          </div>

          <el-input
            v-model="historySearch"
            class="history-search"
            clearable
            :prefix-icon="Search"
            placeholder="搜索历史消息"
            @keyup.enter="loadConversations"
            @clear="loadConversations"
          />

          <section class="token-card">
            <span>本轮 Token</span>
            <strong v-if="latestTokenUsage">{{ latestTokenUsage.total_tokens }}</strong>
            <strong v-else-if="loading">统计中</strong>
            <strong v-else>0</strong>
            <small v-if="latestTokenUsage">
              prompt {{ latestTokenUsage.prompt_tokens }} / completion {{ latestTokenUsage.completion_tokens }}
            </small>
            <small v-else>等待下一次回答</small>
          </section>

          <div class="history-list">
            <button
              v-for="conversation in conversations"
              :key="conversation.id"
              type="button"
              :class="{ active: conversation.id === currentConversationId }"
              @click="loadConversation(conversation)"
            >
              {{ conversation.title || `会话 ${conversation.id}` }}
            </button>
          </div>

          <ol class="graph-flow">
            <li>query_analyzer</li>
            <li>retrieve</li>
            <li>grade_documents</li>
            <li>rewrite_query</li>
            <li>generate</li>
            <li>cite_sources</li>
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
