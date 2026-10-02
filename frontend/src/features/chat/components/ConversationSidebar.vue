<script setup lang="ts">
import { Cpu, Delete, EditPen, FolderOpened, Plus, Refresh, Search } from "@element-plus/icons-vue";
import { ElMessageBox } from "element-plus";
import { ref } from "vue";
import type { Conversation, ConversationProject, TurnMetrics } from "../types";

const props = defineProps<{
  historySearch: string;
  conversations: Conversation[];
  currentConversationId: number | null;
  conversationsLoading: boolean;
  chatLoading: boolean;
  latestMetrics: TurnMetrics | null;
  projects: ConversationProject[];
  /** "all" 全部对话 | "none" 未分组 | 项目 id（字符串） */
  activeProject: string;
}>();

const emit = defineEmits<{
  "update:historySearch": [value: string];
  refresh: [];
  create: [];
  select: [conversation: Conversation];
  "select-project": [projectId: string];
  "create-project": [name: string];
  "rename-project": [project: ConversationProject, name: string];
  "delete-project": [project: ConversationProject];
  "move-conversation": [conversation: Conversation, projectId: number | null];
}>();

const newProjectName = ref("");
const isCreatingProject = ref(false);
const editingProjectId = ref<number | null>(null);
const editingProjectName = ref("");

function startCreateProject() {
  isCreatingProject.value = true;
  newProjectName.value = "";
}

function submitNewProject() {
  const name = newProjectName.value.trim();
  if (!name) {
    isCreatingProject.value = false;
    return;
  }
  emit("create-project", name);
  isCreatingProject.value = false;
  newProjectName.value = "";
}

function startRename(project: ConversationProject) {
  editingProjectId.value = project.id;
  editingProjectName.value = project.name;
}

function submitRename(project: ConversationProject) {
  const name = editingProjectName.value.trim();
  editingProjectId.value = null;
  if (name && name !== project.name) {
    emit("rename-project", project, name);
  }
}

async function confirmDeleteProject(project: ConversationProject) {
  try {
    await ElMessageBox.confirm(
      `删除项目「${project.name}」？其中的对话会移回未分组，不会丢失。`,
      "删除项目",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  emit("delete-project", project);
}

function projectFilterLabel() {
  if (props.activeProject === "all") return "全部对话";
  if (props.activeProject === "none") return "未分组";
  return props.projects.find((item) => String(item.id) === props.activeProject)?.name ?? "全部对话";
}

</script>

<template>
  <aside class="agent-panel">
    <section class="project-section">
      <div class="panel-actions">
        <h2><el-icon><FolderOpened /></el-icon> 项目</h2>
        <el-button :icon="Plus" circle size="small" title="新建项目" @click="startCreateProject" />
      </div>

      <div class="project-list">
        <button
          type="button"
          :class="{ active: activeProject === 'all' }"
          @click="emit('select-project', 'all')"
        >
          <span class="project-dot project-dot-neutral"></span>
          全部对话
        </button>
        <div v-for="project in projects" :key="project.id" class="project-item" :class="{ active: activeProject === String(project.id) }">
          <button v-if="editingProjectId !== project.id" type="button" @click="emit('select-project', String(project.id))">
            <span class="project-dot" :style="{ backgroundColor: project.color || 'var(--color-border)' }"></span>
            <span class="project-name">{{ project.name }}</span>
            <span class="project-count">{{ project.conversation_count }}</span>
          </button>
          <input
            v-else
            v-model="editingProjectName"
            class="project-rename"
            @keyup.enter="submitRename(project)"
            @keyup.esc="editingProjectId = null"
            @blur="submitRename(project)"
          />
          <span v-if="editingProjectId !== project.id" class="project-actions">
            <el-button :icon="EditPen" size="small" text title="重命名" @click="startRename(project)" />
            <el-button :icon="Delete" size="small" text title="删除项目" @click="confirmDeleteProject(project)" />
          </span>
        </div>
        <button
          type="button"
          :class="{ active: activeProject === 'none' }"
          @click="emit('select-project', 'none')"
        >
          <span class="project-dot project-dot-neutral"></span>
          未分组
        </button>
        <input
          v-if="isCreatingProject"
          v-model="newProjectName"
          class="project-rename"
          placeholder="项目名称，回车创建"
          autofocus
          @keyup.enter="submitNewProject"
          @keyup.esc="isCreatingProject = false"
          @blur="submitNewProject"
        />
      </div>
    </section>

    <div class="panel-actions">
      <h2><el-icon><Cpu /></el-icon> 会话历史</h2>
      <div>
        <el-button :icon="Refresh" circle :loading="conversationsLoading" @click="emit('refresh')" />
        <el-button :icon="Plus" circle title="新对话" @click="emit('create')" />
      </div>
    </div>

    <p v-if="activeProject !== 'all'" class="project-filter-hint">
      当前范围：{{ projectFilterLabel() }}，新对话将放入这里
    </p>

    <el-input
      :model-value="historySearch"
      class="history-search"
      clearable
      :prefix-icon="Search"
      placeholder="搜索历史消息"
      @update:model-value="emit('update:historySearch', String($event))"
      @keyup.enter="emit('refresh')"
      @clear="emit('refresh')"
    />

    <section class="metric-card">
      <header>
        <span>本轮指标</span>
        <small v-if="chatLoading">统计中</small>
      </header>
      <div v-if="latestMetrics" class="metric-grid">
        <div class="metric">
          <small>Token</small>
          <strong>{{ latestMetrics.tokenUsage.total_tokens }}</strong>
          <small>prompt {{ latestMetrics.tokenUsage.prompt_tokens }} / completion {{ latestMetrics.tokenUsage.completion_tokens }}</small>
        </div>
        <div class="metric">
          <small>延迟</small>
          <strong>{{ latestMetrics.latencyMs !== null ? `${latestMetrics.latencyMs} ms` : "—" }}</strong>
          <small>端到端耗时</small>
        </div>
        <div class="metric">
          <small>工具</small>
          <strong>{{ latestMetrics.toolTotal ? `${latestMetrics.toolSucceeded}/${latestMetrics.toolTotal}` : "0" }}</strong>
          <small>成功 / 调用</small>
        </div>
        <div class="metric">
          <small>检索命中</small>
          <strong>{{ latestMetrics.sourceCount }}</strong>
          <small>引用片段数</small>
        </div>
      </div>
      <p v-else class="metric-empty">发送一条消息后显示 Token、延迟、工具与检索指标</p>
    </section>

    <div class="history-list">
      <div
        v-for="conversation in conversations"
        :key="conversation.id"
        class="history-item"
        :class="{ active: conversation.id === currentConversationId }"
        @click="emit('select', conversation)"
      >
        <span class="history-title">{{ conversation.title || `会话 ${conversation.id}` }}</span>
        <el-dropdown trigger="click" @command="(command: number | null) => emit('move-conversation', conversation, command)">
          <el-button :icon="FolderOpened" size="small" text title="移动到项目" @click.stop />
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item :command="null">移出项目（未分组）</el-dropdown-item>
              <el-dropdown-item
                v-for="project in projects"
                :key="project.id"
                :command="project.id"
                :disabled="conversation.project_id === project.id"
              >
                移动到：{{ project.name }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <p v-if="!conversations.length && !conversationsLoading" class="history-empty">还没有对话，点右上角 + 开始</p>
    </div>
  </aside>
</template>
