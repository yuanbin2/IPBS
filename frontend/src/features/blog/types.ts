export interface BlogTag {
  id: number;
  name: string;
  slug: string;
  article_count: number;
}

export interface BlogCategory {
  id: number;
  name: string;
  slug: string;
  description: string;
  article_count: number;
}

export interface BlogComment {
  id: number;
  author_name: string;
  content: string;
  created_at: string;
}

export interface BlogArticle {
  id: number;
  title: string;
  slug: string;
  author_name: string;
  summary: string;
  cover_image: string;
  content?: string;
  status: string;
  view_count: number;
  category: BlogCategory | null;
  tags: BlogTag[];
  published_at: string | null;
  created_at: string;
  updated_at?: string;
  knowledge_document_id: number | null;
  comment_count: number;
  comments?: BlogComment[];
}

export interface ArchiveGroup {
  month: string;
  articles: BlogArticle[];
}

export interface BlogAgentSource {
  title: string;
  kind: string;
  content: string;
  score: number;
  url: string;
  document_id?: number | null;
  chunk_index?: number | null;
}

export interface BlogAgentChatMessage {
  role: "user" | "agent";
  content: string;
  sources?: BlogAgentSource[];
  blocked?: boolean;
  pending?: boolean;
}

export interface ApprovalRequest {
  id: number;
  title: string;
  description: string;
  payload: Record<string, unknown>;
  status: "pending" | "executed" | "rejected" | "failed";
  result: string;
}

export interface BlogDraft {
  title: string;
  summary: string;
  cover_image: string;
  category: string;
  tags: string;
  content: string;
}

export type WritingAssistantMode = "task_list" | "outline" | "draft" | "improve";

export interface WritingAssistantRequest {
  mode: WritingAssistantMode;
  instruction: string;
}

export interface WritingAssistantResult {
  markdown: string;
  mode: WritingAssistantMode;
  model: string;
  apiKeySource: "dedicated" | "shared";
}

export interface HeadingItem {
  level: number;
  text: string;
}

export interface EditorStats {
  words: number;
  readingMinutes: number;
  headings: string[];
  headingItems: HeadingItem[];
}
