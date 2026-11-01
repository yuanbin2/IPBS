<script setup lang="ts">
import type { ImportConflict } from "../api/archiveApi";
import type { ImportPlan, ImportSummary } from "../utils/archiveTransfer";

defineProps<{
  file: File | null;
  plan: ImportPlan | null;
  busy: boolean;
  applying: boolean;
  summary: ImportSummary;
}>();
const open = defineModel<boolean>("open", { required: true });
const conflict = defineModel<ImportConflict>("conflict", { required: true });
const emit = defineEmits<{
  "pick-file": [event: Event];
  apply: [];
}>();
</script>

<template>
  <el-dialog v-model="open" title="导入领域压缩包" width="560px">
    <p class="import-hint">
      选择本系统导出的 .zip 包。导入会重建领域结构、文章与图片；已存在的同名文章默认跳过，可在下面调整冲突策略。
    </p>
    <div class="import-pick">
      <input
        type="file"
        accept=".zip"
        aria-label="选择领域压缩包"
        class="import-file"
        @change="emit('pick-file', $event)"
      />
      <span v-if="file" class="section-hint">已选择：{{ file.name }}</span>
    </div>

    <div v-if="busy" class="import-plan">正在解析压缩包…</div>
    <div v-else-if="plan" class="import-plan">
      <p v-for="(line, index) in summary.lines" :key="index" class="import-line">{{ line }}</p>
      <p v-for="(warning, index) in summary.warnings" :key="`w-${index}`" class="import-warning">
        ⚠ {{ warning }}
      </p>
      <el-radio-group v-model="conflict" size="small" aria-label="冲突策略">
        <el-radio-button value="skip">跳过已存在</el-radio-button>
        <el-radio-button value="rename">改名后新建</el-radio-button>
        <el-radio-button value="replace">覆盖已有</el-radio-button>
      </el-radio-group>
    </div>

    <template #footer>
      <el-button @click="open = false">取消</el-button>
      <el-button type="primary" :loading="applying" :disabled="!plan || busy" @click="emit('apply')">
        确认导入
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.section-hint { color: #8a9793; font-size: 12px; }
.import-hint { margin: 0 0 10px; color: #6d7a76; font-size: 13px; line-height: 1.6; }
.import-pick { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.import-file { font-size: 13px; }
.import-plan { margin-top: 12px; padding: 10px 12px; background: #f6f8f7; border-radius: 6px; }
.import-line { margin: 0 0 4px; font-size: 13px; }
.import-warning { margin: 4px 0 0; color: #b25e5e; font-size: 13px; }
</style>
