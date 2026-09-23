export type KnowledgeCategory = "tech_docs" | "product_docs" | "learning_notes" | "project_docs" | "other";

export const CATEGORY_LABELS: Record<KnowledgeCategory, string> = {
  tech_docs: "技术文档",
  product_docs: "产品文档",
  learning_notes: "学习笔记",
  project_docs: "项目资料",
  other: "其他",
};

export interface KnowledgeBase {
  id: number;
  name: string;
  description: string;
  category: KnowledgeCategory;
  category_label: string;
  tags: string[];
  is_archived: boolean;
  sort_order: number;
  document_count: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: number;
  knowledge_base_id: number;
  title: string;
  content_type: string;
  status: "pending" | "processing" | "ready" | "failed";
  error_message: string;
  chunk_count: number;
  created_at: string;
}

export interface SearchResult {
  document_id: number;
  document_title: string;
  chunk_id: number;
  chunk_index: number;
  content: string;
  score: number;
}
