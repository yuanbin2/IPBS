<script setup lang="ts">
defineProps<{ input: string; internetEnabled: boolean; loading: boolean; canSend: boolean }>();
const emit = defineEmits<{
  "update:input": [value: string];
  "update:internetEnabled": [value: boolean];
  send: [];
  stop: [];
  cancel: [];
  keydown: [event: KeyboardEvent];
}>();
</script>

<template>
  <form class="composer" @submit.prevent="emit('send')">
    <el-input
      :model-value="input"
      type="textarea"
      :rows="3"
      resize="none"
      placeholder="向 Agent 提问，例如：帮我计算 12 * 8"
      @update:model-value="emit('update:input', String($event))"
      @keydown="emit('keydown', $event)"
    />
    <div class="composer-actions">
      <el-switch
        :model-value="internetEnabled"
        inline-prompt
        active-text="联网"
        inactive-text="离线"
        aria-label="连接互联网"
        @update:model-value="emit('update:internetEnabled', Boolean($event))"
      />
      <el-button type="primary" native-type="submit" :loading="loading" :disabled="!canSend">发送</el-button>
      <el-button v-if="loading" native-type="button" title="停止接收，后端仍继续执行" @click="emit('stop')">停止接收</el-button>
      <el-button v-if="loading" native-type="button" title="请求后端协作式取消，当前模型调用可能仍在执行" @click="emit('cancel')">请求取消执行</el-button>
    </div>
  </form>
</template>
