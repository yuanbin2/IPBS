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
}

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
  matched_message_id?: number;
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
