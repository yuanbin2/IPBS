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
  quote: string;
  anchor_offset: number | null;
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
  publication_version: number;
  pending_revision?: {
    id: number;
    base_version: number;
    title: string;
    summary: string;
    cover_image: string;
    content: string;
    category: string;
    tags: string[];
  };
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
  /** 后端持久化消息 id；欢迎语等本地消息无 id，作为加载更早消息的翻页游标依据。 */
  id?: number;
  sources?: BlogAgentSource[];
  blocked?: boolean;
  pending?: boolean;
  /** B052 实际生效的知识来源（降级后为 legacy）。 */
  rag_source_effective?: "legacy" | "ragagent";
  /** B052 RAG-Agent 请求失败降级回站内检索时为 true。 */
  degraded?: boolean;
  /** B052 降级原因短句（后端已截断 120 字符）。 */
  degraded_reason?: string;
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
  /** 标签名列表（多值）。历史缓存里可能是逗号分隔字符串，读取时用 normalizeTagList 规整。 */
  tags: string[];
  content: string;
}

export interface PrivateNote {
  id: number;
  title: string;
  content: string;
  quote: string;
  anchor_offset: number | null;
  source_article: number | null;
  source_article_slug: string | null;
  source_url?: string;
  source_title?: string;
  captured_at?: string | null;
  version: number;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
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

export interface CollectionArticleCard {
  id: number;
  title: string;
  slug: string;
  author_name: string;
  summary: string;
  cover_image: string;
  published_at: string | null;
  /** 标签名列表，用于领域页展示与筛选。 */
  tags: string[];
  /** 分类名（未分类时为空串）。 */
  category: string;
}

export interface CollectionNodeSummary {
  id: number;
  title: string;
  description: string;
  position: number;
  parent: number | null;
}

export interface CollectionEntrySummary {
  id: number;
  node: number | null;
  position: number;
  article: Pick<BlogArticle, "id" | "title" | "slug" | "author_name" | "summary" | "status" | "cover_image">;
}

export interface CollectionAutoRule {
  id: number;
  node: number | null;
  node_title: string;
  node_label: string;
  category: { id: number; name: string; slug: string } | null;
  tag: { id: number; name: string } | null;
  enabled: boolean;
  last_applied_at: string | null;
  created_at: string;
}

export interface CollectionDraft {
  public_id: string;
  title: string;
  slug: string;
  description: string;
  draft_version: number;
  publication_version: number;
  is_published: boolean;
  has_pending: boolean;
  pending_approval_id: number | null;
  pending?: { id: number; status: string; review_note: string };
  last_review?: { id: number; status: string; review_note: string; result: string };
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  nodes: CollectionNodeSummary[];
  entries: CollectionEntrySummary[];
  auto_rules?: CollectionAutoRule[];
}

export interface CollectionPublicNode {
  id: number;
  title: string;
  description: string;
  article_count: number;
  articles: CollectionArticleCard[];
  breadcrumb: Array<{ id: number; title: string }>;
  children: CollectionPublicNode[];
}

export interface CollectionPublicDetail {
  public_id: string;
  title: string;
  description: string;
  publication_version: number;
  updated_at: string;
  root_articles: CollectionArticleCard[];
  nodes: CollectionPublicNode[];
}

export interface CollectionPublicSummary {
  public_id: string;
  title: string;
  description: string;
  visible_article_count: number;
  node_count: number;
  publication_version: number;
  updated_at: string;
}

export interface CollectionArticleContext {
  collection: { public_id: string; title: string };
  node_path: string[];
  node_id: number | null;
  prev: { slug: string; title: string; node_path: string[] } | null;
  next: { slug: string; title: string; node_path: string[] } | null;
}

/** B-043 浏览器扩展交接的不可信预填候选。 */
export interface ExtensionClipCandidate {
  sourceUrl: string;
  titleCandidate: string;
  frontendIdCandidate: string;
  ownNote: string;
  noteTarget: string;
}
