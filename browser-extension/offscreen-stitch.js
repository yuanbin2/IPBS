/** offscreen 入口：只做上下文标识，逻辑在 shared/local-save-page.js。 */
import { startLocalSavePage } from "./shared/local-save-page.js";
startLocalSavePage({ isOffscreen: true });
