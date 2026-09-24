export interface ToolCall {
  name: string;
  input: string;
  output: string;
}

export interface SourceCitation {
  document_id: number;
  document_title: string;
  chunk_id: number;
  chunk_index: number;
  score: number;
  content: string;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface SupervisorDecision {
  selected_agent: string;
  display_name: string;
  reason: string;
  confidence: number;
  handoff: string;
}

export interface ChatMessage {
  id?: number;
  role: "user" | "agent";
  content: string;
  toolCalls?: ToolCall[];
  sources?: SourceCitation[];
  trace?: string[];
  tokenUsage?: TokenUsage;
  supervisor?: SupervisorDecision;
  pending?: boolean;
  /** Live trace entries during SSE streaming */
  streamingTrace?: string[];
  /** Whether the thinking panel is currently expanded */
  thinkingExpanded?: boolean;
}

/** SSE event from the streaming chat endpoint */
export interface StreamEvent {
  type: "trace" | "response" | "approval" | "done" | "error";
  data?: string;
  answer?: string;
  tool_calls?: ToolCall[];
  sources?: SourceCitation[];
  trace?: string[];
  token_usage?: TokenUsage;
  supervisor?: SupervisorDecision;
  conversation_id?: number;
  detail?: string;
}

export interface Conversation {
  id: number;
  project_id: number | null;
  title: string;
  created_at: string;
  updated_at: string;
  matched_message_id?: number;
}

/** 对话项目：把会话按主题分组（"all" 表示全部，"none" 表示未分组） */
export interface ConversationProject {
  id: number;
  name: string;
  description: string;
  color: string;
  conversation_count: number;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Array<{
    id: number;
    role: "user" | "agent";
    content: string;
    tool_calls: ToolCall[];
    sources: SourceCitation[];
    trace: string[];
    token_usage: TokenUsage;
  }>;
  has_more_before: boolean;
  has_more_after: boolean;
}

export interface ApprovalRequest {
  id: number;
  title: string;
  description: string;
  payload: Record<string, unknown>;
  status: "pending" | "executed" | "rejected" | "failed";
  result: string;
}
