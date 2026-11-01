/**
 * 标签订入解析工具的单测（B-061 回归）。
 *
 * 核心回归点：**中文全角逗号必须能分隔标签**，否则一次输入会被整串当成一个标签。
 * 同时确认空格不作为分隔符（「Agentic RAG」这类标签本身含空格）。
 *
 * 运行：npm run test:unit
 */

import test from "node:test";
import assert from "node:assert/strict";
import {
  TAG_COUNT_LIMIT,
  TAG_NAME_MAX_LENGTH,
  mergeTagNames,
  normalizeTagList,
  parseTagInput,
} from "../../src/features/blog/utils/tagInput.ts";

test("parseTagInput：英文逗号分隔（原有行为保持）", () => {
  assert.deepEqual(parseTagInput("Vue,Django,RAG"), ["Vue", "Django", "RAG"]);
});

test("parseTagInput：中文全角逗号分隔（B-061 核心回归）", () => {
  assert.deepEqual(parseTagInput("算法，基础算法，快速排序"), ["算法", "基础算法", "快速排序"]);
});

test("parseTagInput：顿号、中英文分号、换行都能分隔", () => {
  assert.deepEqual(parseTagInput("甲、乙"), ["甲", "乙"]);
  assert.deepEqual(parseTagInput("甲;乙；丙"), ["甲", "乙", "丙"]);
  assert.deepEqual(parseTagInput("甲\n乙\r\n丙"), ["甲", "乙", "丙"]);
});

test("parseTagInput：中英文分隔符混用", () => {
  assert.deepEqual(parseTagInput("Vue，Django、RAG；LangGraph"), ["Vue", "Django", "RAG", "LangGraph"]);
});

test("parseTagInput：空格不是分隔符（含空格的标签必须完整保留）", () => {
  assert.deepEqual(parseTagInput("Agentic RAG"), ["Agentic RAG"]);
  assert.deepEqual(parseTagInput("Agentic RAG,项目架构"), ["Agentic RAG", "项目架构"]);
});

test("parseTagInput：去掉首尾空白与粘贴带的井号", () => {
  assert.deepEqual(parseTagInput("  Vue  ,  #RAG "), ["Vue", "RAG"]);
});

test("parseTagInput：丢弃空项、大小写不敏感去重、保留首次写法", () => {
  assert.deepEqual(parseTagInput("Vue,,  ,vue,VUE"), ["Vue"]);
  assert.deepEqual(parseTagInput("，甲，，乙，"), ["甲", "乙"]);
});

test("parseTagInput：超长标签被丢弃（库表 name 上限 60）", () => {
  const ok = "x".repeat(TAG_NAME_MAX_LENGTH);
  const tooLong = "y".repeat(TAG_NAME_MAX_LENGTH + 1);
  assert.deepEqual(parseTagInput(`${ok},${tooLong}`), [ok]);
});

test("parseTagInput：数量上限生效", () => {
  const many = Array.from({ length: TAG_COUNT_LIMIT + 10 }, (_, i) => `t${i}`).join(",");
  assert.equal(parseTagInput(many).length, TAG_COUNT_LIMIT);
});

test("parseTagInput：空串与非法输入返回空数组", () => {
  assert.deepEqual(parseTagInput(""), []);
  assert.deepEqual(parseTagInput("   "), []);
  assert.deepEqual(parseTagInput(",，、;;"), []);
  assert.deepEqual(parseTagInput(undefined as unknown as string), []);
});

test("normalizeTagList：数组原样规整", () => {
  assert.deepEqual(normalizeTagList(["Vue", "RAG"]), ["Vue", "RAG"]);
  assert.deepEqual(normalizeTagList(["Vue，RAG"]), ["Vue", "RAG"]);
  assert.deepEqual(normalizeTagList(["Vue", "vue"]), ["Vue"]);
});

test("normalizeTagList：兼容旧版逗号分隔字符串（localStorage 里的老草稿）", () => {
  assert.deepEqual(normalizeTagList("Vue,RAG"), ["Vue", "RAG"]);
  assert.deepEqual(normalizeTagList("算法，基础算法"), ["算法", "基础算法"]);
  assert.deepEqual(normalizeTagList(""), []);
});

test("normalizeTagList：null / undefined / 数字等异常输入不抛错", () => {
  assert.deepEqual(normalizeTagList(null), []);
  assert.deepEqual(normalizeTagList(undefined), []);
  assert.deepEqual(normalizeTagList(123), []);
  assert.deepEqual(normalizeTagList({}), []);
});

test("mergeTagNames：合并已有标签与新输入并去重", () => {
  assert.deepEqual(mergeTagNames(["Vue", "RAG"], ["vue", "Django"]), ["Vue", "RAG", "Django"]);
});
