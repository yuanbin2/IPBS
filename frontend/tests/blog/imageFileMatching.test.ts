/**
 * 导入文档图片匹配的单测：引用提取、文件匹配、导入规划分派。
 * 运行：node --test tests/blog/
 */

import test from "node:test";
import assert from "node:assert/strict";
import {
  findMarkdownImages,
  matchImageFile,
  planMarkdownImageImport,
} from "../../src/features/blog/utils/imageFileMatching.ts";

function file(name: string, size = 10): File {
  return new File([new Uint8Array(size)], name, { type: "image/png" });
}

test("findMarkdownImages：提取引用、去重、标记远程", () => {
  const markdown = [
    "![架构图](images/arch.png)",
    "![截图](https://example.com/a.png)",
    '![重复](images/arch.png "title")',
    "![空]()",
  ].join("\n");
  const refs = findMarkdownImages(markdown);
  assert.deepEqual(refs.map((ref) => [ref.reference, ref.remote]), [
    ["images/arch.png", false],
    ["https://example.com/a.png", true],
  ]);
  assert.equal(refs[1]?.alt, "截图");
});

test("matchImageFile：按路径后缀或唯一文件名匹配，歧义返回 null", () => {
  const files = [file("posts/img/arch.png"), file("cover.png"), file("dup.png"), file("dup.png")];
  assert.equal(matchImageFile("img/arch.png", files)?.name, "posts/img/arch.png");
  assert.equal(matchImageFile("cover.png", files)?.name, "cover.png");
  assert.equal(matchImageFile("missing.png", files), null);
  assert.equal(matchImageFile("dup.png", files), null, "两个同名文件无法唯一匹配");
});

test("planMarkdownImageImport：本地匹配优先，远程按预算抓取，其余保留", () => {
  const refs = findMarkdownImages(
    [
      "![本地图](images/arch.png)",
      "![远程图](https://cdn.example.com/x.png)",
      "![远程顶替](https://old.example.com/cover.png)",
      "![抓不到](https://private.example.com/y.png)",
      "![缺失](images/lost.png)",
    ].join("\n"),
  );
  const files = [file("arch.png"), file("cover.png")];
  const plan = planMarkdownImageImport(refs, files, { fetchRemote: true, maxRemote: 1 });

  assert.deepEqual(plan.matched.map((item) => item.reference), [
    "images/arch.png",
    "https://old.example.com/cover.png",
  ], "本地文件命中的引用（含远程地址被顶替）都走上传");
  assert.deepEqual(plan.matched.map((item) => item.token), [
    "![本地图](images/arch.png)",
    "![远程顶替](https://old.example.com/cover.png)",
  ], "携带原始 Markdown 片段供精确整段替换");
  assert.deepEqual(plan.remoteUnmatched.map((item) => item.reference), [
    "https://cdn.example.com/x.png",
  ], "远程引用按预算抓取");
  assert.deepEqual(plan.unmatched.map((item) => item.reference), [
    "https://private.example.com/y.png",
    "images/lost.png",
  ], "预算外的远程引用与未匹配的本机路径保留原地址");
});

test("findMarkdownImages：token 保留空 alt 与标题变体，整段替换不失配", () => {
  const refs = findMarkdownImages(["![](images/a.png)", '![标题](https://e.com/b.png "v1")'].join("\n"));
  assert.deepEqual(refs.map((ref) => ref.token), ["![](images/a.png)", '![标题](https://e.com/b.png "v1")']);
});

test("planMarkdownImageImport：关闭抓取时远程全部保留原地址", () => {
  const refs = findMarkdownImages("![远程](https://example.com/a.png)");
  const plan = planMarkdownImageImport(refs, [], { fetchRemote: false });
  assert.equal(plan.matched.length, 0);
  assert.equal(plan.remoteUnmatched.length, 0);
  assert.deepEqual(plan.unmatched.map((item) => item.reference), ["https://example.com/a.png"]);
});
