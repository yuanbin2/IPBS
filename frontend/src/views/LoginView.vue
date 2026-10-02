<script setup lang="ts">
import { ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Lock, UserFilled } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { useAuthStore } from "../stores/auth";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();
const mode = ref<"login" | "register">(route.query.mode === "register" ? "register" : "login");
const username = ref("");
const password = ref("");
const loading = ref(false);

watch(
  () => route.query.mode,
  (requestedMode) => {
    mode.value = requestedMode === "register" ? "register" : "login";
  }
);

function switchMode(nextMode: "login" | "register") {
  void router.replace({
    path: "/login",
    query: { ...route.query, mode: nextMode === "register" ? "register" : undefined }
  });
}

async function submit() {
  loading.value = true;
  try {
    if (mode.value === "login") {
      await auth.login(username.value, password.value);
      ElMessage.success("登录成功");
    } else {
      await auth.register(username.value, password.value);
      ElMessage.success("注册成功");
    }
    router.replace(typeof route.query.redirect === "string" ? route.query.redirect : "/");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "认证失败");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="auth-page">
    <!-- Brand side -->
    <div class="auth-brand">
      <div class="auth-brand-content">
        <div class="auth-brand-icon">
          <el-icon><Lock /></el-icon>
        </div>
        <h2>智能个人博客系统</h2>
        <p>智能个人博客系统，基于 Agentic RAG 的知识管理与问答，让博客、文档和对话汇聚为统一的知识源。</p>
      </div>
    </div>

    <!-- Form side -->
    <div class="auth-form-side">
      <section class="auth-panel">
        <header>
          <div class="auth-logo">
            <el-icon><Lock /></el-icon>
          </div>
          <p class="eyebrow">智能个人博客系统</p>
          <h1>{{ mode === "login" ? "登录工作台" : "注册账号" }}</h1>
          <p class="auth-mode-description">
            {{ mode === "login" ? "登录后管理文章和私有笔记。" : "创建账号后即可保存文章与私有笔记。" }}
          </p>
        </header>

        <form class="auth-form" @submit.prevent="submit">
          <el-input v-model="username" placeholder="用户名" :prefix-icon="UserFilled" />
          <el-input v-model="password" placeholder="密码，至少 8 位" type="password" show-password :prefix-icon="Lock" />
          <template v-if="mode === 'register'">
            <p class="auth-security-note">新账号默认是访客角色；管理员权限由现有管理员单独授予。</p>
          </template>
          <el-button type="primary" native-type="submit" :loading="loading">
            {{ mode === "login" ? "登录" : "注册并进入" }}
          </el-button>
        </form>

        <div class="auth-switch">
          <span>{{ mode === "login" ? "还没有账号？" : "已有账号？" }}</span>
          <button type="button" @click="switchMode(mode === 'login' ? 'register' : 'login')">
            {{ mode === "login" ? "立即注册" : "返回登录" }}
          </button>
        </div>

        <p class="auth-security-note">
          <el-icon><Lock /></el-icon>
          账号受身份认证、角色权限和 Workspace 数据隔离保护；请勿与他人共享密码或访问令牌。
        </p>
      </section>
    </div>
  </main>
</template>
