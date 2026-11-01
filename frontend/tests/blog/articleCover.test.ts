import { test } from "node:test";
import assert from "node:assert/strict";

import { defaultCoverImage, firstImageUrl, isSafeImageUrl } from "../../src/features/blog/utils/articleCover.ts";

test("firstImageUrl 取 Markdown 第一张图", () => {
  const content = "# 标题\n\n![封面](/media/blog/a.png)\n\n正文\n\n![第二张](/media/blog/b.png)";
  assert.equal(firstImageUrl(content), "/media/blog/a.png");
});

test("firstImageUrl 认 HTML img 并按位置竞争", () => {
  assert.equal(firstImageUrl('<p>x</p><img src="/media/blog/html.png" alt="a" />'), "/media/blog/html.png");
  const mixed = '![早](/media/blog/first.png)\n<img src="/media/blog/second.png">';
  assert.equal(firstImageUrl(mixed), "/media/blog/first.png");
  const htmlFirst = '<img src="/media/blog/one.png">\n![晚](/media/blog/two.png)';
  assert.equal(firstImageUrl(htmlFirst), "/media/blog/one.png");
});

test("firstImageUrl 支持 title 与尖括号写法", () => {
  assert.equal(firstImageUrl('![alt](/media/blog/a.png "标题")'), "/media/blog/a.png");
  assert.equal(firstImageUrl("![alt](</media/blog/a.png>)"), "/media/blog/a.png");
});

test("firstImageUrl 跳过不安全的协议", () => {
  assert.equal(firstImageUrl("![x](data:image/png;base64,AAAA)"), null);
  assert.equal(firstImageUrl('![x](javascript:alert("1"))'), null);
  assert.equal(firstImageUrl('<img src="data:image/gif;base64,R0lGOD">'), null);
});

test("firstImageUrl 无图或空正文时返回空", () => {
  assert.equal(firstImageUrl(""), null);
  assert.equal(firstImageUrl("纯文字，没有图片"), null);
  assert.equal(firstImageUrl("![图片]()"), null);
});

test("isSafeImageUrl 只允许 http(s) 与相对路径", () => {
  assert.equal(isSafeImageUrl("https://cdn.example.com/a.png"), true);
  assert.equal(isSafeImageUrl("http://cdn.example.com/a.png"), true);
  assert.equal(isSafeImageUrl("/media/blog/a.png"), true);
  assert.equal(isSafeImageUrl("../static/a.png"), true);
  assert.equal(isSafeImageUrl("data:image/png;base64,AAA"), false);
  assert.equal(isSafeImageUrl("ftp://example.com/a.png"), false);
  assert.equal(isSafeImageUrl(""), false);
});

test("defaultCoverImage 只在封面为空时兜底", () => {
  const content = "![图](/media/blog/a.png)";
  assert.equal(defaultCoverImage("", content), "/media/blog/a.png");
  assert.equal(defaultCoverImage("   ", content), "/media/blog/a.png");
  assert.equal(defaultCoverImage("/media/blog/manual.png", content), null);
  assert.equal(defaultCoverImage("", "没有图片"), null);
});
