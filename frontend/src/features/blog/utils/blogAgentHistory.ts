/**
 * 博客智能体历史消息加载的纯函数工具。
 *
 * 从 BlogView.vue 抽出，方便在 Node 单测里覆盖分页参数拼接与消息映射：
 * - buildBlogAgentHistoryUrl：GET /api/agent/blog/agent/chat/ 的查询串拼接
 * - mapBlogAgentHistoryMessages：后端序列化消息 → 前端 BlogAgentChatMessage
 * - mergeOlderBlogAgentMessages：更早消息按 id 去重后 prepend
 */

import type { BlogAgentChatMessage } from "../types";

/** 历史消息每页条数（后端上限 50）。 */
export const BLOG_AGENT_HISTORY_PAGE_SIZE = 8;

interface SerializedBlogAgentMessage {
  id?: number | null;
  role?: string;
  content?: string;
  sources?: BlogAgentChatMessage["sources"];
  [key: string]: unknown;
}

/**
 * 拼接博客智能体历史消息的 GET 查询串。
 *
 * @param sessionKey 访客会话 key；为空时返回空串（调用方跳过请求）。
 * @param options before：取该消息 id 之前（更早）的一页；limit：每页条数，默认 8。
 */
export function buildBlogAgentHistoryUrl(
  sessionKey: string,
  options: { before?: number; limit?: number } = {}
): string {
  if (!sessionKey) return "";
  const params = new URLSearchParams({ session_key: sessionKey });
  params.set("limit", String(options.limit ?? BLOG_AGENT_HISTORY_PAGE_SIZE));
  if (typeof options.before === "number" && Number.isFinite(options.before)) {
    params.set("before", String(Math.trunc(options.before)));
  }
  return `/api/agent/blog/agent/chat/?${params.toString()}`;
}

/** 将后端序列化消息映射为前端聊天消息；role 非法时按 agent 处理。 */
export function mapBlogAgentHistoryMessage(message: SerializedBlogAgentMessage): BlogAgentChatMessage {
  return {
    id: typeof message.id === "number" ? message.id : undefined,
    role: message.role === "user" ? "user" : "agent",
    content: message.content ?? "",
    sources: message.sources
  };
}

/** 映射一批后端消息并按 id 去重（保持传入顺序）。 */
export function mapBlogAgentHistoryMessages(messages: SerializedBlogAgentMessage[]): BlogAgentChatMessage[] {
  const seen = new Set<number>();
  const result: BlogAgentChatMessage[] = [];
  for (const message of messages ?? []) {
    const mapped = mapBlogAgentHistoryMessage(message);
    if (typeof mapped.id === "number") {
      if (seen.has(mapped.id)) continue;
      seen.add(mapped.id);
    }
    result.push(mapped);
  }
  return result;
}

/**
 * 将更早的一页消息合并到列表头部。
 *
 * 以持久化消息 id 为准去重：本地消息（无 id，如欢迎语、pending）原样保留；
 * 已存在同 id 的旧消息不重复插入。返回新数组，不改入参。
 */
export function mergeOlderBlogAgentMessages(
  current: BlogAgentChatMessage[],
  older: BlogAgentChatMessage[]
): BlogAgentChatMessage[] {
  const existingIds = new Set(
    current.filter((message): message is BlogAgentChatMessage & { id: number } => typeof message.id === "number").map((message) => message.id)
  );
  const fresh = older.filter(
    (message) => typeof message.id !== "number" || !existingIds.has(message.id)
  );
  return [...fresh, ...current];
}
