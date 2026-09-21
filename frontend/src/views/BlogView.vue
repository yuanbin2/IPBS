<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  Refresh,
} from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { type UploadImgEvent } from "md-editor-v3";
import "md-editor-v3/lib/style.css";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import BlogSidebar from "../features/blog/components/BlogSidebar.vue";
import BlogAgentWidget from "../features/blog/components/BlogAgentWidget.vue";
import BlogWriter from "../features/blog/components/BlogWriter.vue";
import ArticleDetail from "../features/blog/components/ArticleDetail.vue";
import ArticleList from "../features/blog/components/ArticleList.vue";
import type {
  ApprovalRequest,
  ArchiveGroup,
  BlogAgentChatMessage,
  BlogArticle,
  BlogCategory,
  BlogTag
} from "../features/blog/types";

const auth = useAuthStore();

const route = useRoute();
const router = useRouter();

const articles = ref<BlogArticle[]>([]);
const currentArticle = ref<BlogArticle | null>(null);
const tags = ref<BlogTag[]>([]);
const categories = ref<BlogCategory[]>([]);
const archive = ref<ArchiveGroup[]>([]);
const about = ref<{ title: string; content: string; highlights: string[] } | null>(null);
const loading = ref(false);
const publishing = ref(false);
const submittingComment = ref(false);
const uploadingImage = ref(false);
const deletingArticleSlug = ref("");
const editorError = ref("");
const approvalDialogOpen = ref(false);
const pendingApproval = ref<ApprovalRequest | null>(null);
const reviewingApproval = ref(false);
const reviewer = ref("admin");
const reviewNote = ref("");
const blogAgentOpen = ref(false);
const blogAgentLoading = ref(false);
const blogAgentInput = ref("这个博客项目的技术栈是什么？");
const blogAgentSessionKey = ref(localStorage.getItem("blogAgentSessionKey") || "");
const blogAgentMessages = ref<BlogAgentChatMessage[]>([
  {
    role: "agent",
    content: "你好，我是这个博客里的智能体。你可以问公开文章、项目经历、技术栈、LangGraph 或 Agentic RAG。"
  }
]);
const blogAgentSuggestions = ["你做过哪些 LangGraph 项目？", "这个项目架构是什么？", "Agentic RAG 是怎么实现的？"];
const commentDraft = ref({
  author_name: "访客",
  content: ""
});

const draft = ref({
  title: "我的 LangGraph 项目复盘",
  summary: "从环境搭建到 Agentic RAG，记录这个项目的关键工程选择。",
  category: "项目复盘",
  tags: "LangGraph,RAG,Django",
  content: [
    "## 项目背景",
    "",
    "这篇文章记录我如何把 **Vue、Django、LangChain 和 LangGraph** 组合成一个企业知识智能体平台。",
    "",
    "## 关键收获",
    "",
    "- 用 Django 管理博客和知识库数据",
    "- 用 LangGraph 编排 Agentic RAG 流程",
    "- 让博客文章发布后自动成为 Agent 的知识来源",
    "",
    "> 博客内容本身就是 Agent 的知识来源。"
  ].join("\n")
});

const noteTemplates = [
  {
    name: "项目复盘",
    content: "## 背景\n\n## 目标\n\n## 技术方案\n\n## 关键实现\n\n## 遇到的问题\n\n## 复盘总结\n"
  },
  {
    name: "论文笔记",
    content: "## 论文信息\n\n## 核心问题\n\n## 方法概述\n\n## 实验结论\n\n## 可借鉴点\n"
  },
  {
    name: "技术方案",
    content: "## 需求\n\n## 架构设计\n\n## 数据模型\n\n## API 设计\n\n## 风险与取舍\n\n## 下一步\n"
  }
];

const editorStats = computed(() => {
  const plain = draft.value.content.replace(/```[\s\S]*?```/g, "").replace(/[#>*_\-\[\]()`]/g, "");
  const compact = plain.replace(/\s+/g, "");
  const englishWords = plain.match(/[A-Za-z0-9]+/g)?.length ?? 0;
  const count = compact.length + englishWords;
  return {
    words: count,
    readingMinutes: Math.max(1, Math.ceil(count / 450)),
    headings: draft.value.content
      .split("\n")
      .filter((line) => /^#{1,3}\s+/.test(line))
      .map((line) => line.replace(/^#{1,3}\s+/, "").trim())
  };
});

const activeSlug = computed(() => String(route.params.slug ?? ""));
const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);
const storedRightWidth = Number(localStorage.getItem("blogLayoutRightWidth"));
const rightPanelVisible = ref(localStorage.getItem("blogLayoutRightVisible") !== "false");
const rightPanelWidth = ref(clamp(Number.isFinite(storedRightWidth) && storedRightWidth > 0 ? storedRightWidth : 360, 260, 560));
const resizingPanel = ref<"right" | null>(null);
const clearingDraft = ref(false);
const blogLayoutStyle = computed(() => ({
  "--blog-panel-width": `${rightPanelWidth.value}px`
}));

function resizePanels(event: PointerEvent) {
  if (resizingPanel.value === "right") {
    const nextWidth = window.innerWidth - event.clientX;
    if (nextWidth <= 210) {
      rightPanelVisible.value = false;
      stopPanelResize();
      return;
    }
    rightPanelWidth.value = clamp(nextWidth, 260, 560);
  }
}

function stopPanelResize() {
  if (!resizingPanel.value) return;
  resizingPanel.value = null;
  document.body.classList.remove("blog-panel-resizing");
  window.removeEventListener("pointermove", resizePanels);
  window.removeEventListener("pointerup", stopPanelResize);
}

function startPanelResize(panel: "right", event: PointerEvent) {
  if (window.matchMedia("(max-width: 980px)").matches) return;
  resizingPanel.value = panel;
  document.body.classList.add("blog-panel-resizing");
  window.addEventListener("pointermove", resizePanels);
  window.addEventListener("pointerup", stopPanelResize);
  event.preventDefault();
}

onMounted(async () => {
  restoreDraft();
  await Promise.all([loadArticles(), loadTags(), loadCategories(), loadArchive(), loadAbout()]);
  if (activeSlug.value) {
    await loadArticle(activeSlug.value);
  }
  await loadBlogAgentHistory();
});

watch(draft, () => {
  if (clearingDraft.value) return;
  localStorage.setItem("blogWriterDraft", JSON.stringify(draft.value));
}, { deep: true });

watch(activeSlug, async (slug) => {
  if (slug) {
    await loadArticle(slug);
  } else {
    currentArticle.value = null;
  }
});

watch([rightPanelWidth, rightPanelVisible], () => {
  localStorage.setItem("blogLayoutRightWidth", String(rightPanelWidth.value));
  localStorage.setItem("blogLayoutRightVisible", String(rightPanelVisible.value));
});

onBeforeUnmount(stopPanelResize);

async function loadArticles(params: Record<string, string> = {}) {
  loading.value = true;
  try {
    const query = new URLSearchParams(params).toString();
    articles.value = await requestJson(`/api/agent/blog/articles/${query ? `?${query}` : ""}`);
  } finally {
    loading.value = false;
  }
}

async function loadArticle(slug: string) {
  currentArticle.value = await requestJson(`/api/agent/blog/articles/${encodeURIComponent(slug)}/`);
}

async function loadTags() {
  tags.value = await requestJson("/api/agent/blog/tags/");
}

async function loadCategories() {
  categories.value = await requestJson("/api/agent/blog/categories/");
}

async function loadArchive() {
  archive.value = await requestJson("/api/agent/blog/archive/");
}

async function loadAbout() {
  about.value = await requestJson("/api/agent/blog/about/");
}

async function openArticle(article: BlogArticle) {
  await router.push({ name: "blog", params: { slug: article.slug } });
}

async function applyFilter(params: Record<string, string>) {
  currentArticle.value = null;
  await router.push("/blog");
  await loadArticles(params);
}

async function publishDraft() {
  editorError.value = "";
  if (!draft.value.title.trim() || !draft.value.content.trim()) {
    editorError.value = "标题和正文不能为空。";
    return;
  }

  publishing.value = true;
  try {
    const payload = await requestJson("/api/agent/blog/articles/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...draft.value,
        tags: draft.value.tags.split(",").map((tag) => tag.trim()).filter(Boolean),
        publish: true
      })
    });
    await loadArticles();
    await loadArchive();
    if (payload.approval_required) {
      openApprovalDialog(payload.approval);
      ElMessage.warning(`文章已保存为草稿，发布审批 #${payload.approval.id} 已创建`);
      return;
    }
    await openArticle(payload);
  } catch (error) {
    editorError.value = error instanceof Error ? error.message : "发布失败，请稍后重试。";
  } finally {
    publishing.value = false;
  }
}

async function syncArticleKnowledge(article: BlogArticle) {
  publishing.value = true;
  try {
    const payload = await requestJson(`/api/agent/blog/articles/${encodeURIComponent(article.slug)}/publish/`, { method: "POST" });
    await Promise.all([loadArticles(), loadArchive()]);
    if (payload.approval_required) {
      openApprovalDialog(payload.approval);
      ElMessage.warning(`发布审批 #${payload.approval.id} 已创建，批准后才会进入知识库`);
      return;
    }
    await loadArticle(article.slug);
  } finally {
    publishing.value = false;
  }
}

async function deleteArticle(article: BlogArticle) {
  try {
    await ElMessageBox.confirm(
      `确定删除文章「${article.title}」吗？如果它已经进入知识库，对应的知识库文档也会一起删除。`,
      "删除文章",
      {
        confirmButtonText: "删除",
        cancelButtonText: "取消",
        type: "warning",
        confirmButtonClass: "el-button--danger"
      }
    );
  } catch {
    return;
  }

  deletingArticleSlug.value = article.slug;
  try {
    const payload = await requestJson(`/api/agent/blog/articles/${encodeURIComponent(article.slug)}/`, {
      method: "DELETE"
    });
    if (payload?.approval_required) {
      openApprovalDialog(payload.approval);
      ElMessage.warning(`删除审批 #${payload.approval.id} 已创建，批准后才会删除文章`);
      return;
    }
    if (currentArticle.value?.slug === article.slug) {
      currentArticle.value = null;
      await router.push("/blog");
    }
    await Promise.all([loadArticles(), loadArchive(), loadTags(), loadCategories()]);
    ElMessage.success("文章已删除");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除文章失败");
  } finally {
    deletingArticleSlug.value = "";
  }
}

function restoreDraft() {
  const cached = localStorage.getItem("blogWriterDraft");
  if (!cached) return;
  try {
    Object.assign(draft.value, JSON.parse(cached));
  } catch {
    localStorage.removeItem("blogWriterDraft");
  }
}

function applyTemplate(content: string) {
  draft.value.content = content;
}

function insertSnippet(snippet: string) {
  draft.value.content = `${draft.value.content.trim()}\n\n${snippet}\n`;
}

async function clearDraftCache() {
  try {
    await ElMessageBox.confirm(
      "将清空标题、摘要、分类、标签和正文，且无法从本地草稿恢复。是否继续？",
      "清空本地草稿",
      {
        confirmButtonText: "确认清空",
        cancelButtonText: "取消",
        type: "warning"
      }
    );
  } catch {
    return;
  }

  clearingDraft.value = true;
  draft.value = {
    title: "",
    summary: "",
    category: "",
    tags: "",
    content: ""
  };
  await nextTick();
  localStorage.removeItem("blogWriterDraft");
  clearingDraft.value = false;
  ElMessage.success("本地草稿和编辑器内容已清空");
}

function openApprovalDialog(approval: ApprovalRequest) {
  if (auth.session.role !== "admin") return;
  pendingApproval.value = approval;
  approvalDialogOpen.value = true;
}

async function reviewCurrentApproval(decision: "approve" | "reject") {
  if (!pendingApproval.value) return;
  reviewingApproval.value = true;
  try {
    const payload = await requestJson(`/api/agent/approvals/${pendingApproval.value.id}/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reviewer: reviewer.value, note: reviewNote.value })
    });
    pendingApproval.value = payload;
    approvalDialogOpen.value = false;
    ElMessage.success(decision === "approve" ? "审批已通过并执行" : "审批已拒绝");
    await Promise.all([loadArticles(), loadArchive(), loadTags(), loadCategories()]);
    if (currentArticle.value?.slug) {
      try {
        await loadArticle(currentArticle.value.slug);
      } catch {
        currentArticle.value = null;
        await router.push("/blog");
      }
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "审批处理失败");
  } finally {
    reviewingApproval.value = false;
  }
}

async function submitComment(article: BlogArticle) {
  if (!commentDraft.value.author_name.trim() || !commentDraft.value.content.trim()) return;
  submittingComment.value = true;
  try {
    await requestJson(`/api/agent/blog/articles/${encodeURIComponent(article.slug)}/comments/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(commentDraft.value)
    });
    commentDraft.value.content = "";
    await loadArticle(article.slug);
  } finally {
    submittingComment.value = false;
  }
}

function askAgent(article: BlogArticle) {
  void router.push(`/chat`);
  localStorage.setItem("pendingAgentQuestion", `根据我的博客文章《${article.title}》，总结我的项目经验`);
}

async function loadBlogAgentHistory() {
  if (!blogAgentSessionKey.value) return;
  try {
    const payload = await requestJson(`/api/agent/blog/agent/chat/?session_key=${encodeURIComponent(blogAgentSessionKey.value)}`);
    if (payload.messages?.length) {
      blogAgentMessages.value = payload.messages.map((message: any) => ({
        role: message.role,
        content: message.content,
        sources: message.sources
      }));
    }
  } catch {
    localStorage.removeItem("blogAgentSessionKey");
    blogAgentSessionKey.value = "";
  }
}

async function sendBlogAgentMessage(prompt?: string) {
  const message = (prompt ?? blogAgentInput.value).trim();
  if (!message || blogAgentLoading.value) return;

  blogAgentOpen.value = true;
  blogAgentMessages.value.push({ role: "user", content: message });
  const pendingMessage: BlogAgentChatMessage = {
    role: "agent",
    content: "正在根据公开博客资料检索...",
    pending: true
  };
  blogAgentMessages.value.push(pendingMessage);
  blogAgentInput.value = "";
  blogAgentLoading.value = true;

  try {
    const payload = await requestJson("/api/agent/blog/agent/chat/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_key: blogAgentSessionKey.value
      })
    });
    blogAgentSessionKey.value = payload.session_key;
    localStorage.setItem("blogAgentSessionKey", payload.session_key);
    Object.assign(pendingMessage, {
      content: payload.answer,
      sources: payload.sources,
      blocked: payload.blocked,
      pending: false
    });
  } catch (error) {
    Object.assign(pendingMessage, {
      content: error instanceof Error ? error.message : "博客智能体暂时不可用，请稍后再试。",
      pending: false
    });
  } finally {
    blogAgentLoading.value = false;
  }
}

function handleBlogAgentKeydown(event: KeyboardEvent) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  void sendBlogAgentMessage();
}

const handleEditorUpload: UploadImgEvent = async (files, callback) => {
  editorError.value = "";
  uploadingImage.value = true;
  try {
    const uploaded = await Promise.all(
      files.map(async (file) => {
        const formData = new FormData();
        formData.append("image", file);
        const payload = await requestJson("/api/agent/blog/images/", {
          method: "POST",
          body: formData
        });
        return {
          url: payload.url,
          alt: file.name.replace(/\.[^.]+$/, ""),
          title: file.name
        };
      })
    );
    callback(uploaded);
  } catch (error) {
    editorError.value = error instanceof Error ? error.message : "图片上传失败。";
  } finally {
    uploadingImage.value = false;
  }
};

async function requestJson(url: string, options: RequestInit = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") ?? "";
  const text = await response.text();
  let payload: any = null;

  if (contentType.includes("application/json") && text) {
    payload = JSON.parse(text);
  } else if (text) {
    const plainText = text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    payload = { detail: plainText.slice(0, 220) || "服务返回了非 JSON 响应。" };
  }

  if (!response.ok) {
    throw new Error(payload?.detail ?? `请求失败：HTTP ${response.status}`);
  }
  return payload;
}
</script>

<template>
  <main
    class="shell blog-shell"
    :class="{
      'right-panel-hidden': !rightPanelVisible,
      'is-resizing': resizingPanel
    }"
    :style="blogLayoutStyle"
  >
    <section class="workspace blog-workspace">
      <header class="topbar">
        <div>
          <h1>个人技术博客</h1>
        </div>
        <div class="blog-layout-controls">
          <el-button :icon="Refresh" :loading="loading" @click="loadArticles()">刷新文章</el-button>
        </div>
      </header>

      <section class="blog-layout">
        <button
          class="panel-toggle right-panel-toggle"
          type="button"
          :aria-label="rightPanelVisible ? '隐藏辅助栏' : '显示辅助栏'"
          :title="rightPanelVisible ? '隐藏辅助栏' : '显示辅助栏'"
          @click="rightPanelVisible = !rightPanelVisible"
        >
          {{ rightPanelVisible ? "›" : "‹" }}
        </button>
        <main class="blog-main">
          <BlogWriter
            :draft="draft"
            :templates="noteTemplates"
            :stats="editorStats"
            :publishing="publishing"
            :uploading-image="uploadingImage"
            :error="editorError"
            :upload-handler="handleEditorUpload"
            @publish="publishDraft"
            @apply-template="applyTemplate"
            @insert-snippet="insertSnippet"
            @clear-draft="clearDraftCache"
          />

          <ArticleDetail
            v-if="currentArticle"
            :article="currentArticle"
            :comment-draft="commentDraft"
            :publishing="publishing"
            :submitting-comment="submittingComment"
            :deleting-slug="deletingArticleSlug"
            @back="currentArticle = null; router.push('/blog')"
            @ask-agent="askAgent"
            @sync="syncArticleKnowledge"
            @remove="deleteArticle"
            @submit-comment="submitComment"
          />
          <ArticleList
            v-else
            :articles="articles"
            :deleting-slug="deletingArticleSlug"
            @open="openArticle"
            @remove="deleteArticle"
          />
        </main>

        <button
          v-show="rightPanelVisible"
          class="panel-resizer right-panel-resizer"
          type="button"
          aria-label="拖动调整辅助栏宽度"
          title="拖动调整辅助栏宽度"
          @pointerdown="startPanelResize('right', $event)"
        />

        <BlogSidebar
          v-show="rightPanelVisible"
          :tags="tags"
          :categories="categories"
          :archive="archive"
          :about="about"
          @filter="applyFilter"
        />
      </section>

      <el-dialog v-model="approvalDialogOpen" title="审批博客操作" width="560px" align-center>
        <section v-if="pendingApproval" class="approval-dialog-body">
          <p>{{ pendingApproval.description }}</p>
          <dl>
            <div v-for="(value, key) in pendingApproval.payload" :key="key">
              <dt>{{ key }}</dt>
              <dd>{{ value }}</dd>
            </div>
          </dl>
          <el-input v-model="reviewer" placeholder="审批人" />
          <el-input v-model="reviewNote" placeholder="审批备注" type="textarea" :rows="3" />
          <p v-if="pendingApproval.result" class="approval-result">{{ pendingApproval.result }}</p>
        </section>
        <template #footer>
          <el-button :loading="reviewingApproval" @click="reviewCurrentApproval('reject')">拒绝</el-button>
          <el-button type="primary" :loading="reviewingApproval" @click="reviewCurrentApproval('approve')">
            批准并执行
          </el-button>
        </template>
      </el-dialog>
    </section>

    <BlogAgentWidget
      v-model:open="blogAgentOpen"
      v-model:input="blogAgentInput"
      :loading="blogAgentLoading"
      :messages="blogAgentMessages"
      :suggestions="blogAgentSuggestions"
      @send="sendBlogAgentMessage"
      @keydown="handleBlogAgentKeydown"
    />
  </main>
</template>
