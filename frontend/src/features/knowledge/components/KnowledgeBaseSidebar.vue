<script setup lang="ts">
import { computed, ref } from "vue";
import {
  ArrowDown,
  ArrowRight,
  Delete,
  Files,
  Folder,
  FolderOpened,
  Plus,
  Refresh,
  Search,
} from "@element-plus/icons-vue";
import { ElMessageBox } from "element-plus";
import type { KnowledgeBase, KnowledgeCategory } from "../types";
import { CATEGORY_LABELS } from "../types";
import CreateKnowledgeBaseDialog from "./CreateKnowledgeBaseDialog.vue";

const props = defineProps<{
  items: KnowledgeBase[];
  selectedId: number | null;
  loading: boolean;
  deletingId: number | null;
}>();

const emit = defineEmits<{
  select: [id: number];
  refresh: [];
  remove: [item: KnowledgeBase];
  archive: [item: KnowledgeBase, action: "archive" | "unarchive"];
  create: [data: { name: string; description: string; category: KnowledgeCategory; tags: string[] }];
}>();

const searchQuery = ref("");
const selectedCategory = ref<KnowledgeCategory | "all">("all");
const showArchived = ref(false);
const expandedCategories = ref<Set<string>>(new Set(["tech_docs", "product_docs", "learning_notes", "project_docs", "other"]));

// 筛选后的知识库列表
const filteredItems = computed(() => {
  let result = props.items;

  // 按归档状态筛选
  if (!showArchived.value) {
    result = result.filter((item) => !item.is_archived);
  } else {
    result = result.filter((item) => item.is_archived);
  }

  // 按分类筛选
  if (selectedCategory.value !== "all") {
    result = result.filter((item) => item.category === selectedCategory.value);
  }

  // 按搜索关键词筛选
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.toLowerCase().trim();
    result = result.filter(
      (item) =>
        item.name.toLowerCase().includes(query) ||
        item.description.toLowerCase().includes(query) ||
        item.tags.some((tag) => tag.toLowerCase().includes(query))
    );
  }

  return result;
});

// 按分类分组的知识库
const groupedItems = computed(() => {
  const groups: Record<string, KnowledgeBase[]> = {};

  for (const item of filteredItems.value) {
    const category = item.category || "other";
    if (!groups[category]) {
      groups[category] = [];
    }
    groups[category].push(item);
  }

  // 按排序顺序排列
  for (const category in groups) {
    groups[category].sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name));
  }

  return groups;
});

// 获取分类列表（有知识库的分类）
const categories = computed(() => {
  return Object.keys(groupedItems.value).filter(
    (cat) => groupedItems.value[cat].length > 0
  );
});

// 归档数量
const archivedCount = computed(() => {
  return props.items.filter((item) => item.is_archived).length;
});

function toggleCategory(category: string) {
  if (expandedCategories.value.has(category)) {
    expandedCategories.value.delete(category);
  } else {
    expandedCategories.value.add(category);
  }
}

function isCategoryExpanded(category: string) {
  return expandedCategories.value.has(category);
}

async function handleArchive(item: KnowledgeBase) {
  const action = item.is_archived ? "unarchive" : "archive";
  const actionLabel = action === "archive" ? "归档" : "取消归档";

  try {
    await ElMessageBox.confirm(
      `确定要${actionLabel}知识库 "${item.name}" 吗？`,
      `${actionLabel}确认`,
      { confirmButtonText: "确定", cancelButtonText: "取消", type: "warning" }
    );
    emit("archive", item, action);
  } catch {
    // 用户取消
  }
}

function getCategoryIcon(category: string) {
  return expandedCategories.value.has(category) ? FolderOpened : Folder;
}
const showCreateDialog = ref(false);

function handleCreate(data: { name: string; description: string; category: KnowledgeCategory; tags: string[] }) {
  emit("create", data);
}
</script>

<template>
  <aside class="knowledge-panel">
    <div class="panel-actions">
      <h2><el-icon><Files /></el-icon> 知识库</h2>
      <div class="panel-buttons">
        <el-button :icon="Plus" type="primary" size="small" @click="showCreateDialog = true">
          新建
        </el-button>
        <el-button :icon="Refresh" circle :loading="loading" @click="$emit('refresh')" />
      </div>
    </div>

    <!-- 新建知识库对话框 -->
    <CreateKnowledgeBaseDialog
      v-model:visible="showCreateDialog"
      @create="handleCreate"
    />

    <!-- 搜索框 -->
    <div class="panel-search">
      <el-input
        v-model="searchQuery"
        placeholder="搜索知识库..."
        clearable
        :prefix-icon="Search"
        size="small"
      />
    </div>

    <!-- 分类筛选 -->
    <div class="panel-categories">
      <el-radio-group v-model="selectedCategory" size="small">
        <el-radio-button label="all">全部</el-radio-button>
        <el-radio-button
          v-for="(label, key) in CATEGORY_LABELS"
          :key="key"
          :label="key"
        >
          {{ label }}
        </el-radio-button>
      </el-radio-group>
    </div>

    <!-- 知识库列表（按分类分组） -->
    <div class="knowledge-list">
      <template v-if="!showArchived">
        <div
          v-for="category in categories"
          :key="category"
          class="category-group"
        >
          <div class="category-header" @click="toggleCategory(category)">
            <el-icon class="category-toggle">
              <ArrowDown v-if="isCategoryExpanded(category)" />
              <ArrowRight v-else />
            </el-icon>
            <el-icon><component :is="getCategoryIcon(category)" /></el-icon>
            <span class="category-name">{{ CATEGORY_LABELS[category as KnowledgeCategory] || category }}</span>
            <span class="category-count">{{ groupedItems[category].length }}</span>
          </div>

          <div v-if="isCategoryExpanded(category)" class="category-items">
            <div
              v-for="item in groupedItems[category]"
              :key="item.id"
              class="knowledge-base-row"
              :class="{ active: item.id === selectedId }"
            >
              <button
                type="button"
                class="knowledge-base-button"
                @click="$emit('select', item.id)"
              >
                <strong>{{ item.name }}</strong>
                <div class="kb-meta">
                  <span>{{ item.document_count }} 文档 / {{ item.chunk_count }} 片段</span>
                  <div v-if="item.tags.length > 0" class="kb-tags">
                    <span v-for="tag in item.tags.slice(0, 3)" :key="tag" class="kb-tag">
                      {{ tag }}
                    </span>
                  </div>
                </div>
              </button>
              <div class="kb-actions">
                <el-button
                  :icon="FolderOpened"
                  circle
                  plain
                  size="small"
                  title="归档"
                  @click="handleArchive(item)"
                />
                <el-button
                  :icon="Delete"
                  circle
                  plain
                  type="danger"
                  size="small"
                  :loading="deletingId === item.id"
                  @click="$emit('remove', item)"
                />
              </div>
            </div>
          </div>
        </div>

        <div v-if="categories.length === 0 && !loading" class="empty-state">
          <span>没有找到知识库</span>
        </div>
      </template>

      <!-- 归档区 -->
      <div v-if="archivedCount > 0" class="archive-section">
        <div class="archive-header" @click="showArchived = !showArchived">
          <el-icon class="category-toggle">
            <ArrowDown v-if="showArchived" />
            <ArrowRight v-else />
          </el-icon>
          <el-icon><Folder /></el-icon>
          <span>归档区</span>
          <span class="category-count">{{ archivedCount }}</span>
        </div>

        <div v-if="showArchived" class="archive-items">
          <div
            v-for="item in filteredItems"
            :key="item.id"
            class="knowledge-base-row archived"
          >
            <button
              type="button"
              class="knowledge-base-button"
              @click="$emit('select', item.id)"
            >
              <strong>{{ item.name }}</strong>
              <span>{{ item.document_count }} 文档</span>
            </button>
            <div class="kb-actions">
              <el-button
                :icon="FolderOpened"
                circle
                plain
                size="small"
                title="取消归档"
                @click="handleArchive(item)"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>