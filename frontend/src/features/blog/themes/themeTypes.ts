export interface BlogTheme {
  id: string;
  name: string;
  description: string;
  // Colors
  bgColor: string;
  textColor: string;
  headingColor: string;
  linkColor: string;
  codeBg: string;
  codeText: string;
  blockquoteBg: string;
  blockquoteBorder: string;
  borderColor: string;
  // Typography
  fontFamily: string;
  headingFont: string;
  fontSize: string;
  lineHeight: string;
  contentWidth: string;
  // Spacing
  paragraphSpacing: string;
  headingSpacing: string;
}

export type ThemeProperty = keyof Omit<BlogTheme, 'id' | 'name' | 'description'>;

export interface ThemePropertyMeta {
  key: ThemeProperty;
  label: string;
  type: 'color' | 'font' | 'size';
  group: 'colors' | 'typography' | 'spacing';
}

export const THEME_PROPERTIES: ThemePropertyMeta[] = [
  // Colors
  { key: 'bgColor', label: '背景色', type: 'color', group: 'colors' },
  { key: 'textColor', label: '文字颜色', type: 'color', group: 'colors' },
  { key: 'headingColor', label: '标题颜色', type: 'color', group: 'colors' },
  { key: 'linkColor', label: '链接颜色', type: 'color', group: 'colors' },
  { key: 'codeBg', label: '代码块背景', type: 'color', group: 'colors' },
  { key: 'codeText', label: '代码文字颜色', type: 'color', group: 'colors' },
  { key: 'blockquoteBg', label: '引用块背景', type: 'color', group: 'colors' },
  { key: 'blockquoteBorder', label: '引用块边框', type: 'color', group: 'colors' },
  { key: 'borderColor', label: '边框颜色', type: 'color', group: 'colors' },
  // Typography
  { key: 'fontFamily', label: '正文字体', type: 'font', group: 'typography' },
  { key: 'headingFont', label: '标题字体', type: 'font', group: 'typography' },
  { key: 'fontSize', label: '字号', type: 'size', group: 'typography' },
  { key: 'lineHeight', label: '行高', type: 'size', group: 'typography' },
  { key: 'contentWidth', label: '内容宽度', type: 'size', group: 'typography' },
  // Spacing
  { key: 'paragraphSpacing', label: '段落间距', type: 'size', group: 'spacing' },
  { key: 'headingSpacing', label: '标题间距', type: 'size', group: 'spacing' },
];

export const FONT_OPTIONS = [
  { label: 'Inter (默认)', value: 'Inter, "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif' },
  { label: 'Georgia (衬线)', value: 'Georgia, "Noto Serif SC", "Songti SC", serif' },
  { label: '系统字体', value: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' },
  { label: '等宽字体', value: '"JetBrains Mono", "Fira Code", Consolas, monospace' },
  { label: '苹方', value: '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif' },
];