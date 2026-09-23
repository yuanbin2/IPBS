<script setup lang="ts">
import { computed, ref, nextTick, watch, onMounted } from "vue";
import { ChatDotRound, Delete, ArrowLeft, Loading, View } from "@element-plus/icons-vue";
import { MdPreview, type HeadList } from "md-editor-v3";
import type { BlogArticle } from "../types";
import { useThemeStore } from "../stores/themeStore";
import { applyThemeToElement } from "../themes/applyTheme";
import ThemeSwitcher from "./ThemeSwitcher.vue";
import ThemeCreator from "./ThemeCreator.vue";

const props = defineProps<{
  article: BlogArticle;
  commentDraft: { author_name: string; content: string };
  publishing: boolean;
  submittingComment: boolean;
  deletingSlug: string;
  relatedArticles: BlogArticle[];
  relatedLoading: boolean;
}>();

defineEmits<{
  back: [];
  askAgent: [article: BlogArticle];
  sync: [article: BlogArticle];
  remove: [article: BlogArticle];
  submitComment: [article: BlogArticle];
  openRelated: [article: BlogArticle];
}>();

const headings = ref<HeadList[]>([]);
const activeHeadingIndex = ref(0);
const contentRef = ref<HTMLElement>();
const collapsedSections = ref<Set<number>>(new Set());
const themeStore = useThemeStore();
const articleThemeRef = ref<HTMLElement>();
const readingProgress = ref(0);

const readingMinutes = computed(() => {
  const text = (props.article.content || "").replace(/```[\s\S]*?```/g, "").replace(/\s+/g, "");
  return Math.max(1, Math.ceil(text.length / 450));
});

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric"
  }).format(new Date(dateStr));
}

function handleArticleScroll(event: Event) {
  const element = event.currentTarget as HTMLElement;
  const scrollable = element.scrollHeight - element.clientHeight;
  readingProgress.value = scrollable > 0 ? Math.min(100, Math.round((element.scrollTop / scrollable) * 100)) : 100;
}

// Apply theme to article content
function applyCurrentTheme() {
  if (articleThemeRef.value) {
    applyThemeToElement(articleThemeRef.value, themeStore.currentTheme);
  }
}

// Watch for theme changes
watch(() => themeStore.currentTheme, () => {
  applyCurrentTheme();
}, { deep: true });

onMounted(() => {
  applyCurrentTheme();
});

// 自定义标题 ID 生成函数
function generateHeadingId(options: { text: string; level: number; index: number }) {
  return `heading-${options.index}`;
}

// 获取目录
function handleGetCatalog(list: HeadList[]) {
  headings.value = list;
  nextTick(() => applyCollapsibleSections());
}

// 跳转到标题
function scrollToHeading(item: HeadList, index: number) {
  activeHeadingIndex.value = index;
  const headingId = `heading-${index}`;
  const element = document.getElementById(headingId);
  if (element) {
    element.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

// 应用折叠功能到所有标题 (H1-H6)
function applyCollapsibleSections() {
  if (!contentRef.value) return;

  // 清理旧的折叠包装器
  contentRef.value.querySelectorAll('.collapsible-section-wrapper').forEach(wrapper => {
    const parent = wrapper.parentNode;
    if (!parent) return;
    while (wrapper.firstChild) {
      parent.insertBefore(wrapper.firstChild, wrapper);
    }
    parent.removeChild(wrapper);
  });

  // 移除旧的折叠按钮
  contentRef.value.querySelectorAll('.section-toggle-btn').forEach(btn => btn.remove());

  const previewEl = contentRef.value.querySelector('.md-editor-preview');
  if (!previewEl) return;

  // 找到所有标题 (H1-H6)
  const allHeadings = previewEl.querySelectorAll('h1, h2, h3, h4, h5, h6');
  if (allHeadings.length < 2) return; // 只有一个或没有标题时不添加折叠

  // 获取标题级别 (1-6)
  function getHeadingLevel(el: Element): number {
    return parseInt(el.tagName.charAt(1));
  }

  let sectionIndex = 0;

  allHeadings.forEach((heading) => {
    const currentLevel = getHeadingLevel(heading);

    // 收集此标题到下一个同级或更高级标题之间的所有元素
    const sectionContent: Element[] = [];
    let nextSibling = heading.nextElementSibling;

    while (nextSibling) {
      // 如果遇到标题，检查级别
      if (/^H[1-6]$/.test(nextSibling.tagName)) {
        const nextLevel = getHeadingLevel(nextSibling);
        // 如果下一个标题级别 <= 当前级别 (更高级或同级)，停止收集
        if (nextLevel <= currentLevel) break;
      }
      sectionContent.push(nextSibling);
      nextSibling = nextSibling.nextElementSibling;
    }

    // 只有当有内容可折叠时才添加按钮
    if (sectionContent.length === 0) return;

    const currentIndex = sectionIndex++;

    // 创建折叠按钮
    const toggleBtn = document.createElement('button');
    toggleBtn.className = `section-toggle-btn level-${currentLevel}`;
    toggleBtn.setAttribute('data-section-index', String(currentIndex));
    toggleBtn.innerHTML = `<span class="toggle-icon">${collapsedSections.value.has(currentIndex) ? '▶' : '▼'}</span>`;
    toggleBtn.title = collapsedSections.value.has(currentIndex) ? '展开此章节' : '折叠此章节';

    // 添加点击事件
    toggleBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleSection(currentIndex);
    });

    // 在标题前插入按钮
    heading.insertBefore(toggleBtn, heading.firstChild);
    heading.classList.add('collapsible-heading');

    // 创建包裹器
    const wrapper = document.createElement('div');
    wrapper.className = `collapsible-section-wrapper${collapsedSections.value.has(currentIndex) ? ' collapsed' : ''}`;
    wrapper.setAttribute('data-section-index', String(currentIndex));

    // 将内容移入包裹器
    const parent = heading.parentNode;
    if (parent) {
      parent.insertBefore(wrapper, heading.nextSibling);
      sectionContent.forEach(el => wrapper.appendChild(el));
    }
  });
}

// 切换章节折叠状态
function toggleSection(index: number) {
  if (collapsedSections.value.has(index)) {
    collapsedSections.value.delete(index);
  } else {
    collapsedSections.value.add(index);
  }

  // 直接操作 DOM 更新状态
  if (!contentRef.value) return;

  const wrapper = contentRef.value.querySelector(`.collapsible-section-wrapper[data-section-index="${index}"]`);
  const toggleBtn = contentRef.value.querySelector(`.section-toggle-btn[data-section-index="${index}"] .toggle-icon`);

  if (wrapper) {
    wrapper.classList.toggle('collapsed');
  }
  if (toggleBtn) {
    toggleBtn.textContent = collapsedSections.value.has(index) ? '▶' : '▼';
  }
}

// 监听文章内容变化，重新应用折叠
watch(() => props.article.content, () => {
  collapsedSections.value.clear();
  nextTick(() => applyCollapsibleSections());
});

function excerpt(text: string, maxLen = 60): string {
  if (!text) return "";
  return text.length > maxLen ? text.slice(0, maxLen) + "..." : text;
}
</script>

<template>
  <section class="article-detail-fullscreen">
    <div class="reading-progress" aria-hidden="true">
      <span :style="{ width: `${readingProgress}%` }" />
    </div>
    <!-- 顶部导航栏 -->
    <header class="article-header">
      <button class="back-button" type="button" @click="$emit('back')">
        <el-icon><ArrowLeft /></el-icon>
        返回文章列表
      </button>
      <div class="article-header-context">
        <strong>技术文章</strong>
        <span>/</span>
        <span>{{ article.category?.name || "未分类" }}</span>
      </div>
      <div class="article-actions-bar">
        <ThemeSwitcher />
        <el-button type="primary" :icon="ChatDotRound" @click="$emit('askAgent', article)">让 Agent 总结</el-button>
        <el-button
          v-if="!article.knowledge_document_id"
          :loading="publishing"
          @click="$emit('sync', article)"
        >
          同步到知识库
        </el-button>
        <el-button
          type="danger"
          plain
          :icon="Delete"
          :loading="deletingSlug === article.slug"
          @click="$emit('remove', article)"
        >
          删除
        </el-button>
      </div>
    </header>

    <!-- 主内容区域 -->
    <div class="article-content-wrapper">
      <!-- 左侧大纲 -->
      <aside class="article-outline" v-if="headings.length">
        <div class="outline-header">
          <span>本文目录</span>
          <small>{{ headings.length }} 节</small>
        </div>
        <nav class="outline-nav">
          <a
            v-for="(item, index) in headings"
            :key="index"
            :class="['outline-item', `level-${item.level}`, { active: activeHeadingIndex === index }]"
            @click="scrollToHeading(item, index)"
          >
            {{ item.text }}
          </a>
        </nav>
      </aside>

      <!-- 右侧文章内容 -->
      <main class="article-main" ref="contentRef" @scroll="handleArticleScroll">
        <div ref="articleThemeRef" class="article-theme-container">
          <div class="article-breadcrumb">
            <span>文章</span><b>/</b><strong>{{ article.category?.name || "未分类" }}</strong>
          </div>
          <h1 class="article-title">{{ article.title }}</h1>
          <p class="article-summary" v-if="article.summary">{{ article.summary }}</p>
          <div class="article-byline">
            <div class="author-avatar">{{ (article.author_name || "匿").charAt(0).toUpperCase() }}</div>
            <div class="author-copy">
              <strong>{{ article.author_name || "匿名作者" }}</strong>
              <span>{{ formatDate(article.published_at || article.created_at) }} · 约 {{ readingMinutes }} 分钟阅读</span>
            </div>
            <div class="article-metrics">
              <span><el-icon><View /></el-icon>{{ article.view_count }} 浏览</span>
              <span>{{ article.comment_count }} 评论</span>
              <span v-if="article.knowledge_document_id" class="knowledge-status">已收录知识库</span>
            </div>
          </div>

          <div class="tag-row article-tags" v-if="article.tags.length">
            <span v-for="tag in article.tags" :key="tag.id"># {{ tag.name }}</span>
          </div>

          <div class="article-cover" v-if="article.cover_image">
            <img :src="article.cover_image" :alt="article.title" />
          </div>

          <MdPreview
            :model-value="article.content || ''"
            language="zh-CN"
            preview-theme="github"
            code-theme="github"
            :show-code-row-number="true"
            :md-heading-id="generateHeadingId"
            @onGetCatalog="handleGetCatalog"
            class="article-content blog-md-preview"
          />
        </div>

        <!-- 相关推荐 -->
        <section class="related-articles" v-if="relatedArticles.length">
          <h3>相关推荐</h3>
          <div class="related-grid">
            <article
              v-for="related in relatedArticles"
              :key="related.id"
              class="related-card"
              @click="$emit('openRelated', related)"
            >
              <div class="related-cover" v-if="related.cover_image">
                <img :src="related.cover_image" :alt="related.title" loading="lazy" />
              </div>
              <div class="related-cover placeholder" v-else>
                <span>{{ related.title.charAt(0) }}</span>
              </div>
              <div class="related-info">
                <h4>{{ related.title }}</h4>
                <p>{{ excerpt(related.summary) }}</p>
                <footer>
                  <span v-if="related.category">{{ related.category.name }}</span>
                  <span>{{ related.view_count }} 浏览</span>
                </footer>
              </div>
            </article>
          </div>
        </section>

        <div class="related-loading" v-if="relatedLoading">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>正在加载推荐...</span>
        </div>

        <!-- 评论区 -->
        <section class="comment-section">
          <h3>评论</h3>
          <article v-for="comment in article.comments" :key="comment.id" class="comment-item">
            <strong>{{ comment.author_name }}</strong>
            <p>{{ comment.content }}</p>
          </article>
          <form class="comment-form" @submit.prevent="$emit('submitComment', article)">
            <el-input v-model="commentDraft.author_name" placeholder="昵称" />
            <el-input v-model="commentDraft.content" type="textarea" :rows="3" placeholder="写下你的想法" />
            <el-button type="primary" native-type="submit" :loading="submittingComment">发表评论</el-button>
          </form>
        </section>
      </main>
    </div>
  </section>

  <ThemeCreator />
</template>
