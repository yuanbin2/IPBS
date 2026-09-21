<script setup lang="ts">
import type { ApprovalRequest } from "../types";

defineProps<{
  open: boolean;
  approval: ApprovalRequest | null;
  reviewer: string;
  note: string;
  reviewing: boolean;
}>();

const emit = defineEmits<{
  "update:open": [value: boolean];
  "update:reviewer": [value: string];
  "update:note": [value: string];
  review: [decision: "approve" | "reject"];
}>();
</script>

<template>
  <el-dialog :model-value="open" title="审批对话触发的操作" width="560px" align-center @update:model-value="emit('update:open', $event)">
    <section v-if="approval" class="approval-dialog-body">
      <p>{{ approval.description }}</p>
      <dl>
        <div v-for="(value, key) in approval.payload" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></div>
      </dl>
      <el-input :model-value="reviewer" placeholder="审批人" @update:model-value="emit('update:reviewer', String($event))" />
      <el-input
        :model-value="note"
        placeholder="审批备注"
        type="textarea"
        :rows="3"
        @update:model-value="emit('update:note', String($event))"
      />
    </section>
    <template #footer>
      <el-button :loading="reviewing" @click="emit('review', 'reject')">拒绝</el-button>
      <el-button type="primary" :loading="reviewing" @click="emit('review', 'approve')">批准并执行</el-button>
    </template>
  </el-dialog>
</template>
