import type { BlogTheme } from './themeTypes';

const THEME_VAR_MAP: Record<keyof Omit<BlogTheme, 'id' | 'name' | 'description'>, string> = {
  bgColor: '--theme-bg',
  textColor: '--theme-text',
  headingColor: '--theme-heading',
  linkColor: '--theme-link',
  codeBg: '--theme-code-bg',
  codeText: '--theme-code-text',
  blockquoteBg: '--theme-quote-bg',
  blockquoteBorder: '--theme-quote-border',
  borderColor: '--theme-border',
  fontFamily: '--theme-font',
  headingFont: '--theme-heading-font',
  fontSize: '--theme-font-size',
  lineHeight: '--theme-line-height',
  contentWidth: '--theme-content-width',
  paragraphSpacing: '--theme-paragraph-spacing',
  headingSpacing: '--theme-heading-spacing',
};

/**
 * Apply a theme by setting CSS variables on a container element.
 */
export function applyThemeToElement(el: HTMLElement, theme: BlogTheme): void {
  for (const [key, cssVar] of Object.entries(THEME_VAR_MAP)) {
    const value = theme[key as keyof typeof THEME_VAR_MAP];
    el.style.setProperty(cssVar, value);
  }
}

/**
 * Remove all theme variables from a container element.
 */
export function removeThemeFromElement(el: HTMLElement): void {
  for (const cssVar of Object.values(THEME_VAR_MAP)) {
    el.style.removeProperty(cssVar);
  }
}

/**
 * Generate CSS class content for a theme (for preview purposes).
 */
export function generateThemePreviewStyle(theme: BlogTheme): string {
  return Object.entries(THEME_VAR_MAP)
    .map(([key, cssVar]) => `${cssVar}: ${theme[key as keyof typeof THEME_VAR_MAP]}`)
    .join('; ');
}