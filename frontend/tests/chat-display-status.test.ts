import assert from "node:assert/strict";
import test from "node:test";
import { displayRunFailure, displayStage } from "../src/features/chat/utils/displayStatus.ts";

test("AI progress follows known backend stages without exposing query text", () => {
  assert.equal(displayStage("supervisor -> rag_agent (private question)"), "正在检索相关资料");
  assert.equal(displayStage("internet_query_rewrite -> private query"), "正在查找网页资料");
  assert.equal(displayStage("internet_query_rewrite -> private query", true), "已查找网页资料");
  assert.equal(displayStage("mcp_tool_agent -> executing tool"), "正在使用已授权工具");
  assert.equal(displayStage("opaque: private document body"), "正在处理请求");
  assert.equal(displayStage("审批请求已保存", true), "已提交操作审批");
  assert.equal(displayStage("此路径不提供生成期正文增量，显示最终回答"), "正在处理请求，完成后显示回答");
});

test("run failures offer next steps without showing raw error codes", () => {
  assert.match(displayRunFailure("failed", "TimeoutError"), /缩短问题后重试/);
  assert.match(displayRunFailure("cancelled"), /已取消/);
  assert.match(displayRunFailure("failed", "secret failure"), /稍后重试/);
  assert.doesNotMatch(displayRunFailure("failed", "secret failure"), /secret/);
});
