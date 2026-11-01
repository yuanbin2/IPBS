# 托盘截图小工具（screenshot-tray）

PixPin 式系统级截图工具：全局快捷键截图 → 悬浮条「发博客 / 存本地 / OCR 识别 / 长截图 / 取消」。
技术方案与接口查证见 `docs/system_design.md`（本工具为该设计的实现）。

## 环境与启动

- 仅支持 Windows 11；使用**项目根**虚拟环境 `.venv`（本次离线回归使用 Python 3.14、PyQt6 6.7.1），勿全局安装。
- 安装依赖（进项目根目录执行）：

  ```bat
  .venv\Scripts\python.exe -m pip install -r tools\screenshot-tray\requirements.txt
  ```

- 启动（后台运行，不弹控制台）：

  ```bat
  tools\screenshot-tray\run.bat
  ```

  或前台调试：`.venv\Scripts\python.exe tools\screenshot-tray\main.py`

## 配置

- 配置文件：`%APPDATA%\BlogScreenshotTool\config.json`（首次运行自动生成）
- 凭据文件：`%APPDATA%\BlogScreenshotTool\credentials.bin`（DPAPI 加密，绑定当前用户）
- 日志：`%APPDATA%\BlogScreenshotTool\logs\tray.log`（1MB × 3 滚动）

可在托盘菜单「打开设置…」中修改：全局热键（默认 `Ctrl+Alt+A`，即时生效）、后端地址
（默认 `http://127.0.0.1:8001`）、博客前端地址（默认 `http://127.0.0.1:5174`）、
保存目录、账号密码、开机自启（写入 HKCU Run）。

## 使用

1. 托盘图标出现后按全局热键 → 各屏出现半透明遮罩，拖拽框选（支持跨屏），Esc 取消。
2. 松开鼠标后选区旁弹出悬浮条：
   - **发博客**：自动登录（DPAPI 凭据）→ `POST /api/agent/blog/images/` 上传 →
     成功后 `![alt](/media/blog/...)` Markdown 已进剪贴板，可直接粘贴；
   - **存本地**：按 `{yyyy}/{MM}/{yyyyMMdd-HHmmss}.png` 存入配置目录；
   - **OCR 识别**（P1）：起本机端点持有 PNG，打开博客前端 `/blog` 页
     （深链 `#screenshot-handoff=...`），前端拉图后进入既有 ScreenshotOcrDialog
     本地识别链路（token 128bit 随机、5 分钟内**可重复取**以便前端失败重试；
     端点响应带 CORS 头，仅绑 localhost）；
   - **长截图**：进入滚动采集模式（见下节）；
   - **取消**：结束本轮。
3. 上传失败（断网 / 非 OPERATOR / 超 5MB / 限流 429 / 后端 5xx）→
   气泡说明原因并**自动回退存本地**。
   **未登录**时：除气泡外**直接弹出设置窗口**（聚焦账号输入框，气泡展示 8 秒），
   截图仍先存本地，登录后重试即可。

## 长截图（滚动截图）

1. 入口：悬浮条「长截图」按钮，或托盘菜单「长截图」（选区后直接进入采集）。
2. 选区固定后弹出小型控制窗（拼接预览缩略图、已采集帧数、完成/取消按钮）。若屏幕没有足够的选区外空间，抓屏瞬间临时隐藏控制窗再恢复；在选区内**分段滚动并停顿约半秒**。
3. 拼接使用 NumPy 行分区粗搜与原始相邻帧的二维像素复核，覆盖整个可能重叠范围。混合 DPI 选区固定一个输出倍率，其他屏幕片段会重采样。上限 30 帧 / 总高 30000px / 总像素 20M（先达到的限制生效）；首帧也受限。
4. 静止只提示「画面暂无变化」，不据此判断到达底部。无可靠重叠、向上滚动或周期性内容歧义时会暂停，保留已有结果；向下滚回与上一成功帧重叠的位置，点「重试」。队列处理落后时请分段停顿。
5. 点「完成」或 Esc → 拼接结果作为一张图回到悬浮条，走与普通截图同一套
   去向动作（发博客 / 存本地 / OCR 识别）。

## 注意事项

- 「发博客」要求登录 **OPERATOR 角色**账号（公开媒体接口的硬性要求）。
- 公开媒体 URL（`/media/blog/...`）未登录访客可读；私有笔记图片 URL 需鉴权，勿混用。
- 上传 PNG 不做压缩：超 5MB 直接回退存本地（P2 再考虑压缩）。
- 悬浮条动作发起即隐藏；失败回退后本轮结束（"重试上一张"为 P2）。
- 双开会被命名互斥锁拦截，第二个实例静默退出。

### 长截图拼接的已知边界

- 固定页头、页脚会在发现相同位置且有可识别纹理时从匹配区排除；页头保留一次，固定页脚从新增正文中排除。被固定元素遮住的正文无法恢复，建议框选时避开它们。
- 有纹理的固定侧栏（包括较窄的侧栏）、跨整幅动画、无有效纹理的空白或周期性表格可能无法唯一定位接缝，程序会拒绝追加并保留已有结果。请避开这些区域或缩小滚动步长。
- 完成后最多等待约 650ms 处理最后稳定画面；未形成稳定且可靠重叠的末帧不会被猜测追加。
- 仅在显式诊断时才应保存原始帧；当前实现默认不保存任何原始屏幕内容。

### 离线回归与桌面验收

在仓库根目录运行：

```bat
.venv\Scripts\python.exe -m unittest discover -s tools\screenshot-tray\tests -v
```

桌面验收使用 `tests/manual-scroll-page.html`：在 Edge 和 Chrome 分别打开文件，启动 `run.bat`；先点击页头按钮切换成非固定模式，框选普通长文区域，每次约滚 100px 并停顿半秒，至 `END-120` 后点完成并存本地，检查编号连续、末尾完整、无控制窗。随后框选蓝框内滚动容器重复；再点击页头按钮恢复固定模式并重复，检查页头只出现一次。另在双屏 100%/150% 缩放、负屏幕坐标、大选区无法放下控制窗时检查抓帧像素、鼠标滚轮穿透和 Esc 在浏览器有焦点时完成。当前这些步骤需要可操作 Windows 桌面的人工验收，离线测试不代表已完成实机验收。

## 验收清单

### P0

- [ ] `run.bat` 启动无异常，托盘出现，日志落盘，`config.json` 生成。
- [ ] 再次运行被互斥锁拦截（无双开）。
- [ ] 热键唤起遮罩：双显示器（不同缩放 100%/150%）下每屏遮罩铺满、选区颜色无错位（物理像素截取）。
- [ ] Esc 取消；选区过小视为取消。
- [ ] 悬浮条出现在选区旁且不越屏；五个按钮齐全。
- [ ] 发博客：剪贴板得到 `![...](/media/blog/...)` 且可粘贴渲染；日志可追溯。
- [ ] 存本地：生成 `<目录>/<年>/<月>/<yyyyMMdd-HHmmss>.png`。
- [ ] 人为制造失败（断网 / 超 5MB）→ 气泡说明 + 自动回退存本地。
- [ ] 未登录点「发博客」→ 气泡引导文案（约 8 秒）+ 设置窗口自动弹出且账号输入框聚焦；
      登录保存后重新发博客成功。
- [ ] 设置中改热键即时生效。

### P1

- [ ] OCR 按钮：起端点 → 打开 `/blog#screenshot-handoff=127.0.0.1:<port>/s/<token>`
      → 前端拉图进入 ScreenshotOcrDialog → 校对产出 Markdown（token 5 分钟内可重复取；
      前端 fetch 失败时展示人性化中文提示，确认托盘工具运行后可重试）。
- [ ] 「发到私有笔记」链路：`upload_note_image` 返回 `url` 形如
      `/api/agent/blog/notes/images/<id>/`（`requires_auth: true`）。
- [ ] 勾选/取消「开机自动启动」→ HKCU `...\CurrentVersion\Run` 的
      `BlogScreenshotTool` 值写入/移除生效。

### 长截图（人工验收：滚动交互无法自动化）

- [ ] 悬浮条与托盘菜单均有「长截图」入口；托盘入口选区后直接进入采集。
- [ ] 选区固定后控制窗弹出，不遮挡选区，含拼接预览缩略图、帧数、完成/取消按钮。
- [ ] 在选区内滚动页面：内容变化时自动采集，帧数递增，预览缩略图随之更新。
- [ ] 滚动动画中途不采集模糊帧（画面稳定约 0.4s 才采集）。
- [ ] 小幅缓慢滚动（约 10% 帧高，如 904×344 选区滚 30~40px）→ 正常拼接，总高精确增长，不报「无重叠」。
- [ ] 画面不变 → 控制窗提示「画面暂无变化」，不误报到底。
- [ ] 点「完成」或 Esc → 拼接结果回到悬浮条，发博客/存本地/OCR 均可用且结果正确。
- [ ] 滚动过快导致无重叠 → 控制窗报错，向下滚回重叠位置并点「重试」恢复采集；点「完成」保留已拼部分。
- [ ] 达上限（30 帧 / 总高约 30000px / 总像素约 20M）→ 自动暂停并提示点「完成」。
- [ ] 取消按钮：结束整轮长截图，不残留窗口与后台线程。
- [ ] 100%/150% 混排缩放下长截图选区内容无错位（物理像素抓取）。
- [ ] 滚动采集期间琥珀色边框在选区四周持续可见，且鼠标/滚轮完全穿透、不影响下层页面滚动。
- [ ] 长截图结果图中不含琥珀色边框线（边框不进帧）。
- [ ] 点「完成」/「取消」后边框立即消失，无残留窗口。

## 文件结构

```
tools/screenshot-tray/
├── README.md / requirements.txt / run.bat / main.py
├── app/      constants.py errors.py controller.py
├── core/     config_store.py credential_store.py log_manager.py single_instance.py
├── services/ auth_client.py blog_api_client.py local_saver.py clipboard_helper.py hotkey_manager.py stitcher.py vertical_match.py
├── handoff/  handoff_server.py
├── ui/       overlay_selector.py action_toolbar.py scroll_capture.py screen_compose.py capture_worker.py tray_icon.py settings_dialog.py toast.py
└── tests/    test_screen_compose.py test_stitcher.py test_capture_worker.py test_controller_state.py manual-scroll-page.html
```
