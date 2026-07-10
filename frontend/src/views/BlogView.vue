<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  ChatDotRound,
  CollectionTag,
  Delete,
  EditPen,
  Files,
  Promotion,
  Refresh,
} from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { MdEditor, MdPreview, type UploadImgEvent } from "md-editor-v3";
import "md-editor-v3/lib/style.css";
import { RouterLink, useRoute, useRouter } from "vue-router";

interface BlogTag {
  id: number;
  name: string;
  slug: string;
  article_count: number;
}

interface BlogCategory {
  id: number;
  name: string;
  slug: string;
  description: string;
  article_count: number;
}

interface BlogArticle {
  id: number;
  title: string;
  slug: string;
  summary: string;
  content?: string;
  status: string;
  view_count: number;
  category: BlogCategory | null;
  tags: BlogTag[];
  published_at: string | null;
  knowledge_document_id: number | null;
  comment_count: number;
  comments?: BlogComment[];
}

interface BlogComment {
  id: number;
  author_name: string;
  content: string;
  created_at: string;
}

interface ArchiveGroup {
  month: string;
  articles: BlogArticle[];
}

interface BlogAgentSource {
  title: string;
  kind: string;
  content: string;
  score: number;
  url: string;
}

interface BlogAgentChatMessage {
  role: "user" | "agent";
  content: string;
  sources?: BlogAgentSource[];
  blocked?: boolean;
  pending?: boolean;
}

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

interface ApprovalRequest {
  id: number;
  title: string;
  description: string;
  payload: Record<string, unknown>;
  status: "pending" | "executed" | "rejected" | "failed";
  result: string;
}

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

onMounted(async () => {
  restoreDraft();
  await Promise.all([loadArticles(), loadTags(), loadCategories(), loadArchive(), loadAbout()]);
  if (activeSlug.value) {
    await loadArticle(activeSlug.value);
  }
  await loadBlogAgentHistory();
});

watch(draft, () => {
  localStorage.setItem("blogWriterDraft", JSON.stringify(draft.value));
}, { deep: true });

watch(activeSlug, async (slug) => {
  if (slug) {
    await loadArticle(slug);
  } else {
    currentArticle.value = null;
  }
});

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

function clearDraftCache() {
  localStorage.removeItem("blogWriterDraft");
  ElMessage.success("本地草稿缓存已清理");
}

function openApprovalDialog(approval: ApprovalRequest) {
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
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">Knowledge Agent</div>
      <nav class="nav">
        <RouterLink to="/">概览</RouterLink>
        <RouterLink class="active" to="/blog">博客</RouterLink>
        <RouterLink to="/knowledge">知识库</RouterLink>
        <RouterLink to="/chat">对话</RouterLink>
        <a>评估</a>
      </nav>
    </aside>

    <section class="workspace blog-workspace">
      <header class="topbar">
        <div>
          <p class="eyebrow">Day 6 Personal Blog Agent</p>
          <h1>个人技术博客</h1>
        </div>
        <el-button :icon="Refresh" :loading="loading" @click="loadArticles()">刷新文章</el-button>
      </header>

      <section class="blog-layout">
        <main class="blog-main">
          <section class="write-box markdown-writer">
            <header class="writer-heading">
              <h2><el-icon><EditPen /></el-icon> Markdown 写作台</h2>
              <el-button type="primary" :loading="publishing" @click="publishDraft">发布并加入知识库</el-button>
            </header>

            <div class="writer-fields">
              <el-input v-model="draft.title" size="large" placeholder="文章标题" />
              <el-input v-model="draft.summary" placeholder="摘要，会显示在文章卡片里" />
              <div class="writer-meta">
                <el-input v-model="draft.category" placeholder="分类" />
                <el-input v-model="draft.tags" placeholder="标签，逗号分隔" />
              </div>
            </div>

            <section class="note-workbench">
              <div class="note-actions">
                <el-button v-for="item in noteTemplates" :key="item.name" @click="applyTemplate(item.content)">
                  {{ item.name }}
                </el-button>
                <el-button @click="insertSnippet('> 这里记录一个关键观察。')">引用</el-button>
                <el-button @click="insertSnippet('```python\n# code here\n```')">代码块</el-button>
                <el-button plain @click="clearDraftCache">清理本地草稿</el-button>
              </div>
              <div class="note-stats">
                <span>{{ editorStats.words }} 字</span>
                <span>约 {{ editorStats.readingMinutes }} 分钟阅读</span>
                <span>自动保存</span>
              </div>
              <div v-if="editorStats.headings.length" class="note-outline">
                <strong>大纲</strong>
                <span v-for="heading in editorStats.headings" :key="heading">{{ heading }}</span>
              </div>
            </section>

            <MdEditor
              v-model="draft.content"
              language="zh-CN"
              preview-theme="github"
              code-theme="github"
              :toolbars-exclude="['github']"
              :show-code-row-number="true"
              :footers="['markdownTotal', 'scrollSwitch']"
              :on-upload-img="handleEditorUpload"
              :placeholder="'用 Markdown 写正文，可插入标题、列表、代码块、表格、链接、图片、流程图和公式。'"
              class="blog-md-editor"
            />

            <p v-if="editorError" class="editor-error">{{ editorError }}</p>
            <div class="writer-footer">
              <span>{{ uploadingImage ? "图片上传中..." : "支持工具栏、预览、全屏、代码块、表格、链接和图片上传" }}</span>
              <el-button type="primary" :loading="publishing" @click="publishDraft">发布文章</el-button>
            </div>
          </section>

          <section v-if="currentArticle" class="article-detail">
            <button class="text-link" type="button" @click="currentArticle = null; router.push('/blog')">返回文章列表</button>
            <h2>{{ currentArticle.title }}</h2>
            <div class="article-meta">
              <span>{{ currentArticle.category?.name || "未分类" }}</span>
              <span>{{ currentArticle.view_count }} 次浏览</span>
              <span v-if="currentArticle.knowledge_document_id">已进入知识库</span>
            </div>
            <p class="summary">{{ currentArticle.summary }}</p>
            <MdPreview
              :model-value="currentArticle.content || ''"
              language="zh-CN"
              preview-theme="github"
              code-theme="github"
              :show-code-row-number="true"
              class="article-content blog-md-preview"
            />
            <div class="tag-row">
              <span v-for="tag in currentArticle.tags" :key="tag.id">{{ tag.name }}</span>
            </div>
            <div class="article-actions">
              <el-button type="primary" :icon="ChatDotRound" @click="askAgent(currentArticle)">让 Agent 总结这篇文章</el-button>
              <el-button
                v-if="!currentArticle.knowledge_document_id"
                :loading="publishing"
                @click="syncArticleKnowledge(currentArticle)"
              >
                同步到知识库
              </el-button>
              <el-button
                type="danger"
                plain
                :icon="Delete"
                :loading="deletingArticleSlug === currentArticle.slug"
                @click="deleteArticle(currentArticle)"
              >
                删除文章
              </el-button>
            </div>
            <section class="comment-section">
              <h3>评论</h3>
              <article v-for="comment in currentArticle.comments" :key="comment.id" class="comment-item">
                <strong>{{ comment.author_name }}</strong>
                <p>{{ comment.content }}</p>
              </article>
              <form class="comment-form" @submit.prevent="submitComment(currentArticle)">
                <el-input v-model="commentDraft.author_name" placeholder="昵称" />
                <el-input v-model="commentDraft.content" type="textarea" :rows="3" placeholder="写下你的想法" />
                <el-button type="primary" native-type="submit" :loading="submittingComment">发表评论</el-button>
              </form>
            </section>
          </section>

          <section v-else class="article-list">
            <article v-for="article in articles" :key="article.id" class="article-card" @click="openArticle(article)">
              <div>
                <h2>{{ article.title }}</h2>
                <p>{{ article.summary }}</p>
              </div>
              <footer>
                <span>{{ article.category?.name || "未分类" }}</span>
                <span>{{ article.view_count }} views</span>
                <strong v-if="article.knowledge_document_id">Knowledge Ready</strong>
                <el-button
                  size="small"
                  type="danger"
                  plain
                  :icon="Delete"
                  :loading="deletingArticleSlug === article.slug"
                  @click.stop="deleteArticle(article)"
                >
                  删除
                </el-button>
              </footer>
            </article>
          </section>
        </main>

        <aside class="blog-panel">
          <section class="side-box">
            <h2><el-icon><CollectionTag /></el-icon> 标签</h2>
            <div class="tag-cloud">
              <button v-for="tag in tags" :key="tag.id" type="button" @click="applyFilter({ tag: tag.slug })">
                {{ tag.name }} {{ tag.article_count }}
              </button>
            </div>
          </section>

          <section class="side-box">
            <h2>分类</h2>
            <div class="tag-cloud">
              <button
                v-for="category in categories"
                :key="category.id"
                type="button"
                @click="applyFilter({ category: category.slug })"
              >
                {{ category.name }} {{ category.article_count }}
              </button>
            </div>
          </section>

          <section class="side-box">
            <h2><el-icon><Files /></el-icon> 归档</h2>
            <button v-for="group in archive" :key="group.month" type="button" class="archive-item">
              {{ group.month }} / {{ group.articles.length }} 篇
            </button>
          </section>

          <section v-if="about" class="side-box about-box">
            <h2><el-icon><Promotion /></el-icon> 关于我</h2>
            <p>{{ about.content }}</p>
            <span v-for="item in about.highlights" :key="item">{{ item }}</span>
          </section>
        </aside>
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

    <section class="blog-agent-widget" :class="{ open: blogAgentOpen }">
      <button class="blog-agent-fab" type="button" @click="blogAgentOpen = !blogAgentOpen">
        <el-icon><ChatDotRound /></el-icon>
        <span>问博客智能体</span>
      </button>

      <section v-if="blogAgentOpen" class="blog-agent-panel">
        <header>
          <div>
            <strong>博客智能体</strong>
            <small>仅回答公开博客、简历和 README 内容</small>
          </div>
          <button type="button" @click="blogAgentOpen = false">×</button>
        </header>

        <div class="blog-agent-messages">
          <article
            v-for="(message, index) in blogAgentMessages"
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
          <button v-for="item in blogAgentSuggestions" :key="item" type="button" @click="sendBlogAgentMessage(item)">
            {{ item }}
          </button>
        </div>

        <form class="blog-agent-composer" @submit.prevent="sendBlogAgentMessage()">
          <el-input
            v-model="blogAgentInput"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="问公开博客内容，例如：这个项目架构是什么？"
            @keydown="handleBlogAgentKeydown"
          />
          <el-button type="primary" native-type="submit" :loading="blogAgentLoading">发送</el-button>
        </form>
      </section>
    </section>
  </main>
</template>
