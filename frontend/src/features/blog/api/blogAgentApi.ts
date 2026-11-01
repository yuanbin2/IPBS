import type { BlogAgentChatMessage } from "../types";
import { buildBlogAgentHistoryUrl, BLOG_AGENT_HISTORY_PAGE_SIZE } from "../utils/blogAgentHistory.ts";
import { requestJson } from "./requestJson.ts";

export interface BlogAgentHistoryPage {
  messages?: Array<{ id?: number | null; role?: string; content?: string; sources?: BlogAgentChatMessage["sources"] }>;
  has_more_before?: boolean;
}

export interface BlogAgentAnswer {
  session_key: string;
  answer: string;
  sources?: BlogAgentChatMessage["sources"];
  blocked?: boolean;
  rag_source_effective?: "legacy" | "ragagent";
  degraded?: boolean;
  degraded_reason?: string;
}

export function fetchBlogAgentHistory(sessionKey: string, before?: number): Promise<BlogAgentHistoryPage> {
  return requestJson(buildBlogAgentHistoryUrl(sessionKey, { limit: BLOG_AGENT_HISTORY_PAGE_SIZE, before }));
}

export function postBlogAgentMessage(message: string, sessionKey: string, ragSource: "legacy" | "ragagent"): Promise<BlogAgentAnswer> {
  return requestJson("/api/agent/blog/agent/chat/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_key: sessionKey, rag_source: ragSource }),
  });
}
