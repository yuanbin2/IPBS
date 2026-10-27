<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  ChatDotRound,
  DataAnalysis,
  Files,
  House,
  Lock,
  Menu,
  Operation,
  Tools,
  UploadFilled
} from "@element-plus/icons-vue";
import { useAuthStore } from "../stores/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const sidebarOpen = ref(false);

const navItems = computed(() => [
  { path: "/", label: "概览", icon: House },
  { path: "/blog", label: "博客", icon: Files },
  { path: "/knowledge", label: "知识库", icon: UploadFilled },
  { path: "/chat", label: "对话", icon: ChatDotRound },
  { path: "/mcp-tools", label: "MCP 工具", icon: Tools },
  ...(auth.canViewObservability
    ? [{ path: "/observability", label: "观测评估", icon: DataAnalysis }]
    : []),
  ...(auth.session.role === "admin"
    ? [
        { path: "/admin-approvals", label: "审批", icon: Operation },
        { path: "/security", label: "安全", icon: Lock }
      ]
    : [])
]);

const pageTitle = computed(() => {
  const item = navItems.value.find((nav) => {
    if (nav.path === "/") return route.path === "/";
    return route.path.startsWith(nav.path);
  });
  return item?.label ?? "";
});

const activePath = computed(() => {
  if (route.path.startsWith("/blog")) return "/blog";
  return route.path;
});

async function logout() {
  try {
    await auth.logout();
    await router.replace("/login");
  } catch {
    ElMessage.error("退出未完成，请检查网络后重试。");
  }
}

function toggleSidebar() {
  sidebarOpen.value = !sidebarOpen.value;
}

function closeSidebar() {
  sidebarOpen.value = false;
}
</script>

<template>
  <main class="shell">
    <!-- Mobile hamburger -->
    <button
      class="mobile-nav-toggle"
      type="button"
      aria-label="打开导航菜单"
      @click="toggleSidebar"
    >
      <el-icon><Menu /></el-icon>
    </button>

    <!-- Mobile overlay -->
    <div
      class="sidebar-overlay"
      :class="{ visible: sidebarOpen }"
      @click="closeSidebar"
    />

    <!-- Sidebar -->
    <aside class="sidebar" :class="{ 'sidebar-open': sidebarOpen }">
      <div class="sidebar-header">
        <div class="sidebar-logo">B</div>
        <div class="sidebar-brand">
          <strong>智能个人博客系统</strong>
          <small>Agentic RAG Platform</small>
        </div>
      </div>

      <nav class="nav">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :class="{ active: activePath === item.path }"
          :to="item.path"
          @click="closeSidebar"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <section class="account-box">
        <div class="account-avatar">
          <el-icon><Operation /></el-icon>
        </div>
        <div class="account-info">
          <strong>{{ auth.session.actor }}</strong>
          <span>{{ auth.roleLabel }} / {{ auth.session.workspace_key }}</span>
        </div>
        <button class="account-logout" type="button" @click="logout">退出</button>
      </section>
    </aside>

    <!-- Main workspace -->
    <section class="workspace">
      <header class="topbar">
        <div class="topbar-left">
          <h1>{{ pageTitle }}</h1>
        </div>
        <div class="topbar-right">
          <span style="color: var(--color-text-muted); font-size: var(--font-size-sm);">
            {{ auth.session.actor }}
          </span>
        </div>
      </header>
      <div class="main-content">
        <slot />
      </div>
    </section>
  </main>
</template>
