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
  content?: string;
  status: string;
  view_count: number;
  category: BlogCategory | null;
  tags: BlogTag[];
  published_at: string | null;
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
  category: string;
  tags: string;
  content: string;
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
