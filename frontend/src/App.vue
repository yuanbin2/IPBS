<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import AppShell from "./components/AppShell.vue";
import { useAuthStore } from "./stores/auth";

const route = useRoute();
const auth = useAuthStore();
const isPublicPage = computed(() => Boolean(route.meta.public) && (route.name !== "blog" || !auth.isAuthenticated));
</script>

<template>
  <RouterView v-if="isPublicPage" />
  <AppShell v-else>
    <RouterView />
  </AppShell>
</template>
