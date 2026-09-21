<script setup lang="ts">
import { ChatDotRound, Connection, DataAnalysis, Files, UploadFilled, Right } from "@element-plus/icons-vue";
import { useRouter } from "vue-router";

const router = useRouter();

const features = [
  {
    title: "个人博客",
    detail: "文章发布后自动进入知识库，成为 Agent 的个人经历来源。",
    icon: Files,
    color: "#409eff"
  },
  {
    title: "企业知识库",
    detail: "上传 Markdown、txt、PDF，自动切分并建立检索索引。",
    icon: UploadFilled,
    color: "#67c23a"
  },
  {
    title: "智能对话",
    detail: "基于 LangGraph 的多智能体协作，自动路由到最合适的 Agent。",
    icon: ChatDotRound,
    color: "#909399"
  },
  {
    title: "Agentic RAG",
    detail: "检索、评分、改写问题、生成答案并给出引用来源。",
    icon: DataAnalysis,
    color: "#e6a23c"
  }
];

function goToLogin() {
  router.push("/login");
}
</script>

<template>
  <div class="landing-page">
    <!-- Hero Section -->
    <header class="hero">
      <div class="hero-content">
        <div class="hero-badge">Enterprise AI Platform</div>
        <h1>企业知识智能体平台</h1>
        <p class="hero-subtitle">
          基于 Agentic RAG 的智能知识管理，让博客、文档和对话汇聚为统一的知识源。
        </p>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="goToLogin">
            开始使用
            <el-icon class="el-icon--right"><Right /></el-icon>
          </el-button>
        </div>
      </div>
      <div class="hero-visual">
        <div class="visual-card">
          <div class="visual-icon">
            <el-icon :size="48"><Connection /></el-icon>
          </div>
          <div class="visual-text">AI Agent</div>
        </div>
      </div>
    </header>

    <!-- Features Section -->
    <section class="features">
      <h2>核心功能</h2>
      <p class="section-desc">一站式解决企业知识管理和智能问答需求</p>
      <div class="feature-grid">
        <div v-for="item in features" :key="item.title" class="feature-card">
          <div class="feature-icon" :style="{ background: item.color + '15', color: item.color }">
            <el-icon :size="28"><component :is="item.icon" /></el-icon>
          </div>
          <h3>{{ item.title }}</h3>
          <p>{{ item.detail }}</p>
        </div>
      </div>
    </section>

    <!-- CTA Section -->
    <section class="cta">
      <h2>准备好开始了吗？</h2>
      <p>立即登录，体验智能知识管理平台</p>
      <el-button type="primary" size="large" @click="goToLogin">
        立即登录
      </el-button>
    </section>

    <!-- Footer -->
    <footer class="landing-footer">
      <p>© 2025 企业知识智能体平台</p>
    </footer>
  </div>
</template>

<style scoped>
.landing-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}

/* Hero Section */
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1200px;
  margin: 0 auto;
  padding: 80px 40px 60px;
  gap: 60px;
}

.hero-content {
  flex: 1;
}

.hero-badge {
  display: inline-block;
  padding: 6px 16px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  font-size: 14px;
  margin-bottom: 20px;
  backdrop-filter: blur(10px);
}

.hero h1 {
  font-size: 48px;
  font-weight: 700;
  margin: 0 0 16px;
  line-height: 1.2;
}

.hero-subtitle {
  font-size: 18px;
  opacity: 0.9;
  margin: 0 0 32px;
  line-height: 1.6;
}

.hero-actions {
  display: flex;
  gap: 16px;
}

.hero-visual {
  flex: 0 0 300px;
}

.visual-card {
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(20px);
  border-radius: 24px;
  padding: 60px;
  text-align: center;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.visual-icon {
  margin-bottom: 16px;
}

.visual-text {
  font-size: 24px;
  font-weight: 600;
}

/* Features Section */
.features {
  background: #f5f7fa;
  padding: 80px 40px;
  color: #333;
}

.features h2,
.tech-stack h2,
.cta h2 {
  text-align: center;
  font-size: 36px;
  margin: 0 0 16px;
}

.section-desc {
  text-align: center;
  color: #666;
  font-size: 16px;
  margin: 0 0 48px;
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.feature-card {
  background: #fff;
  border-radius: 16px;
  padding: 32px;
  transition: transform 0.3s, box-shadow 0.3s;
}

.feature-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.1);
}

.feature-icon {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
}

.feature-card h3 {
  font-size: 20px;
  margin: 0 0 12px;
  color: #333;
}

.feature-card p {
  color: #666;
  margin: 0;
  line-height: 1.6;
}

/* CTA Section */
.cta {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 80px 40px;
  text-align: center;
}

.cta p {
  font-size: 18px;
  opacity: 0.9;
  margin: 0 0 32px;
}

/* Footer */
.landing-footer {
  background: #1a1a2e;
  color: rgba(255, 255, 255, 0.7);
  padding: 24px 40px;
  text-align: center;
  font-size: 14px;
}

.landing-footer p {
  margin: 0;
}

/* Responsive */
@media (max-width: 768px) {
  .hero {
    flex-direction: column;
    padding: 60px 20px 40px;
    text-align: center;
  }

  .hero h1 {
    font-size: 32px;
  }

  .hero-actions {
    justify-content: center;
  }

  .hero-visual {
    flex: none;
    width: 100%;
  }

  .visual-card {
    padding: 40px;
  }

  .feature-grid {
    grid-template-columns: 1fr;
  }
}
</style>
