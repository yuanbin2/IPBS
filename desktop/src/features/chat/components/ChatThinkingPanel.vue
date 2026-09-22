<script setup lang="ts">
import { ref, watch, computed } from "vue";
import { ArrowDown, ArrowRight, Loading } from "@element-plus/icons-vue";

const props = defineProps<{
  traces: string[];
  isStreaming: boolean;
  isComplete: boolean;
}>();

const expanded = ref(true);

// Auto-collapse when streaming completes
watch(
  () => props.isComplete,
  (complete) => {
    if (complete && props.traces.length > 0) {
      setTimeout(() => { expanded.value = false; }, 800);
    }
  }
);

// Auto-expand when new traces arrive during streaming
watch(
  () => props.traces.length,
  () => {
    if (props.isStreaming) {
      expanded.value = true;
    }
  }
);

const displayTraces = computed(() => {
  return [...new Set(props.traces)];
});
</script>

<template>
  <section v-if="traces.length > 0" class="thinking-panel">
    <button
      class="thinking-toggle"
      type="button"
      @click="expanded = !expanded"
    >
      <el-icon>
        <Loading v-if="isStreaming" class="thinking-spinner" />
        <ArrowDown v-else-if="expanded" />
        <ArrowRight v-else />
      </el-icon>
      <span>
        {{ isStreaming ? "正在思考..." : `思考过程 (${displayTraces.length} 步)` }}
      </span>
    </button>

    <Transition name="thinking-expand">
      <div v-show="expanded" class="thinking-content">
        <div
          v-for="(trace, index) in displayTraces"
          :key="trace + index"
          class="thinking-step"
          :class="{ 'thinking-step-latest': isStreaming && index === displayTraces.length - 1 }"
        >
          <span class="thinking-step-dot" />
          <span class="thinking-step-text">{{ trace }}</span>
        </div>
      </div>
    </Transition>
  </section>
</template>