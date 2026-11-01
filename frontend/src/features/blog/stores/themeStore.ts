import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { BlogTheme } from '../themes/themeTypes';
import { DEFAULT_THEME_ID, presetThemes, getThemeById, createEmptyTheme } from '../themes/presetThemes';

const STORAGE_KEY_THEME = 'blogCurrentThemeId';
const STORAGE_KEY_CUSTOM = 'blogCustomThemes';

export const useThemeStore = defineStore('blogTheme', () => {
  // State
  const customThemes = ref<BlogTheme[]>(loadCustomThemes());
  const currentThemeId = ref<string>(resolveStoredThemeId(customThemes.value));
  const creatorOpen = ref(false);
  const editingTheme = ref<BlogTheme | null>(null);

  /**
   * 读取本地记录的主题 id。已下线（default/dark）或已不存在的 id 一律迁移到
   * DEFAULT_THEME_ID 并写回，否则会出现「id 有值但找不到主题」——
   * 表现为切换器里没有任何一项高亮，而正文却用的是兜底主题。
   */
  function resolveStoredThemeId(custom: BlogTheme[]): string {
    const stored = localStorage.getItem(STORAGE_KEY_THEME);
    if (stored && (getThemeById(stored) || custom.some(t => t.id === stored))) {
      return stored;
    }
    if (stored) {
      localStorage.setItem(STORAGE_KEY_THEME, DEFAULT_THEME_ID);
    }
    return DEFAULT_THEME_ID;
  }

  // Computed
  const allThemes = computed<BlogTheme[]>(() => [...presetThemes, ...customThemes.value]);

  const currentTheme = computed<BlogTheme>(() => {
    return (
      allThemes.value.find(t => t.id === currentThemeId.value) ||
      getThemeById(DEFAULT_THEME_ID) ||
      presetThemes[0]
    );
  });

  const isCustomTheme = computed(() => {
    return customThemes.value.some(t => t.id === currentThemeId.value);
  });

  // Actions
  function setTheme(id: string) {
    currentThemeId.value = id;
    localStorage.setItem(STORAGE_KEY_THEME, id);
  }

  function saveCustomTheme(theme: BlogTheme) {
    const index = customThemes.value.findIndex(t => t.id === theme.id);
    if (index >= 0) {
      customThemes.value[index] = { ...theme };
    } else {
      customThemes.value.push({ ...theme });
    }
    saveCustomThemes();
  }

  function deleteCustomTheme(id: string) {
    customThemes.value = customThemes.value.filter(t => t.id !== id);
    saveCustomThemes();
    // If deleted theme was active, fall back to the built-in default theme.
    if (currentThemeId.value === id) {
      setTheme(DEFAULT_THEME_ID);
    }
  }

  function openCreator(theme?: BlogTheme) {
    editingTheme.value = theme ? { ...theme } : createEmptyTheme();
    creatorOpen.value = true;
  }

  function closeCreator() {
    creatorOpen.value = false;
    editingTheme.value = null;
  }

  // Persistence
  function loadCustomThemes(): BlogTheme[] {
    try {
      const stored = localStorage.getItem(STORAGE_KEY_CUSTOM);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  }

  function saveCustomThemes() {
    localStorage.setItem(STORAGE_KEY_CUSTOM, JSON.stringify(customThemes.value));
  }

  return {
    currentThemeId,
    customThemes,
    creatorOpen,
    editingTheme,
    allThemes,
    currentTheme,
    isCustomTheme,
    setTheme,
    saveCustomTheme,
    deleteCustomTheme,
    openCreator,
    closeCreator,
  };
});