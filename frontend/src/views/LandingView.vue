<script setup lang="ts">
import { ChatDotRound, DataAnalysis, Files, Right, UploadFilled } from "@element-plus/icons-vue";
import { useRouter } from "vue-router";

const router = useRouter();

const features = [
  {
    title: "个人博客",
    detail: "选择“发布并加入知识库”后，文章才会成为 Agent 的知识来源。",
    icon: Files
  },
  {
    title: "企业知识库",
    detail: "上传 Markdown、txt、PDF，自动切分并建立检索索引。",
    icon: UploadFilled
  },
  {
    title: "智能对话",
    detail: "基于 LangGraph 的多智能体协作，自动路由到最合适的 Agent。",
    icon: ChatDotRound
  },
  {
    title: "Agentic RAG",
    detail: "检索、评分、改写问题、生成答案并给出引用来源。",
    icon: DataAnalysis
  }
];

const stack = ["LangGraph", "Agentic RAG", "pgvector", "多智能体", "RBAC 权限", "审计可观测"];

function goToLogin() {
  router.push("/login");
}

function goToRegister() {
  router.push({ path: "/login", query: { mode: "register" } });
}

function goToBlog() {
  router.push("/blog");
}
</script>

<template>
  <div class="landing-page">
    <!-- Nav -->
    <nav class="landing-nav">
      <div class="landing-nav-inner">
        <div class="landing-brand">
          <span class="landing-brand-mark">B</span>
          <span class="landing-brand-name">智能个人博客系统</span>
        </div>
        <div class="landing-nav-actions">
          <button class="landing-nav-link" type="button" @click="goToBlog">浏览文章</button>
          <button class="landing-nav-link" type="button" @click="goToLogin">登录</button>
          <el-button type="primary" @click="goToRegister">注册账号</el-button>
        </div>
      </div>
    </nav>

    <!-- Hero -->
    <header class="landing-hero">
      <div class="landing-hero-inner">
        <div class="landing-hero-text">
          <div class="landing-badge">Agentic RAG · 知识智能体平台</div>
          <h1>让博客、文档与对话<br />汇聚为统一的知识源</h1>
          <p>
            基于多智能体协作与检索增强生成，将散落的内容沉淀为可对话、可追溯、可治理的组织知识。
          </p>
          <div class="landing-actions">
            <el-button type="primary" size="large" @click="goToBlog">
              浏览公开文章
              <el-icon class="el-icon--right"><Right /></el-icon>
            </el-button>
            <button class="landing-hero-more" type="button" @click="goToRegister">注册账号</button>
          </div>
        </div>

        <!-- Product preview: simulated RAG conversation -->
        <div class="landing-hero-visual">
          <div class="preview-window">
            <div class="preview-titlebar">
              <span class="preview-dot" />
              <span class="preview-dot" />
              <span class="preview-dot" />
              <span class="preview-title">知识助手</span>
            </div>
            <div class="preview-body">
              <div class="preview-msg preview-msg--user">如何做好团队知识管理？</div>
              <div class="preview-msg preview-msg--agent">
                <p>知识管理的核心是把「人的经验」转化为「可检索的资产」。建议从三点入手：</p>
                <p class="preview-list">1. 统一沉淀：文档、博客、对话统一入库<br />2. 语义检索：向量召回 + 关键词混合打分<br />3. 持续治理：审批、审计与效果评估</p>
                <div class="preview-sources">
                  <span class="preview-source">文档 · 知识管理实践</span>
                  <span class="preview-source">博客 · 团队协作</span>
                </div>
              </div>
              <div class="preview-composer">
                <span class="preview-composer-text">继续提问…</span>
                <span class="preview-composer-send">↵</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </header>

    <!-- Features -->
    <section class="landing-features">
      <div class="landing-features-inner">
        <div class="landing-section-head">
          <span class="landing-eyebrow">核心能力</span>
          <h2>一站式知识管理</h2>
          <p>从内容创作到智能问答，覆盖知识全生命周期</p>
        </div>
        <div class="landing-feature-grid">
          <div v-for="item in features" :key="item.title" class="landing-feature-card">
            <div class="landing-feature-icon">
              <el-icon :size="24"><component :is="item.icon" /></el-icon>
            </div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.detail }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Tech strip -->
    <section class="landing-tech">
      <div class="landing-tech-inner">
        <span class="landing-tech-label">技术底座</span>
        <ul class="landing-tech-list">
          <li v-for="item in stack" :key="item">{{ item }}</li>
        </ul>
      </div>
    </section>

    <!-- CTA -->
    <section class="landing-cta">
      <div class="landing-cta-inner">
        <h2>准备好开始了吗？</h2>
        <p>注册账号，把文章与笔记沉淀为可检索的知识。</p>
        <el-button type="primary" size="large" @click="goToRegister">立即注册</el-button>
      </div>
    </section>

    <!-- Footer -->
    <footer class="landing-footer">
      <p>智能个人博客系统 · Agentic RAG 知识管理</p>
    </footer>
  </div>
</template>

<style scoped>
.landing-page {
  min-height: 100vh;
  background: var(--color-bg-page, #f4f6f5);
  color: var(--color-text-primary, #1a2623);
}

/* --- Nav --- */
.landing-nav {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(18, 43, 40, 0.92);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.landing-nav-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1200px;
  margin: 0 auto;
  padding: 14px 32px;
}

.landing-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.landing-brand-mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--color-primary);
  color: #fff;
  font-weight: 700;
  font-size: 16px;
}

.landing-brand-name {
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.landing-nav-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

.landing-nav-link {
  border: 0;
  background: transparent;
  color: rgba(255, 255, 255, 0.8);
  cursor: pointer;
  font-size: 14px;
  padding: 6px 4px;
}

.landing-nav-link:hover {
  color: #fff;
}

/* --- Hero --- */
.landing-hero {
  position: relative;
  overflow: hidden;
  background:
    radial-gradient(120% 120% at 80% -20%, rgba(175, 138, 63, 0.16) 0%, transparent 55%),
    linear-gradient(160deg, #174b46 0%, #123d39 55%, #0e312d 100%);
  color: #fff;
}

.landing-hero::after {
  content: "";
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
  background-size: 48px 48px;
  pointer-events: none;
  mask-image: radial-gradient(80% 80% at 20% 0%, #000 0%, transparent 100%);
}

.landing-hero-inner {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1200px;
  margin: 0 auto;
  padding: 88px 32px 96px;
  gap: 56px;
}

.landing-hero-text {
  flex: 1;
  max-width: 560px;
}

.landing-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  color: #d8e4e0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 24px;
}

.landing-hero h1 {
  margin: 0 0 20px;
  font-size: 44px;
  line-height: 1.22;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #fff;
}

.landing-hero-text p {
  margin: 0 0 36px;
  font-size: 17px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.78);
  max-width: 480px;
}

.landing-actions {
  display: flex;
  align-items: center;
  gap: 20px;
}

.landing-hero-more {
  border: 0;
  background: transparent;
  color: rgba(255, 255, 255, 0.82);
  cursor: pointer;
  font-size: 15px;
  padding: 8px 2px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.4);
}

.landing-hero-more:hover {
  color: #fff;
  border-bottom-color: #fff;
}

/* --- Hero visual: product preview --- */
.landing-hero-visual {
  flex: 0 0 420px;
}

.preview-window {
  background: var(--color-bg-surface, #fdfefd);
  border-radius: 12px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.32);
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.preview-titlebar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-divider, #e9eeec);
  background: var(--color-bg-page, #f4f6f5);
}

.preview-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-border);
}

.preview-dot:nth-child(1) {
  background: #d98c8c;
}
.preview-dot:nth-child(2) {
  background: #d9b98c;
}
.preview-dot:nth-child(3) {
  background: #9cc9a8;
}

.preview-title {
  margin-left: 10px;
  color: var(--color-text-secondary, #55655f);
  font-size: 13px;
  font-weight: 600;
}

.preview-body {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 320px;
}

.preview-msg {
  max-width: 85%;
  padding: 12px 16px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.65;
}

.preview-msg--user {
  align-self: flex-end;
  background: var(--color-primary, #174b46);
  color: #ffffff;
  border-bottom-right-radius: 4px;
}

.preview-msg--agent {
  align-self: flex-start;
  background: #ffffff;
  border: 1px solid var(--color-border, #dce4e1);
  color: var(--color-text-primary, #1a2623);
  border-bottom-left-radius: 4px;
}

.preview-msg--agent p {
  margin: 0 0 8px;
  color: var(--color-text-primary, #1a2623);
}

.preview-list {
  color: #2f3d38;
  font-weight: 500;
}

.preview-sources {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--color-divider);
}

.preview-source {
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--color-primary-soft, #e9f1ef);
  color: var(--color-primary, #174b46);
  font-size: 12px;
  font-weight: 600;
}

.preview-composer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
  padding: 10px 14px;
  border: 1px solid var(--color-border, #dce4e1);
  border-radius: 8px;
  color: var(--color-text-muted, #828f8b);
  font-size: 13px;
}

.preview-composer-send {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: var(--color-primary);
  color: #fff;
  font-size: 13px;
}

/* --- Features --- */
.landing-features {
  padding: 96px 32px;
  background: var(--color-bg-page);
}

.landing-features-inner {
  max-width: 1200px;
  margin: 0 auto;
}

.landing-section-head {
  margin-bottom: 56px;
}

.landing-eyebrow {
  display: block;
  color: var(--color-accent);
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  margin-bottom: 12px;
}

.landing-section-head h2 {
  margin: 0 0 10px;
  font-size: 32px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--color-text-primary);
}

.landing-section-head p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 16px;
}

.landing-feature-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--color-border);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  overflow: hidden;
}

.landing-feature-card {
  background: var(--color-bg-surface);
  padding: 36px 32px;
  transition: background var(--transition-base);
}

.landing-feature-card:hover {
  background: var(--color-primary-soft);
}

.landing-feature-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 10px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  margin-bottom: 24px;
}

.landing-feature-card h3 {
  margin: 0 0 10px;
  font-size: 17px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.landing-feature-card p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.7;
}

/* --- Tech strip --- */
.landing-tech {
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-surface);
}

.landing-tech-inner {
  display: flex;
  align-items: center;
  gap: 32px;
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 32px;
}

.landing-tech-label {
  flex-shrink: 0;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.landing-tech-list {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.landing-tech-list li {
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 500;
  padding: 4px 0;
}

.landing-tech-list li:not(:last-child)::after {
  content: "";
  display: inline-block;
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--color-border);
  margin-left: 12px;
  vertical-align: middle;
}

/* --- CTA --- */
.landing-cta {
  background:
    radial-gradient(80% 120% at 50% 0%, rgba(175, 138, 63, 0.12) 0%, transparent 60%),
    var(--color-bg-sidebar);
  padding: 96px 32px;
  text-align: center;
}

.landing-cta-inner {
  max-width: 640px;
  margin: 0 auto;
}

.landing-cta h2 {
  margin: 0 0 12px;
  font-size: 32px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #fff;
}

.landing-cta p {
  margin: 0 0 32px;
  color: rgba(255, 255, 255, 0.72);
  font-size: 16px;
}

/* --- Footer --- */
.landing-footer {
  background: var(--color-bg-sidebar);
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding: 24px 32px;
  text-align: center;
}

.landing-footer p {
  margin: 0;
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
}

/* --- Responsive --- */
@media (max-width: 900px) {
  .landing-hero-inner {
    flex-direction: column;
    align-items: flex-start;
    padding: 56px 24px 64px;
  }

  .landing-hero h1 {
    font-size: 34px;
  }

  .landing-hero-visual {
    flex: none;
    width: 100%;
  }

  .landing-feature-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .landing-hero h1 {
    font-size: 28px;
  }

  .landing-feature-grid {
    grid-template-columns: 1fr;
  }

  .landing-tech-inner {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }

  .landing-nav-inner {
    padding: 12px 20px;
  }
}
</style>
