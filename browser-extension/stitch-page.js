/** 标签页兜底入口：offscreen 不可用时由 background 打开，逻辑同上。 */
import { startLocalSavePage } from "./shared/local-save-page.js";
startLocalSavePage({ isOffscreen: false });
