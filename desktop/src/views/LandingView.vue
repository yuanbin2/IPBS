<script setup lang="ts">
import { ChatDotRound, DataAnalysis, Files, Right, UploadFilled } from "@element-plus/icons-vue";
import { useRouter } from "vue-router";

const router = useRouter();

const features = [
  {
    title: "个人博客",
    detail: "文章发布后自动进入知识库，成为 Agent 的个人经历来源。",
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

function goToLogin() {
  router.push("/login");
}
</script>

<template>
  <div class="landing-page">
    <!-- Hero -->
    <header class="landing-hero">
      <div class="landing-hero-inner">
        <div class="landing-hero-text">
          <div class="landing-badge">Enterprise AI Platform</div>
          <h1>企业知识智能体平台</h1>
          <p>
            基于 Agentic RAG 的智能知识管理，让博客、文档和对话汇聚为统一的知识源。
          </p>
          <div class="landing-actions">
            <el-button type="primary" size="large" @click="goToLogin">
              开始使用
              <el-icon class="el-icon--right"><Right /></el-icon>
            </el-button>
          </div>
        </div>
        <div class="landing-hero-visual">
          <div class="landing-visual-card">
            <el-icon :size="48"><ChatDotRound /></el-icon>
            <span>AI Agent</span>
          </div>
        </div>
      </div>
    </header>

    <!-- Features -->
    <section class="landing-features">
      <div class="landing-features-inner">
        <h2>核心功能</h2>
        <p class="landing-section-desc">一站式解决企业知识管理和智能问答需求</p>
        <div class="landing-feature-grid">
          <div v-for="item in features" :key="item.title" class="landing-feature-card">
            <div class="landing-feature-icon">
              <el-icon :size="28"><component :is="item.icon" /></el-icon>
            </div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.detail }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- CTA -->
    <section class="landing-cta">
      <h2>准备好开始了吗？</h2>
      <p>立即登录，体验智能知识管理平台</p>
      <el-button type="primary" size="large" @click="goToLogin">
        立即登录
      </el-button>
    </section>

    <!-- Footer -->
    <footer class="landing-footer">
      <p>&copy; 2025 企业知识智能体平台</p>
    </footer>
  </div>
</template>

<style scoped>
.landing-page {
  min-height: 100vh;
  background: var(--color-bg-page);
}

/* Hero */
.landing-hero {
  background: var(--color-primary);
  color: #ffffff;
  padding: 80px 40px 60px;
}

.landing-hero-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1200px;
  margin: 0 auto;
  gap: 60px;
}

.landing-hero-text {
  flex: 1;
}

.landing-badge {
  display: inline-block;
  padding: 6px 16px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 20px;
}

.landing-hero h1 {
  font-size: 44px;
  font-weight: 700;
  margin: 0 0 16px;
  line-height: 1.2;
  color: #ffffff;
}

.landing-hero p {
  font-size: 18px;
  opacity: 0.85;
  margin: 0 0 32px;
  line-height: 1.6;
}

.landing-actions {
  display: flex;
  gap: 16px;
}

.landing-hero-visual {
  flex: 0 0 280px;
}

.landing-visual-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 48px;
  text-align: center;
  border: 1px solid rgba(255, 255, 255, 0.15);
}

.landing-visual-card span {
  font-size: 22px;
  font-weight: 600;
}

/* Features */
.landing-features {
  background: var(--color-bg-surface);
  padding: 80px 40px;
}

.landing-features-inner {
  max-width: 1200px;
  margin: 0 auto;
}

.landing-features h2 {
  text-align: center;
  font-size: 32px;
  margin: 0 0 12px;
  color: var(--color-text-primary);
}

.landing-section-desc {
  text-align: center;
  color: var(--color-text-secondary);
  font-size: 16px;
  margin: 0 0 48px;
}

.landing-feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 24px;
}

.landing-feature-card {
  border: 1px solid var(--color-border);
  border-radius: 10px;
  padding: 32px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.landing-feature-card:hover {
  border-color: var(--color-primary-border);
  box-shadow: 0 4px 16px rgba(39, 102, 120, 0.08);
}

.landing-feature-icon {
  width: 52px;
  height: 52px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  margin-bottom: 20px;
}

.landing-feature-card h3 {
  font-size: 18px;
  margin: 0 0 10px;
  color: var(--color-text-primary);
}

.landing-feature-card p {
  color: var(--color-text-secondary);
  margin: 0;
  line-height: 1.6;
  font-size: 14px;
}

/* CTA */
.landing-cta {
  background: var(--color-primary);
  padding: 80px 40px;
  text-align: center;
  color: #ffffff;
}

.landing-cta h2 {
  font-size: 32px;
  margin: 0 0 12px;
  color: #ffffff;
}

.landing-cta p {
  font-size: 17px;
  opacity: 0.85;
  margin: 0 0 32px;
}

/* Footer */
.landing-footer {
  background: var(--color-bg-sidebar);
  color: rgba(255, 255, 255, 0.6);
  padding: 24px 40px;
  text-align: center;
  font-size: 14px;
}

.landing-footer p {
  margin: 0;
}

/* Responsive */
@media (max-width: 768px) {
  .landing-hero {
    padding: 60px 20px 40px;
  }

  .landing-hero-inner {
    flex-direction: column;
    text-align: center;
  }

  .landing-hero h1 {
    font-size: 32px;
  }

  .landing-actions {
    justify-content: center;
  }

  .landing-hero-visual {
    flex: none;
    width: 100%;
  }

  .landing-visual-card {
    padding: 32px;
  }

  .landing-features {
    padding: 60px 20px;
  }

  .landing-cta {
    padding: 60px 20px;
  }
}
</style>
