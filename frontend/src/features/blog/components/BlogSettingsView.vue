<script setup lang="ts">
/**
 * 站点设置页（管理员/运营）：站点标题、副标题、作者名、关于页内容、
 * 页脚文案、每页文章数。保存到 /api/agent/blog/settings/（单例行）。
 * 公开读取无鉴权；写入需要管理员或运营角色（服务端校验）。
 */
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { apiUrl } from "../../../api/client";
import { useAuthStore } from "../../../stores/auth";

const router = useRouter();
const auth = useAuthStore();

const loading = ref(true);
const saving = ref(false);
const error = ref("");

const form = reactive({
  site_title: "",
  site_tagline: "",
  author_name: "",
  about_title: "",
  about_content: "",
  footer_text: "",
  articles_per_page: 12,
});

const highlights = ref<string[]>([]);

const canEdit = computed(() => {
  const role = auth.session?.role;
  return role === "admin" || role === "operator";
});

async function loadSettings() {
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch(apiUrl("/api/agent/blog/settings/"));
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail ?? "设置读取失败");
    Object.assign(form, {
      site_title: payload.site_title ?? "",
      site_tagline: payload.site_tagline ?? "",
      author_name: payload.author_name ?? "",
      about_title: payload.about_title ?? "",
      about_content: payload.about_content ?? "",
      footer_text: payload.footer_text ?? "",
      articles_per_page: payload.articles_per_page ?? 12,
    });
    highlights.value = Array.isArray(payload.about_highlights) ? [...payload.about_highlights] : [];
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "设置读取失败";
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  error.value = "";
  try {
    const response = await fetch(apiUrl("/api/agent/blog/settings/"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, about_highlights: highlights.value.filter((item) => item.trim()) }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail ?? "保存失败");
    Object.assign(form, {
      site_title: payload.site_title ?? "",
      site_tagline: payload.site_tagline ?? "",
      author_name: payload.author_name ?? "",
      about_title: payload.about_title ?? "",
      about_content: payload.about_content ?? "",
      footer_text: payload.footer_text ?? "",
      articles_per_page: payload.articles_per_page ?? 12,
    });
    highlights.value = Array.isArray(payload.about_highlights) ? [...payload.about_highlights] : [];
    ElMessage.success("设置已保存");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "保存失败";
  } finally {
    saving.value = false;
  }
}

function addHighlight() {
  if (highlights.value.length >= 6) return;
  highlights.value.push("");
}

function removeHighlight(index: number) {
  highlights.value.splice(index, 1);
}

onMounted(() => {
  void loadSettings();
});
</script>

<template>
  <main class="settings-view">
    <header class="settings-header">
      <h1>站点设置</h1>
      <p>这里的内容会直接作用于博客的首页标语、关于页与文章列表分页。</p>
    </header>

    <div v-if="loading" class="settings-loading">正在读取设置…</div>

    <template v-else>
      <section class="settings-card">
        <h2>站点信息</h2>
        <label class="settings-field">
          <span>站点标题（首页主标语）</span>
          <input v-model="form.site_title" maxlength="120" placeholder="例如：技术笔记与项目实践" />
        </label>
        <label class="settings-field">
          <span>副标题</span>
          <input v-model="form.site_tagline" maxlength="200" placeholder="一句话介绍这个站点" />
        </label>
        <label class="settings-field">
          <span>作者名</span>
          <input v-model="form.author_name" maxlength="80" placeholder="显示在关于页与文章署名处" />
        </label>
      </section>

      <section class="settings-card">
        <h2>关于页</h2>
        <label class="settings-field">
          <span>关于页标题</span>
          <input v-model="form.about_title" maxlength="120" placeholder="默认：关于这个知识型博客" />
        </label>
        <label class="settings-field">
          <span>关于内容</span>
          <textarea v-model="form.about_content" rows="5" maxlength="2000" placeholder="留空时使用默认文案"></textarea>
        </label>
        <div class="settings-field">
          <span>亮点标签（最多 6 条）</span>
          <div v-for="(_, index) in highlights" :key="index" class="highlight-row">
            <input v-model="highlights[index]" maxlength="80" />
            <button type="button" class="ghost" @click="removeHighlight(index)">删除</button>
          </div>
          <button type="button" class="ghost add" :disabled="highlights.length >= 6" @click="addHighlight">+ 添加亮点</button>
        </div>
      </section>

      <section class="settings-card">
        <h2>阅读与列表</h2>
        <label class="settings-field narrow">
          <span>文章列表每页数量（4–24）</span>
          <input v-model.number="form.articles_per_page" type="number" min="4" max="24" />
        </label>
        <label class="settings-field">
          <span>页脚文案</span>
          <input v-model="form.footer_text" maxlength="200" placeholder="例如：© 2026 某某 · 仅供学习交流" />
        </label>
      </section>

      <p v-if="error" class="settings-error">{{ error }}</p>

      <p v-if="!canEdit" class="settings-note">当前账号没有编辑站点设置的权限（需要管理员或运营角色），页面为只读。</p>

      <footer class="settings-actions">
        <button type="button" class="ghost" @click="router.back()">返回</button>
        <button type="button" class="primary" :disabled="saving || !canEdit" @click="save">
          {{ saving ? "保存中…" : "保存设置" }}
        </button>
      </footer>
    </template>
  </main>
</template>

<style scoped>
.settings-view { max-width: 720px; margin: 0 auto; padding: 32px 20px 64px; }
.settings-header h1 { margin: 0 0 4px; font-size: 24px; }
.settings-header p { margin: 0 0 20px; color: #6b7a72; font-size: 13px; }
.settings-card { border: 1px solid #e4e8e2; border-radius: 10px; padding: 18px 20px; margin-bottom: 16px; background: #fff; }
.settings-card h2 { margin: 0 0 12px; font-size: 16px; }
.settings-field { display: block; margin-bottom: 12px; font-size: 13px; }
.settings-field > span { display: block; margin-bottom: 4px; color: #51604f; }
.settings-field input, .settings-field textarea {
  width: 100%; box-sizing: border-box; border: 1px solid #d8dfd7; border-radius: 6px;
  padding: 8px 10px; font: inherit; color: inherit; background: #fff;
}
.settings-field.narrow input { max-width: 160px; }
textarea { resize: vertical; }
.highlight-row { display: flex; gap: 8px; margin-bottom: 6px; }
.highlight-row input { flex: 1; }
.ghost { border: 1px solid #d8dfd7; background: #fff; border-radius: 6px; padding: 6px 12px; font: inherit; cursor: pointer; }
.ghost:hover { border-color: #b9c6bb; }
.ghost.add { width: 100%; }
.settings-actions { display: flex; justify-content: flex-end; gap: 10px; }
.primary { border: 0; background: #3f7a5b; color: #fff; border-radius: 6px; padding: 9px 18px; font: inherit; cursor: pointer; }
.primary:disabled { opacity: 0.6; cursor: default; }
.settings-error { color: #b23b3b; font-size: 13px; }
.settings-note { color: #8a6d3b; font-size: 13px; background: #fdf6e7; border: 1px solid #f0e2c0; border-radius: 6px; padding: 8px 12px; }
.settings-loading { color: #6b7a72; }
</style>
