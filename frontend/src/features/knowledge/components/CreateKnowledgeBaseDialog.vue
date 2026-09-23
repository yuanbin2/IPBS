<script setup lang="ts">
import { ref, watch } from "vue";
import type { KnowledgeCategory } from "../types";
import { CATEGORY_LABELS } from "../types";

const props = defineProps<{
  visible: boolean;
}>();

const emit = defineEmits<{
  "update:visible": [value: boolean];
  create: [data: { name: string; description: string; category: KnowledgeCategory; tags: string[] }];
}>();

const form = ref({
  name: "",
  description: "",
  category: "other" as KnowledgeCategory,
  tags: [] as string[],
});

const tagInput = ref("");

watch(() => props.visible, (newVal) => {
  if (newVal) {
    form.value = {
      name: "",
      description: "",
      category: "other",
      tags: [],
    };
    tagInput.value = "";
  }
});

function addTag() {
  const tag = tagInput.value.trim();
  if (tag && !form.value.tags.includes(tag)) {
    form.value.tags.push(tag);
    tagInput.value = "";
  }
}

function removeTag(index: number) {
  form.value.tags.splice(index, 1);
}

function handleSubmit() {
  if (!form.value.name.trim()) return;
  emit("create", { ...form.value });
  emit("update:visible", false);
}

function handleClose() {
  emit("update:visible", false);
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="新建知识库"
    width="500px"
    @update:model-value="handleClose"
  >
    <el-form :model="form" label-position="top">
      <el-form-item label="知识库名称" required>
        <el-input
          v-model="form.name"
          placeholder="请输入知识库名称"
          maxlength="120"
          show-word-limit
        />
      </el-form-item>

      <el-form-item label="描述">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="3"
          placeholder="请输入知识库描述（可选）"
        />
      </el-form-item>

      <el-form-item label="分类" required>
        <el-select v-model="form.category" placeholder="请选择分类" style="width: 100%">
          <el-option
            v-for="(label, key) in CATEGORY_LABELS"
            :key="key"
            :label="label"
            :value="key"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="标签">
        <div class="tag-input-group">
          <el-input
            v-model="tagInput"
            placeholder="输入标签后按回车"
            @keyup.enter="addTag"
          >
            <template #append>
              <el-button @click="addTag">添加</el-button>
            </template>
          </el-input>
        </div>
        <div class="tag-list" v-if="form.tags.length > 0">
          <el-tag
            v-for="(tag, index) in form.tags"
            :key="index"
            closable
            @close="removeTag(index)"
          >
            {{ tag }}
          </el-tag>
        </div>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="handleClose">取消</el-button>
      <el-button type="primary" :disabled="!form.name.trim()" @click="handleSubmit">
        创建
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.tag-input-group {
  width: 100%;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}
</style>