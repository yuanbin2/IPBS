/**
 * 博客智能体历史消息分页工具的纯逻辑单测。
 *
 * 覆盖：查询串拼接（session_key / limit / before 游标）、
 * 后端消息映射保留 id、以及更早一页消息 prepend 时的 id 去重。
 *
 * 运行：npm run test:unit
 */

import test from "node:test";
import assert from "node:assert/strict";
import {
  BLOG_AGENT_HISTORY_PAGE_SIZE,
  buildBlogAgentHistoryUrl,
  mapBlogAgentHistoryMessages,
  mergeOlderBlogAgentMessages,
} from "../../src/features/blog/utils/blogAgentHistory.ts";
import type { BlogAgentChatMessage } from "../../src/features/blog/types.ts";

test("buildBlogAgentHistoryUrl：默认带 session_key 与每页 limit", () => {
  const url = buildBlogAgentHistoryUrl("visitor-session");
  assert.equal(url, `/api/agent/blog/agent/chat/?session_key=visitor-session&limit=${BLOG_AGENT_HISTORY_PAGE_SIZE}`);
});

test("buildBlogAgentHistoryUrl：session_key 为空返回空串，调用方跳过请求", () => {
  assert.equal(buildBlogAgentHistoryUrl(""), "");
});

test("buildBlogAgentHistoryUrl：before 游标与自定义 limit 拼接", () => {
  const url = buildBlogAgentHistoryUrl("visitor-session", { before: 42, limit: 8 });
  assert.equal(url, "/api/agent/blog/agent/chat/?session_key=visitor-session&limit=8&before=42");
});

test("buildBlogAgentHistoryUrl：session_key 特殊字符需编码", () => {
  const url = buildBlogAgentHistoryUrl("a b&c");
  const params = new URLSearchParams(url.split("?")[1] ?? "");
  assert.equal(params.get("session_key"), "a b&c");
});

test("mapBlogAgentHistoryMessages：保留后端 id 且映射 sources", () => {
  const messages = mapBlogAgentHistoryMessages([
    { id: 7, role: "user", content: "你好", sources: [] },
    { id: 8, role: "agent", content: "回答", sources: [{ title: "README", kind: "doc", content: "", score: 1, url: "" }] },
  ]);
  assert.equal(messages.length, 2);
  assert.deepEqual(
    messages.map((message: BlogAgentChatMessage) => message.id),
    [7, 8]
  );
  assert.equal(messages[0].role, "user");
  assert.equal(messages[1].sources?.[0].title, "README");
});

test("mapBlogAgentHistoryMessages：同 id 去重、非法 role 回退 agent", () => {
  const messages = mapBlogAgentHistoryMessages([
    { id: 3, role: "user", content: "重复" },
    { id: 3, role: "user", content: "重复" },
    { role: "unknown", content: "本地消息" },
  ]);
  assert.equal(messages.length, 2);
  assert.equal(messages[1].role, "agent");
});

test("mergeOlderBlogAgentMessages：prepend 更早消息并按 id 去重，本地消息原样保留", () => {
  const current: BlogAgentChatMessage[] = [
    { role: "agent", content: "欢迎语（本地消息，无 id）" },
    { id: 5, role: "user", content: "m5" },
    { id: 6, role: "agent", content: "m6" },
  ];
  const older: BlogAgentChatMessage[] = [
    { id: 3, role: "user", content: "m3" },
    { id: 5, role: "user", content: "m5 重复" },
  ];
  const merged = mergeOlderBlogAgentMessages(current, older);
  assert.deepEqual(
    merged.map((message) => message.id ?? null),
    [3, null, 5, 6]
  );
  assert.equal(merged[0].content, "m3");
  assert.equal(merged[1].content, "欢迎语（本地消息，无 id）");
  // 不改入参
  assert.equal(current.length, 3);
});
