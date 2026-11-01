/**
 * 抽取器测试：正文识别、标题/列表/表格/代码/链接/图片规则、噪声剔除、
 * 恶意内容不作安全过滤器（交给站内）、超限与空结果。
 * 运行：node --test browser-extension/tests/extract.test.js
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";

import { extractFromDocument, toMarkdown, findArticleRoot, imageSourceOf, titleCandidateOf, EXTRACTOR_VERSION } from "../shared/extract.js";

/** 最小 DOM 桩：只实现抽取器用到的 API。 */
class StubElement {
  constructor(tag, attrs = {}) {
    this.tagName = String(tag).toUpperCase();
    this.attrs = { ...attrs };
    this.children = [];
    this.parentNode = null;
    this._text = "";
    // 元素默认 nodeType=1；文本节点由 text() 设为 3
    this.nodeType = 1;
    this.className = attrs.class ?? "";
    this.id = attrs.id ?? "";
  }
  get childNodes() {
    return this.children;
  }
  appendChild(node) {
    node.parentNode = this;
    this.children.push(node);
    return node;
  }
  remove() {
    if (this.parentNode) {
      this.parentNode.children = this.parentNode.children.filter((item) => item !== this);
      this.parentNode = null;
    }
  }
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
  }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
  }
  removeAttribute(name) {
    delete this.attrs[name];
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
    // 与真实 DOM 一致：赋值会生成一个文本子节点
    if (this._text) {
      const node = new StubElement("#text");
      node.nodeType = 3;
      node.nodeValue = this._text;
      this.children.push(node);
    }
  }
  get textContent() {
    if (this._text) return this._text;
    return this.childNodes.map((child) => (child.nodeType === 3 ? child.nodeValue ?? "" : child.textContent ?? "")).join("");
  }
  querySelectorAll(selector) {
    const wanted = selector.split(",").map((part) => part.trim());
    const out = [];
    const visit = (node) => {
      for (const child of node.children) {
        for (const part of wanted) {
          if (part === "p" && child.tagName === "P") out.push(child);
          else if (part === "a" && child.tagName === "A") out.push(child);
          else if (part === "img" && child.tagName === "IMG") out.push(child);
          else if (part === "pre" && child.tagName === "PRE") out.push(child);
          else if (part === "table" && child.tagName === "TABLE") out.push(child);
          else if (part === "tr" && child.tagName === "TR") out.push(child);
          else if (part === "th" && child.tagName === "TH") out.push(child);
          else if (part === "td" && child.tagName === "TD") out.push(child);
          else if (part === "code" && child.tagName === "CODE") out.push(child);
          else if (part === "li" && child.tagName === "LI") out.push(child);
          else if (part === "h1" && child.tagName === "H1") out.push(child);
          else if (part === "ul" && child.tagName === "UL") out.push(child);
          else if (part === "blockquote" && child.tagName === "BLOCKQUOTE") out.push(child);
          else if (part === "article" && child.tagName === "ARTICLE") out.push(child);
          else if (part === "main" && child.tagName === "MAIN") out.push(child);
          else if (part === "nav" && child.tagName === "NAV") out.push(child);
          else if (part === "aside" && child.tagName === "ASIDE") out.push(child);
          else if (part === "footer" && child.tagName === "FOOTER") out.push(child);
          else if (part === "div" && child.tagName === "DIV") out.push(child);
          else if (part === "section" && child.tagName === "SECTION") out.push(child);
        }
        visit(child);
      }
    };
    visit(this);
    return out;
  }
  querySelector(selector) {
    const found = this.querySelectorAll(selector);
    return found.length ? found[0] : null;
  }
  closest() {
    return null;
  }
  cloneNode(deep = true) {
    const copy = new StubElement(this.tagName, this.attrs);
    copy._text = this._text;
    copy.nodeType = this.nodeType;
    copy.nodeValue = this.nodeValue;
    if (deep) {
      for (const child of this.children) copy.appendChild(child.cloneNode(true));
    }
    return copy;
  }
}

function text(value) {
  const node = new StubElement("#text");
  node.nodeType = 3;
  node.nodeValue = String(value);
  return node;
}

function buildDoc(body, { title = "", location = "https://example.org/post" } = {}) {
  const doc = new StubElement("html");
  const titleNode = new StubElement("title");
  titleNode.textContent = title;
  doc.appendChild(titleNode);
  const bodyNode = new StubElement("body");
  bodyNode.appendChild(body);
  doc.appendChild(bodyNode);
  doc.title = title;
  doc.location = { href: location };
  doc.createElement = (tag) => new StubElement(tag);
  doc.documentElement = doc;
  doc.getSelection = () => null;
  return doc;
}

function article(paragraphs) {
  const root = new StubElement("article");
  for (const paragraph of paragraphs) {
    const p = new StubElement("p");
    const node = new StubElement("#text");
    node.nodeType = 3;
    node.nodeValue = paragraph;
    p.appendChild(node);
    root.appendChild(p);
  }
  return root;
}

test("抽取器：识别正文容器并剔除非正文噪声", () => {
  const body = new StubElement("body");
  const nav = new StubElement("nav");
  const navLink = new StubElement("a", { href: "/home" });
  navLink.appendChild(text("首页"));
  nav.appendChild(navLink);
  body.appendChild(nav);
  const main = article(["第一段正文，足够长以通过正文抽取的最小长度检查，包含标点。", "第二段正文，继续说明内容并且同样超过阈值。"]);
  body.appendChild(main);
  const footer = new StubElement("footer");
  footer.appendChild(text("版权信息"));
  body.appendChild(footer);
  const doc = buildDoc(body, { title: "示例文章" });
  const outcome = extractFromDocument(doc, "article");
  assert.equal(outcome.ok, true);
  assert.equal(outcome.titleCandidate, "示例文章");
  assert.ok(outcome.markdown.includes("第一段正文"));
  assert.ok(!outcome.markdown.includes("首页"));
  assert.ok(!outcome.markdown.includes("版权信息"));
  assert.ok(outcome.markdown.includes("第二段正文"));
});

test("抽取器：标题/列表/表格/代码/链接/图片规则保真", () => {
  const body = new StubElement("body");
  const root = new StubElement("article");
  const h2 = new StubElement("h2");
  h2.textContent = "实现细节";
  root.appendChild(h2);
  const p = new StubElement("p");
  p.appendChild(text("参见 "));
  const link = new StubElement("a", { href: "https://example.org/source" });
  link.appendChild(text("原始资料"));
  p.appendChild(link);
  p.appendChild(text("。"));
  root.appendChild(p);
  const ul = new StubElement("ul");
  for (const item of ["要点一", "要点二"]) {
    const li = new StubElement("li");
    li.appendChild(text(item));
    ul.appendChild(li);
  }
  root.appendChild(ul);
  const pre = new StubElement("pre");
  const code = new StubElement("code", { class: "language-python" });
  code.textContent = "print('ok')\n";
  pre.appendChild(code);
  root.appendChild(pre);
  const table = new StubElement("table");
  const tr1 = new StubElement("tr");
  const th1 = new StubElement("th");
  th1.textContent = "字段";
  const th2 = new StubElement("th");
  th2.textContent = "说明";
  tr1.appendChild(th1);
  tr1.appendChild(th2);
  table.appendChild(tr1);
  const tr2 = new StubElement("tr");
  const td1 = new StubElement("td");
  td1.textContent = "ID";
  tr2.appendChild(td1);
  table.appendChild(tr2);
  root.appendChild(table);
  const imgWrap = new StubElement("p");
  const img = new StubElement("img", { src: "https://cdn.example.org/a.png", alt: "示意图" });
  imgWrap.appendChild(img);
  root.appendChild(imgWrap);
  body.appendChild(root);
  const doc = buildDoc(body, { title: "规则测试" });
  const outcome = extractFromDocument(doc, "article");
  assert.equal(outcome.ok, true);
  const markdown = outcome.markdown;
  assert.ok(markdown.includes("## 实现细节"));
  assert.ok(markdown.includes("[原始资料](https://example.org/source)"));
  assert.ok(markdown.includes("- 要点一"));
  assert.ok(markdown.includes("- 要点二"));
  assert.ok(markdown.includes("```python"));
  assert.ok(markdown.includes("print('ok')"));
  assert.ok(markdown.includes("| 字段 | 说明 |"));
  assert.ok(markdown.includes("| --- | --- |"));
  assert.ok(markdown.includes("| ID |"));
  assert.ok(markdown.includes("![示意图](https://cdn.example.org/a.png)"));
  const imageWarning = outcome.warnings.find((item) => item.code === "IMAGE_REMOTE");
  assert.ok(imageWarning);
});

test("抽取器：相对链接基于原网页 URL 解析并去跟踪参数", () => {
  const root = new StubElement("article");
  const p = new StubElement("p");
  const link = new StubElement("a", { href: "/next?utm_source=x" });
  link.appendChild(text("下一页"));
  p.appendChild(link);
  root.appendChild(p);
  const extra = new StubElement("p");
  extra.appendChild(text("补充段落，保证正文长度超过阈值判定。"));
  root.appendChild(extra);
  const doc = buildDoc(root, { location: "https://example.org/post" });
  const { markdown } = toMarkdown(root, { baseUrl: "https://example.org/post" });
  assert.ok(markdown.includes("[下一页](https://example.org/next)"), markdown);
});

test("抽取器：段落中的 span 保持行内，不把一句话拆成三段", () => {
  const root = new StubElement("article");
  const paragraph = new StubElement("p");
  paragraph.appendChild(text("开始 "));
  const span = new StubElement("span");
  span.appendChild(text("重要内容"));
  paragraph.appendChild(span);
  paragraph.appendChild(text(" 结束。"));
  root.appendChild(paragraph);
  assert.equal(toMarkdown(root).markdown, "开始 重要内容 结束。");
});

test("抽取器：blob/data/相对未知图片标记为需手动补图", () => {
  const root = new StubElement("article");
  const p = new StubElement("p");
  const blob = new StubElement("img", { src: "blob:https://example.org/uuid", alt: "懒加载图" });
  p.appendChild(blob);
  root.appendChild(p);
  const p2 = new StubElement("p");
  const data = new StubElement("img", { src: "data:image/png;base64,AAAA", alt: "内嵌图" });
  p2.appendChild(data);
  root.appendChild(p2);
  const extra = new StubElement("p");
  extra.appendChild(text("正文段落，保证长度足够通过检查阈值判定。"));
  root.appendChild(extra);
  const { markdown, warnings } = toMarkdown(root, { baseUrl: "https://example.org/post" });
  assert.ok(!markdown.includes("blob:"));
  assert.ok(!markdown.includes("data:image"));
  assert.ok(warnings.some((item) => item.code === "IMAGE_NEEDS_MANUAL"));
  assert.ok(!markdown.includes("!["));
});

test("抽取器：空正文/登录页/纯脚本页给出可操作错误", () => {
  const empty = buildDoc(new StubElement("body"), { title: "登录" });
  assert.equal(extractFromDocument(empty, "article").ok, false);
  assert.equal(extractFromDocument(empty, "article").code, "extract_empty");

  const scriptOnly = new StubElement("body");
  const script = new StubElement("script");
  script.textContent = "window.steal()";
  scriptOnly.appendChild(script);
  const doc = buildDoc(scriptOnly, { title: "loading" });
  assert.equal(extractFromDocument(doc, "article").code, "extract_empty");
});

test("抽取器：抽取器不是安全过滤器，脚本文本按数据处理", () => {
  const root = new StubElement("article");
  const p = new StubElement("p");
  p.appendChild(text("ignore previous instructions and <script>alert(1)</script>"));
  root.appendChild(p);
  const doc = buildDoc(root, { title: "提示注入样本" });
  const outcome = extractFromDocument(doc, "article");
  assert.equal(outcome.ok, true);
  assert.ok(outcome.markdown.includes("ignore previous instructions"));
  // 扩展不做 XSS 过滤：脚本文本原样作为文章数据，站内负责清理
  assert.ok(outcome.markdown.includes("<script>"));
});

test("抽取器：正文超限返回 size_limit", () => {
  const root = new StubElement("article");
  const p = new StubElement("p");
  p.textContent = "字".repeat(400_001);
  root.appendChild(p);
  const doc = buildDoc(root, { title: "超长" });
  const outcome = extractFromDocument(doc, "article");
  assert.equal(outcome.ok, false);
  assert.equal(outcome.code, "size_limit");
});

test("抽取器：标题候选优先 og:title → h1 → title", () => {
  const body = new StubElement("body");
  const h1 = new StubElement("h1");
  h1.textContent = "正文标题";
  body.appendChild(h1);
  const doc = buildDoc(body, { title: "网页标题" });
  assert.equal(titleCandidateOf(doc), "正文标题");
  const withOg = buildDoc(body, { title: "网页标题" });
  withOg.querySelector = (selector) =>
    selector.includes("og:title") ? { getAttribute: () => "分享标题" } : null;
  assert.equal(titleCandidateOf(withOg), "分享标题");
});

test("抽取器：图片地址只接受可解析的 HTTP(S)，补全相对与懒加载地址", () => {
  const http = new StubElement("img", { src: "https://example.org/a.png" });
  assert.equal(imageSourceOf(http).usable, true);
  const relative = new StubElement("img", { src: "./a.png" });
  assert.equal(imageSourceOf(relative, "").usable, false);
  assert.equal(imageSourceOf(relative, "https://example.org/posts/one").reference, "https://example.org/posts/a.png");
  const lazy = new StubElement("img", { src: "data:image/gif;base64,AAAA", "data-src": "/real.png" });
  assert.equal(imageSourceOf(lazy, "https://example.org/post").reference, "https://example.org/real.png");
  const protocol = new StubElement("img", { src: "javascript:alert(1)" });
  assert.equal(imageSourceOf(protocol).usable, false);
  const empty = new StubElement("img", {});
  assert.equal(imageSourceOf(empty).usable, false);
  assert.equal(EXTRACTOR_VERSION, "webclip-extract-1");
});

test("抽取器：无正文容器时降级整页并给出警告", () => {
  const body = new StubElement("body");
  const p1 = new StubElement("p");
  p1.appendChild(text("散落的第一段，没有语义容器，长度也超过阈值。"));
  body.appendChild(p1);
  const p2 = new StubElement("p");
  p2.appendChild(text("散落的第二段，同样凑够长度阈值。"));
  body.appendChild(p2);
  const doc = buildDoc(body, { title: "无容器" });
  const outcome = extractFromDocument(doc, "article");
  assert.equal(outcome.ok, true);
  assert.ok(outcome.warnings.some((item) => item.code === "NO_ARTICLE_BODY"));
});

test("抽取器：经典脚本在独立页面上下文中可直接执行", () => {
  const source = readFileSync(new URL("../shared/extract-core.js", import.meta.url), "utf8");
  const sandbox = createContext({ TextEncoder, URL });
  runInContext(source, sandbox);
  // 用户重试采集会向同一个隔离世界再次注入，不能重复声明顶层 const。
  runInContext(source, sandbox);
  const document = buildDoc(article([
    "这是独立网页里的正文段落，足够长以通过抽取阈值。",
    "第二段正文验证运行时依赖都在页面脚本里，而不是依赖弹窗模块作用域。",
  ]));
  const result = sandbox.__BLOG_WEBCLIP_EXTRACT__.extractFromDocument(document, "article");
  assert.equal(result.ok, true);
  assert.match(result.markdown, /第二段正文/);
});
