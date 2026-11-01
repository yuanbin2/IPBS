/**
 * B-045 调试脚本：手动驱动 OCR 流程并打印 worker/页面控制台输出。
 * 运行：node e2e/debug-ocr.mjs
 */
import { chromium } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { startServices } from "./start-services.mjs";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const fixtures = resolve(frontendRoot, "e2e/fixtures");

const stop = await startServices();
// 等 Vite 就绪（startServices 异步返回后端口可能还没开始监听）
for (let attempt = 0; attempt < 150; attempt += 1) {
  try {
    const response = await fetch("http://127.0.0.1:5173/login");
    if (response.status < 500) break;
  } catch {
    // still starting
  }
  await new Promise((r) => setTimeout(r, 200));
}
let exitCode = 0;
try {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage();
  page.on("console", (message) => {
    console.log(`[console:${message.type()}]`, message.text().slice(0, 500));
  });
  page.on("pageerror", (error) => console.log("[pageerror]", error.message.slice(0, 800)));
  page.on("requestfailed", (request) => console.log("[requestfailed]", request.url().slice(0, 200), request.failure()?.errorText));

  await page.goto("http://127.0.0.1:5173/login?redirect=%2Fblog");
  await page.getByPlaceholder("用户名").fill("upload-e2e-operator");
  await page.getByPlaceholder("密码，至少 8 位").fill("Upload-e2e-only-2026!");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL(/\/blog$/);
  await page.getByRole("button", { name: "写博客", exact: true }).click();
  await page.locator(".vditor-wysiwyg").waitFor();
  await page.getByRole("button", { name: "截图识别", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: /截图识别为 Markdown/ });
  await dialog.waitFor();

  const bytes = await readFile(resolve(fixtures, "ocr-zh-article.png"));
  await dialog.locator('input[type="file"]').setInputFiles({ name: "ocr-zh-article.png", mimeType: "image/png", buffer: bytes });
  console.log("--- file uploaded, waiting for OCR result ---");
  const started = Date.now();
  try {
    await dialog.locator(".ocr-block-card").first().waitFor({ timeout: 150_000 });
    console.log(`--- OCR finished in ${Date.now() - started}ms ---`);
    const cards = await dialog.locator(".ocr-block-card").count();
    console.log("blocks:", cards);
    for (let i = 0; i < cards; i += 1) {
      const value = await dialog.locator(".ocr-block-card textarea").nth(i).inputValue();
      console.log(`block ${i}:`, JSON.stringify(value.slice(0, 200)));
    }
    const preview = await dialog.locator(".ocr-preview-body").innerText();
    console.log("preview:", JSON.stringify(preview.slice(0, 600)));
  } catch (error) {
    console.log("--- OCR did not finish ---", error.message.split("\n")[0]);
    exitCode = 1;
  }
  await browser.close();
} catch (error) {
  console.log("[fatal]", error.message);
  exitCode = 1;
} finally {
  await stop();
}
process.exit(exitCode);
