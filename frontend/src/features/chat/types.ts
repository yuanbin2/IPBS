export interface ToolCall {
  name: string;
  input: string;
  output: string;
  /** 显式成功标记（后端 ToolResult.ok）；历史数据可能缺失 */
  ok?: boolean;
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
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
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
  /** 本轮已收到完整回答；新消息在重新加载会话前尚无持久化消息 ID。 */
  answered?: boolean;
  /** Live trace entries during SSE streaming */
  streamingTrace?: string[];
  /** Whether the thinking panel is currently expanded */
  thinkingExpanded?: boolean;
}

/** SSE event from the streaming chat endpoint */
export interface StreamEvent {
  type: "run" | "progress" | "trace" | "answer_delta" | "answer_snapshot" | "response" | "approval" | "done" | "error";
  data?: string;
  text?: string;
  status?: "pending" | "running" | "succeeded" | "failed" | "cancelled";
  answer?: string;
  tool_calls?: ToolCall[];
  sources?: SourceCitation[];
  trace?: string[];
  token_usage?: TokenUsage;
  supervisor?: SupervisorDecision;
  approval_required?: boolean;
  approval?: ApprovalRequest;
  conversation_id?: number;
  latency_ms?: number;
  detail?: string;
}

/** 本轮回答的实时指标（侧边栏指标卡） */
export interface TurnMetrics {
  tokenUsage: TokenUsage;
  latencyMs: number | null;
  toolTotal: number;
  toolSucceeded: number;
  sourceCount: number;
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
