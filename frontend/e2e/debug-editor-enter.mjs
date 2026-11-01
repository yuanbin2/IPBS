import { chromium } from "@playwright/test";

const base = "http://127.0.0.1:5174";
const slug = "5577如何在-javascript中实现事件总线并在组件间传递消息";
const browser = await chromium.launch({ channel: process.env.E2E_BROWSER_CHANNEL || undefined });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

await page.goto(`${base}/login`);
await page.fill('input[placeholder="用户名"]', "wxbroute");
await page.fill('input[placeholder="密码，至少 8 位"]', "483900336");
await page.click('button[type="submit"]');
await page.waitForTimeout(2000);

await page.goto(`${base}/blog/${encodeURIComponent(slug)}`);
await page.waitForSelector('.vditor-wysiwyg [contenteditable="true"]', { timeout: 20000 });
await page.waitForTimeout(1200);

// 劫持滚动 API，抓「谁把视图滚回顶部」
await page.evaluate(() => {
  const log = (window.__scrollLog = []);
  const record = (kind, target, detail) => {
    log.push({ kind, target: target.className?.toString?.().slice(0, 40) ?? target.tagName, detail: String(detail).slice(0, 80) });
  };
  const origScrollTo = Element.prototype.scrollTo;
  Element.prototype.scrollTo = function (...args) {
    record("el.scrollTo", this, args[0]);
    return origScrollTo.apply(this, args);
  };
  const origScrollIntoView = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = function (...args) {
    record("el.scrollIntoView", this, args[0]);
    return origScrollIntoView.apply(this, args);
  };
  ["scrollTop", "scrollLeft"].forEach((prop) => {
    const desc = Object.getOwnPropertyDescriptor(Element.prototype, prop);
    Object.defineProperty(Element.prototype, prop, {
      get: desc.get,
      set(value) {
        if (Math.abs(value - this[prop]) > 60) record(`set ${prop}`, this, `→ ${Math.round(value)}`);
        desc.set.call(this, value);
      },
      configurable: true,
    });
  });
});

const metrics = () =>
  page.evaluate(() => {
    const main = document.querySelector(".article-main") || document.scrollingElement;
    const editor = document.querySelector('.vditor-wysiwyg [contenteditable="true"]');
    const sel = window.getSelection();
    let index = -1;
    if (sel?.anchorNode && editor) {
      let block = sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement;
      while (block && block.parentElement && block.parentElement !== editor) block = block.parentElement;
      index = [...editor.children].indexOf(block);
    }
    return {
      windowY: Math.round(window.scrollY),
      mainTop: Math.round(main.scrollTop),
      caretBlock: index,
      editorTopInView: Math.round(editor.getBoundingClientRect().top),
    };
  });

// 滚到文章中部，让光标块处于视口内
await page.evaluate(() => {
  const editor = document.querySelector('.vditor-wysiwyg [contenteditable="true"]');
  const blocks = [...editor.children];
  const target = blocks[14];
  target.scrollIntoView({ block: "center" });
});
await page.waitForTimeout(400);

console.log("滚动定位后:", JSON.stringify(await metrics()));

// 在视口内的空行上放光标并回车
const placed = await page.evaluate(() => {
  const editor = document.querySelector('.vditor-wysiwyg [contenteditable="true"]');
  const blocks = [...editor.children];
  const idx = blocks.findIndex((b) => !b.textContent.trim());
  if (idx < 0) return -1;
  const target = blocks[idx];
  target.scrollIntoView({ block: "center" });
  const range = document.createRange();
  if (target.firstChild) range.setStart(target.firstChild, 0);
  else range.setStart(target, 0);
  range.collapse(true);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  return idx;
});
await page.waitForTimeout(400);
console.log("光标放在空行块#", placed, JSON.stringify(await metrics()));

await page.keyboard.press("Enter");
await page.waitForTimeout(300);
console.log("回车后 +300ms:", JSON.stringify(await metrics()));
await page.waitForTimeout(800);
const final = await metrics();
console.log("回车后 +1100ms:", JSON.stringify(final));
const scrollLog = await page.evaluate(() => window.__scrollLog);
console.log("滚动劫持日志:", JSON.stringify(scrollLog.slice(-12), null, 0));

await browser.close();
