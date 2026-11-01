import { nextTick, ref, watch } from "vue";
import type { BlogAgentChatMessage } from "../types";
import { scrollWhenHeightSettles } from "../../chat/utils/scroll";
import { mapBlogAgentHistoryMessages, mergeOlderBlogAgentMessages } from "../utils/blogAgentHistory";
import { fetchBlogAgentHistory, postBlogAgentMessage } from "../api/blogAgentApi";

/** 博客悬浮问答的会话状态、历史分页和请求；页面只负责打开入口及挂载组件。 */
export function useBlogAgentChat() {
  const blogAgentOpen = ref(false);
  const blogAgentLoading = ref(false);
  const blogAgentInput = ref("这个博客项目的技术栈是什么？");
  const blogAgentSource = ref<"legacy" | "ragagent">(
    localStorage.getItem("blogAgentSource") === "ragagent" ? "ragagent" : "legacy",
  );
  const blogAgentSessionKey = ref(localStorage.getItem("blogAgentSessionKey") || "");
  const blogAgentMessages = ref<BlogAgentChatMessage[]>([{
    role: "agent",
    content: "你好，我是这个博客里的智能体。你可以问公开文章、项目经历、技术栈、LangGraph 或 Agentic RAG。",
  }]);
  const blogAgentHasMoreBefore = ref(false);
  const blogAgentLoadingOlder = ref(false);
  const blogAgentSuggestions = ["你做过哪些 LangGraph 项目？", "这个项目架构是什么？", "Agentic RAG 是怎么实现的？"];

  function getScroller(): HTMLElement | null {
    return blogAgentOpen.value ? (document.querySelector<HTMLElement>(".blog-agent-messages") ?? null) : null;
  }
  async function loadBlogAgentHistory() {
    if (!blogAgentSessionKey.value) return;
    try {
      const payload = await fetchBlogAgentHistory(blogAgentSessionKey.value);
      if (payload.messages?.length) {
        blogAgentMessages.value = [...blogAgentMessages.value, ...mapBlogAgentHistoryMessages(payload.messages)];
        blogAgentHasMoreBefore.value = Boolean(payload.has_more_before);
        void scrollWhenHeightSettles(getScroller());
      }
    } catch {
      localStorage.removeItem("blogAgentSessionKey");
      blogAgentSessionKey.value = "";
    }
  }
  async function loadMoreBlogAgentHistory() {
    if (!blogAgentSessionKey.value || !blogAgentHasMoreBefore.value || blogAgentLoadingOlder.value) return;
    const oldestPersisted = blogAgentMessages.value.find((message) => typeof message.id === "number");
    if (!oldestPersisted?.id) return;
    const scroller = getScroller();
    const previousHeight = scroller?.scrollHeight ?? 0;
    blogAgentLoadingOlder.value = true;
    try {
      const payload = await fetchBlogAgentHistory(blogAgentSessionKey.value, oldestPersisted.id);
      blogAgentMessages.value = mergeOlderBlogAgentMessages(
        blogAgentMessages.value, mapBlogAgentHistoryMessages(payload.messages ?? []),
      );
      blogAgentHasMoreBefore.value = Boolean(payload.has_more_before);
      await nextTick();
      if (scroller) scroller.scrollTop = scroller.scrollHeight - previousHeight;
    } catch {
      // 加载更早消息失败不打断当前会话，按钮恢复可重试。
    } finally {
      blogAgentLoadingOlder.value = false;
    }
  }
  watch(blogAgentOpen, (open) => {
    if (open) void nextTick().then(() => scrollWhenHeightSettles(getScroller()));
  });

  async function sendBlogAgentMessage(prompt?: string) {
    const message = (prompt ?? blogAgentInput.value).trim();
    if (!message || blogAgentLoading.value) return;
    blogAgentOpen.value = true;
    blogAgentMessages.value.push({ role: "user", content: message });
    const pendingMessage: BlogAgentChatMessage = {
      role: "agent",
      content: blogAgentSource.value === "ragagent"
        ? "正在通过 RAG-Agent 检索本站隔离知识..." : "正在根据公开博客资料检索...",
      pending: true,
    };
    blogAgentMessages.value.push(pendingMessage);
    blogAgentInput.value = "";
    blogAgentLoading.value = true;
    void nextTick().then(() => scrollWhenHeightSettles(getScroller()));
    try {
      const payload = await postBlogAgentMessage(message, blogAgentSessionKey.value, blogAgentSource.value);
      blogAgentSessionKey.value = payload.session_key;
      localStorage.setItem("blogAgentSessionKey", payload.session_key);
      Object.assign(pendingMessage, {
        content: payload.answer, sources: payload.sources, blocked: payload.blocked, pending: false,
        rag_source_effective: payload.rag_source_effective, degraded: payload.degraded,
        degraded_reason: payload.degraded_reason,
      });
    } catch (error) {
      Object.assign(pendingMessage, {
        content: error instanceof Error ? error.message : "博客智能体暂时不可用，请稍后再试。",
        pending: false,
      });
    } finally {
      blogAgentLoading.value = false;
      void nextTick().then(() => scrollWhenHeightSettles(getScroller()));
    }
  }
  function handleBlogAgentKeydown(event: KeyboardEvent) {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    void sendBlogAgentMessage();
  }
  return {
    blogAgentOpen, blogAgentLoading, blogAgentInput, blogAgentSource, blogAgentMessages,
    blogAgentHasMoreBefore, blogAgentLoadingOlder, blogAgentSuggestions, loadBlogAgentHistory,
    loadMoreBlogAgentHistory, sendBlogAgentMessage, handleBlogAgentKeydown,
  };
}
