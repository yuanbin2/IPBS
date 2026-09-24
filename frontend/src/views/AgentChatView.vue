<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from "vue";
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
  ConversationProject,
  SupervisorDecision,
  TokenUsage,
  ToolCall,
  TurnMetrics
} from "../features/chat/types";

const MESSAGE_PAGE_SIZE = 20;
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
const latestMetrics = ref<TurnMetrics | null>(null);
const projects = ref<ConversationProject[]>([]);
/** "all" 全部对话 | "none" 未分组 | 项目 id（字符串） */
const activeProject = ref("all");
const getConversationScroller = () => document.querySelector<HTMLElement>(".conversation");
const approvalDialogOpen = ref(false);
const pendingApproval = ref<ApprovalRequest | null>(null);
const reviewingApproval = ref(false);
const reviewer = ref("admin");
const reviewNote = ref("");

const canSend = computed(() => input.value.trim().length > 0 && !loading.value);

onMounted(() => {
  const pendingQuestion = localStorage.getItem("pendingAgentQuestion");
  if (pendingQuestion) {
    input.value = pendingQuestion;
    localStorage.removeItem("pendingAgentQuestion");
  }
  void loadProjects();
  void loadConversations();
});

async function loadProjects() {
  const response = await fetch("/api/agent/projects/");
  if (!response.ok) return;
  projects.value = await response.json();
  // 当前选中的项目被删掉时，回退到全部对话
  if (activeProject.value !== "all" && activeProject.value !== "none") {
    const stillExists = projects.value.some((project) => String(project.id) === activeProject.value);
    if (!stillExists) activeProject.value = "all";
  }
}

async function loadConversations() {
  conversationsLoading.value = true;
  try {
    const params = new URLSearchParams();
    if (historySearch.value.trim()) {
      params.set("q", historySearch.value.trim());
    }
    if (activeProject.value !== "all") {
      params.set("project", activeProject.value);
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

function selectProject(projectId: string) {
  if (activeProject.value === projectId) return;
  activeProject.value = projectId;
  void loadConversations();
}

async function createProject(name: string) {
  const response = await fetch("/api/agent/projects/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  });
  if (!response.ok) {
    ElMessage.error(response.status === 409 ? "项目名已存在" : "创建项目失败");
    return;
  }
  const project = await response.json();
  projects.value = [...projects.value, project];
  activeProject.value = String(project.id);
  await loadConversations();
  ElMessage.success(`已创建项目「${project.name}」`);
}

async function renameProject(project: ConversationProject, name: string) {
  const response = await fetch(`/api/agent/projects/${project.id}/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  });
  if (!response.ok) {
    ElMessage.error("重命名失败");
    return;
  }
  const updated = await response.json();
  projects.value = projects.value.map((item) => (item.id === updated.id ? updated : item));
}

async function deleteProject(project: ConversationProject) {
  const response = await fetch(`/api/agent/projects/${project.id}/`, { method: "DELETE" });
  if (!response.ok) {
    ElMessage.error("删除项目失败");
    return;
  }
  projects.value = projects.value.filter((item) => item.id !== project.id);
  if (activeProject.value === String(project.id)) {
    activeProject.value = "all";
  }
  await loadConversations();
  ElMessage.success("项目已删除，对话移回未分组");
}

async function moveConversation(conversation: Conversation, projectId: number | null) {
  const response = await fetch(`/api/agent/conversations/${conversation.id}/move/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId })
  });
  if (!response.ok) {
    ElMessage.error("移动对话失败");
    return;
  }
  ElMessage.success(projectId === null ? "已移出项目" : "已移动对话");
  await Promise.all([loadConversations(), loadProjects()]);
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
  const lastWithUsage = [...messages.value].reverse().find((message) => message.tokenUsage);
  latestMetrics.value = lastWithUsage?.tokenUsage
    ? metricsFromMessage(lastWithUsage.tokenUsage, lastWithUsage.toolCalls, lastWithUsage.sources)
    : null;
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

/** 单次工具调用是否成功：优先读后端显式 ok 标志，历史数据回退关键词判断。 */
function toolCallSucceeded(call: ToolCall): boolean {
  if (typeof call.ok === "boolean") return call.ok;
  const output = (call.output ?? "").toLowerCase();
  return !!output && !["error", "failed", "异常", "失败"].some((marker) => output.includes(marker));
}

/** 从流式 response 事件构建本轮指标。 */
function metricsFromEvent(event: {
  token_usage?: TokenUsage;
  tool_calls?: ChatMessage["toolCalls"];
  sources?: ChatMessage["sources"];
  latency_ms?: number;
}): TurnMetrics {
  const toolCalls = event.tool_calls ?? [];
  const succeeded = toolCalls.filter((call) => toolCallSucceeded(call)).length;
  return {
    tokenUsage: event.token_usage ?? { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
    latencyMs: event.latency_ms ?? null,
    toolTotal: toolCalls.length,
    toolSucceeded: succeeded,
    sourceCount: event.sources?.length ?? 0
  };
}

/** 从历史消息重建指标（延迟未知，置空）。 */
function metricsFromMessage(
  tokenUsage: TokenUsage,
  toolCalls?: ChatMessage["toolCalls"],
  sources?: ChatMessage["sources"]
): TurnMetrics {
  const calls = toolCalls ?? [];
  const succeeded = calls.filter((call) => toolCallSucceeded(call)).length;
  return {
    tokenUsage,
    latencyMs: null,
    toolTotal: calls.length,
    toolSucceeded: succeeded,
    sourceCount: sources?.length ?? 0
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
  latestMetrics.value = null;
  input.value = "";
}

async function sendMessage(prompt?: string) {
  const message = (prompt ?? input.value).trim();
  if (!message || loading.value) return;

  messages.value.push({ role: "user", content: message });
  const pendingMessage = reactive<ChatMessage>({
    role: "agent",
    content: "",
    tokenUsage: emptyUsage,
    pending: true,
    streamingTrace: [],
    thinkingExpanded: true
  });
  messages.value.push(pendingMessage);
  latestMetrics.value = null;
  input.value = "";
  loading.value = true;
  await nextTick();
  scrollToBottom();

  try {
    // Use SSE streaming endpoint
    const response = await fetch("/api/agent/chat/stream/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        conversation_id: currentConversationId.value,
        internet_enabled: internetEnabled.value,
        // 新对话直接落入侧边栏当前选中的项目（"all"/"none" 不传，保持未分组）
        project_id:
          activeProject.value !== "all" && activeProject.value !== "none"
            ? Number(activeProject.value)
            : undefined
      })
    });

    if (!response.ok) {
      const errorPayload = await response.json().catch(() => ({}));
      throw new Error(errorPayload.detail ?? "Stream request failed");
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const jsonStr = line.slice(6).trim();
        if (!jsonStr) continue;

        try {
          const event = JSON.parse(jsonStr);

          if (event.type === "trace" && event.data) {
            pendingMessage.streamingTrace!.push(event.data);
            nextTick(() => scrollToBottom());
          } else if (event.type === "response") {
            Object.assign(pendingMessage, {
              content: event.answer,
              toolCalls: event.tool_calls,
              sources: event.sources,
              trace: event.trace,
              tokenUsage: event.token_usage,
              supervisor: event.supervisor,
              pending: false
            });
            latestMetrics.value = metricsFromEvent(event);
            if (event.approval_required && event.approval && auth.session.role === "admin") {
              pendingApproval.value = event.approval;
              approvalDialogOpen.value = true;
            }
          } else if (event.type === "done") {
            currentConversationId.value = event.conversation_id;
            await Promise.all([loadConversations(), loadProjects()]);
          } else if (event.type === "error") {
            throw new Error(event.detail ?? "Unknown stream error");
          }
        } catch (parseError) {
          if (parseError instanceof Error && parseError.message !== "Unknown stream error") {
            // Skip malformed JSON lines
          } else {
            throw parseError;
          }
        }
      }
    }
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
  <section class="chat-workspace">
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
          :latest-metrics="latestMetrics"
          :projects="projects"
          :active-project="activeProject"
          @refresh="loadConversations"
          @create="startNewConversation"
          @select="loadConversation"
          @suggest="sendMessage"
          @select-project="selectProject"
          @create-project="createProject"
          @rename-project="renameProject"
          @delete-project="deleteProject"
          @move-conversation="(conversation, projectId) => moveConversation(conversation, projectId)"
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
</template>
