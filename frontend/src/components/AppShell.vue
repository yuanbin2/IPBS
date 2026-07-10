<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  ChatDotRound,
  DataAnalysis,
  Files,
  House,
  Lock,
  Operation,
  Tools,
  UploadFilled,
  UserFilled
} from "@element-plus/icons-vue";
import { useAuthStore } from "../stores/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const navItems = [
  { path: "/", label: "概览", icon: House },
  { path: "/blog", label: "博客", icon: Files },
  { path: "/knowledge", label: "知识库", icon: UploadFilled },
  { path: "/chat", label: "对话", icon: ChatDotRound },
  { path: "/admin-approvals", label: "审批", icon: Lock },
  { path: "/mcp-tools", label: "MCP 工具", icon: Tools },
  { path: "/observability", label: "观测评估", icon: DataAnalysis },
  { path: "/security", label: "安全", icon: UserFilled }
];

const activePath = computed(() => {
  if (route.path.startsWith("/blog")) return "/blog";
  return route.path;
});

function logout() {
  auth.logout();
  router.replace("/login");
}
</script>

<template>
  <main class="shell">
    <aside class="sidebar">
      <RouterLink class="brand" to="/">Knowledge Agent</RouterLink>
      <nav class="nav">
        <RouterLink v-for="item in navItems" :key="item.path" :class="{ active: activePath === item.path }" :to="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>
      <section class="account-box">
        <el-icon><Operation /></el-icon>
        <div>
          <strong>{{ auth.session.actor }}</strong>
          <span>{{ auth.roleLabel }} / {{ auth.session.workspace_key }}</span>
        </div>
        <button type="button" @click="logout">退出</button>
      </section>
    </aside>
    <section class="workspace">
      <slot />
    </section>
  </main>
</template>
