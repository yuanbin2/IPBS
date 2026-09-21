<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from "vue";
import { Back } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { RouterLink } from "vue-router";
import { useAuthStore } from "../stores/auth";
import ChatMessageList from "../features/chat/components/ChatMessageList.vue";
import ConversationSidebar from "../features/chat/components/ConversationSidebar.vue";
import ChatComposer from "../features/chat/components/ChatComposer.vue";
import ChatApprovalDialog from "../features/chat/components/ChatApprovalDialog.vue";
import type {
  ApprovalRequest,
  ChatMessage,
  Conversation,
  ConversationDetail,
  SupervisorDecision,
  TokenUsage
} from "../features/chat/types";

const MESSAGE_PAGE_SIZE = 30;
const auth = useAuthStore();

const emptyUsage: TokenUsage = {
  prompt_tokens: 0,
  completion_tokens: 0,
  total_tokens: 0
};

const welcomeMessage: ChatMessage = {
  role: "agent",
  content: "我现在是一个 LangGraph 多智能体助手。你可以普通提问，也可以直接让我调用 MCP：搜索本地文件、查看 Git、搜索网页或统计系统数据。",
  tokenUsage: emptyUsage
};


const input = ref("帮我检索 LangGraph 和 RAG 的关系");
const historySearch = ref("");
const loading = ref(false);
const internetEnabled = ref(false);
const conversationsLoading = ref(false);
const messagesLoading = ref(false);
const hasMoreBefore = ref(false);
const currentConversationId = ref<number | null>(null);
const conversations = ref<Conversation[]>([]);
const messages = ref<ChatMessage[]>([welcomeMessage]);
const latestTokenUsage = ref<TokenUsage | null>(null);
const getConversationScroller = () => document.querySelector<HTMLElement>(".conversation");
const approvalDialogOpen = ref(false);
const pendingApproval = ref<ApprovalRequest | null>(null);
const reviewingApproval = ref(false);
const reviewer = ref("admin");
const reviewNote = ref("");

const suggestions = [
  "MCP 搜索本地文件中的 LangGraph",
  "用 MCP 查看 Git 仓库状态",
  "网页搜索 Django REST Framework 官方文档",
  "用 MCP 统计系统数据"
];
const agentRoster = [
  { name: "Supervisor", detail: "路由与任务拆分" },
  { name: "RAG Agent", detail: "知识库检索问答" },
  { name: "Blog Agent", detail: "博客与项目经历" },
  { name: "SQL Analysis", detail: "安全统计分析" },
  { name: "MCP Tool Agent", detail: "文件、Git、网页与数据库工具" },
  { name: "Writing", detail: "写作与总结" },
  { name: "Review", detail: "质量与引用检查" },
  { name: "Admin Approval", detail: "高风险操作审批" }
];
const canSend = computed(() => input.value.trim().length > 0 && !loading.value);

onMounted(() => {
  const pendingQuestion = localStorage.getItem("pendingAgentQuestion");
  if (pendingQuestion) {
    input.value = pendingQuestion;
    localStorage.removeItem("pendingAgentQuestion");
  }
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

  // 记录插入旧消息前的高度，加载后恢复视觉位置，避免滚动条突然跳到顶部。
  const scroller = getConversationScroller();
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
  if ((getConversationScroller()?.scrollTop ?? 0) < 40) {
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
    tokenUsage: message.token_usage,
    supervisor: parseSupervisorDecision(message.trace)
  };
}

function scrollToBottom() {
  const scroller = getConversationScroller();
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

  // 先乐观插入用户消息和占位回答，降低模型响应期间的界面等待感。
  messages.value.push({ role: "user", content: message });
  // 后续响应会原位更新这条占位消息，因此必须持有响应式代理。
  // 如果这里只保存普通对象，直接 Object.assign 原始引用不会通知 Vue 重渲染，
  // 就会出现“后台已有答案，但刷新页面后才显示”的现象。
  const pendingMessage = reactive<ChatMessage>({
    role: "agent",
    content: "正在生成回答，token 消耗统计中...",
    tokenUsage: emptyUsage,
    pending: true
  });
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
        conversation_id: currentConversationId.value,
        internet_enabled: internetEnabled.value
      })
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail ?? "Agent request failed");
    }

    currentConversationId.value = payload.conversation.id;
    // 原位替换占位对象，避免整个消息列表重建并丢失当前滚动位置。
    Object.assign(pendingMessage, {
      content: payload.answer,
      toolCalls: payload.tool_calls,
      sources: payload.sources,
      trace: payload.trace,
      tokenUsage: payload.token_usage,
      supervisor: payload.supervisor,
      pending: false
    });
    if (payload.approval_required && payload.approval && auth.session.role === "admin") {
      pendingApproval.value = payload.approval;
      approvalDialogOpen.value = true;
    }
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

async function reviewCurrentApproval(decision: "approve" | "reject") {
  if (!pendingApproval.value) return;
  reviewingApproval.value = true;
  try {
    const response = await fetch(`/api/agent/approvals/${pendingApproval.value.id}/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision,
        reviewer: reviewer.value,
        note: reviewNote.value
      })
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail ?? "审批处理失败");
    }
    pendingApproval.value = payload;
    messages.value.push({
      role: "agent",
      content: payload.result || (decision === "approve" ? "审批已通过并执行。" : "审批已拒绝。"),
      toolCalls: [
        {
          name: "admin_approval",
          input: `approval_id=${payload.id}`,
          output: payload.result
        }
      ],
      tokenUsage: emptyUsage
    });
    approvalDialogOpen.value = false;
    ElMessage.success(decision === "approve" ? "审批已通过并执行" : "审批已拒绝");
    await loadConversations();
    await nextTick();
    scrollToBottom();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "审批处理失败");
  } finally {
    reviewingApproval.value = false;
  }
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
    return;
  }

  event.preventDefault();
  void sendMessage();
}


function parseSupervisorDecision(trace?: string[]): SupervisorDecision | undefined {
  // 历史消息只持久化 trace，因此回放时从轨迹恢复 Supervisor 展示信息。
  const routeTrace = trace?.find((item) => item.startsWith("supervisor -> ") && item.includes("_agent"));
  if (!routeTrace) return undefined;
  const selectedAgent = routeTrace.match(/supervisor -> ([a-z_]+)/)?.[1] ?? "unknown_agent";
  return {
    selected_agent: selectedAgent,
    display_name: formatAgentName(selectedAgent),
    reason: routeTrace.replace(/^supervisor -> [a-z_]+ \(/, "").replace(/\)$/, ""),
    confidence: 0,
    handoff: `handoff -> ${formatAgentName(selectedAgent)}`
  };
}

function formatAgentName(agentName: string) {
  const names: Record<string, string> = {
    rag_agent: "RAG Agent",
    blog_agent: "Blog Agent",
    sql_analysis_agent: "SQL Analysis Agent",
    writing_agent: "Writing Agent",
    review_agent: "Review Agent",
    admin_approval_agent: "Admin Approval Agent",
    mcp_tool_agent: "MCP Tool Agent"
  };
  return names[agentName] ?? agentName;
}
</script>

<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">Knowledge Agent</div>
      <nav class="nav">
        <RouterLink to="/">概览</RouterLink>
        <RouterLink to="/blog">博客</RouterLink>
        <RouterLink to="/knowledge">知识库</RouterLink>
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
        <ChatMessageList
          :messages="messages"
          :has-more-before="hasMoreBefore"
          :loading-older="messagesLoading"
          @load-older="loadOlderMessages"
          @scroll="handleConversationScroll"
        />

        <ConversationSidebar
          v-model:history-search="historySearch"
          :conversations="conversations"
          :current-conversation-id="currentConversationId"
          :conversations-loading="conversationsLoading"
          :chat-loading="loading"
          :latest-token-usage="latestTokenUsage"
          :agents="agentRoster"
          :suggestions="suggestions"
          @refresh="loadConversations"
          @create="startNewConversation"
          @select="loadConversation"
          @suggest="sendMessage"
        />
      </section>

      <ChatComposer
        v-model:input="input"
        v-model:internet-enabled="internetEnabled"
        :loading="loading"
        :can-send="canSend"
        @send="sendMessage()"
        @keydown="handleComposerKeydown"
      />

      <ChatApprovalDialog
        v-model:open="approvalDialogOpen"
        v-model:reviewer="reviewer"
        v-model:note="reviewNote"
        :approval="pendingApproval"
        :reviewing="reviewingApproval"
        @review="reviewCurrentApproval"
      />
    </section>
  </main>
</template>
