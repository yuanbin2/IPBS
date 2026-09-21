export interface KnowledgeBase {
  id: number;
  name: string;
  description: string;
  document_count: number;
  chunk_count: number;
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
