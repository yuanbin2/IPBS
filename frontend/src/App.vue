<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import AppShell from "./components/AppShell.vue";
import { useAuthStore } from "./stores/auth";
import { shouldRenderWithoutShell } from "./router/shellVisibility";

const route = useRoute();
const auth = useAuthStore();

// 公开页面默认裸渲染给未登录访客；但已登录访问 /blog 系列时必须保留外壳，
// 否则领域目录等页面会丢失左侧导航、用户无法返回博客（B-058）。
const isPublicPage = computed(() =>
  shouldRenderWithoutShell({
    isPublic: Boolean(route.meta.public),
    path: route.path,
    isAuthenticated: auth.isAuthenticated,
  }),
);
</script>

<template>
  <RouterView v-if="isPublicPage" />
  <AppShell v-else>
    <RouterView />
  </AppShell>
</template>
