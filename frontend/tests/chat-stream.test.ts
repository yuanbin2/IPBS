import assert from "node:assert/strict";
import test from "node:test";
import { applyAnswerEvent, SseEventParser } from "../src/features/chat/utils/streamProtocol.ts";

test("SSE parser handles split frames, CRLF, and multiple data lines", () => {
  const parser = new SseEventParser();
  assert.deepEqual(parser.push('data: {"type":"answer_'), []);
  assert.deepEqual(parser.push('delta","text":"前"}\r\n\r\n'), [{ type: "answer_delta", text: "前" }]);
  assert.deepEqual(parser.push('data: {"type":"progress",\n'), []);
  assert.deepEqual(parser.push('data: "detail":"检索中"}\n\n'), [
    { type: "progress", detail: "检索中" }
  ]);
});

test("UTF-8 decoder and SSE parser preserve split Chinese characters", () => {
  const bytes = new TextEncoder().encode('data: {"type":"answer_delta","text":"中文"}\n\n');
  const split = bytes.indexOf(0xe4) + 1;
  const decoder = new TextDecoder();
  const parser = new SseEventParser();
  assert.deepEqual(parser.push(decoder.decode(bytes.slice(0, split), { stream: true })), []);
  const events = parser.push(decoder.decode(bytes.slice(split), { stream: true }));
  assert.equal(events[0]?.text, "中文");
});

test("answer deltas, snapshot repair, and final response produce saved text", () => {
  let answer = "";
  answer = applyAnswerEvent(answer, { type: "answer_delta", text: "```py\npri" });
  assert.equal(answer, "```py\npri"); // Render as plain text while Markdown is incomplete.
  answer = applyAnswerEvent(answer, { type: "answer_delta", text: "nt(1)\n```" });
  answer = applyAnswerEvent(answer, { type: "answer_snapshot", text: "最终答案" });
  answer = applyAnswerEvent(answer, { type: "response", answer: "最终答案" });
  assert.equal(answer, "最终答案");
});

test("malformed SSE JSON fails instead of silently dropping a result", () => {
  const parser = new SseEventParser();
  assert.throws(() => parser.push("data: {bad json}\n\n"), SyntaxError);
});

test("done and error events do not append uncommitted partial text", () => {
  let answer = applyAnswerEvent("", { type: "answer_delta", text: "暂存" });
  answer = applyAnswerEvent(answer, { type: "error", detail: "超时" });
  answer = applyAnswerEvent(answer, { type: "done", status: "failed" });
  assert.equal(answer, "暂存");
});
