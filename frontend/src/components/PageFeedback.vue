<script setup lang="ts">
defineProps<{
  tone: "loading" | "empty" | "error" | "partial";
  title: string;
  nextStep: string;
  actionLabel?: string;
}>();

defineEmits<{ action: [] }>();
</script>

<template>
  <section class="page-feedback" :class="`page-feedback--${tone}`" :role="tone === 'error' ? 'alert' : 'status'">
    <strong>{{ title }}</strong>
    <p>{{ nextStep }}</p>
    <el-button v-if="actionLabel" type="primary" plain @click="$emit('action')">{{ actionLabel }}</el-button>
  </section>
</template>
