import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { BlogTheme } from '../themes/themeTypes';
import { presetThemes, getThemeById, createEmptyTheme } from '../themes/presetThemes';

const STORAGE_KEY_THEME = 'blogCurrentThemeId';
const STORAGE_KEY_CUSTOM = 'blogCustomThemes';

export const useThemeStore = defineStore('blogTheme', () => {
  // State
  const currentThemeId = ref<string>(localStorage.getItem(STORAGE_KEY_THEME) || 'default');
  const customThemes = ref<BlogTheme[]>(loadCustomThemes());
  const creatorOpen = ref(false);
  const editingTheme = ref<BlogTheme | null>(null);

  // Computed
  const allThemes = computed<BlogTheme[]>(() => [...presetThemes, ...customThemes.value]);

  const currentTheme = computed<BlogTheme>(() => {
    return allThemes.value.find(t => t.id === currentThemeId.value) || presetThemes[0];
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
    // If deleted theme was active, switch to default
    if (currentThemeId.value === id) {
      setTheme('default');
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