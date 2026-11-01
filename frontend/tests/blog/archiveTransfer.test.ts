import assert from "node:assert/strict";
import { test } from "node:test";

import {
  MAX_ARCHIVE_BYTES,
  buildExportUrl,
  countImported,
  parseContentDispositionFilename,
  summarizeImportPlan,
  validateArchiveFile,
} from "../../src/features/blog/utils/archiveTransfer.ts";

test("buildExportUrl 支持单个与多个领域", () => {
  assert.equal(buildExportUrl([]), "");
  assert.equal(
    buildExportUrl(["168a4874-6ab7-4daa-8c30-7598405571ce"]),
    "/api/agent/blog/collections/export/?ids=168a4874-6ab7-4daa-8c30-7598405571ce",
  );
  assert.equal(
    buildExportUrl(["aaa", " bbb "]),
    "/api/agent/blog/collections/export/?ids=aaa%2Cbbb",
  );
});

test("buildExportUrl 过滤空值", () => {
  assert.equal(buildExportUrl(["", "  ", "ccc"]), "/api/agent/blog/collections/export/?ids=ccc");
});

test("parseContentDispositionFilename 兼容 RFC5987 与普通形式", () => {
  assert.equal(
    parseContentDispositionFilename('attachment; filename="blog-collections-2-20261011.zip"'),
    "blog-collections-2-20261011.zip",
  );
  assert.equal(
    parseContentDispositionFilename("attachment; filename*=UTF-8''blog-collection-%E7%AC%94%E8%AE%B0.zip"),
    "blog-collection-笔记.zip",
  );
  assert.equal(parseContentDispositionFilename(null), "");
  assert.equal(parseContentDispositionFilename("attachment"), "");
});

test("validateArchiveFile 只接受合规 zip", () => {
  assert.equal(validateArchiveFile(null).ok, false);
  assert.equal(validateArchiveFile({ name: "a.txt", size: 10 }).ok, false);
  assert.equal(validateArchiveFile({ name: "a.zip", size: MAX_ARCHIVE_BYTES + 1 }).ok, false);
  assert.equal(validateArchiveFile({ name: "a.ZIP", size: 1024 }).ok, true);
});

test("summarizeImportPlan 汇总数量并标记冲突", () => {
  const summary = summarizeImportPlan({
    totals: { collections: 2, articles: 5, images: 3, nodes: 4, skipped_articles: 1 },
    collections: [
      { title: "领域甲", articles: 3, images: 3, skipped_articles: 1, missing_images: ["a.png"] },
      { title: "领域乙", articles: 2, images: 0 },
    ],
    warnings: ["领域甲：1 张图片在包里缺失"],
  });
  assert.equal(summary.lines.length, 3);
  assert.match(summary.lines[0], /2 个领域/);
  assert.match(summary.lines[1], /3 篇/);
  assert.match(summary.lines[1], /1 篇已存在/);
  assert.match(summary.lines[1], /1 张图缺失/);
  assert.equal(summary.hasConflict, true);
  assert.equal(summary.warnings.length, 1);
});

test("summarizeImportPlan 空结果不报错", () => {
  assert.deepEqual(summarizeImportPlan(null), { lines: [], warnings: [], hasConflict: false });
});

test("countImported 只统计真正创建的领域", () => {
  assert.equal(countImported([{ status: "created" }, { status: "skipped" }]), 1);
  assert.equal(countImported(undefined), 0);
});
