<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import AppShell from "./components/AppShell.vue";

const route = useRoute();
const isPublicPage = computed(() => Boolean(route.meta.public));
</script>

<template>
  <RouterView v-if="isPublicPage" />
  <AppShell v-else>
    <RouterView />
  </AppShell>
</template>
