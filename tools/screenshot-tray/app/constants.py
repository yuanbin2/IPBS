"""全局常量：路径、后端端点、默认配置、错误与 UI 文案。

约定来源：docs/system_design.md §7「共享知识」；后端接口出处见 §1。
中文 UI 文案统一放本文件。
"""
from __future__ import annotations

import os
from pathlib import Path

# ---- 应用路径 ----
APP_NAME = "BlogScreenshotTool"
APP_DIR = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / APP_NAME
CONFIG_PATH = APP_DIR / "config.json"
CREDENTIAL_PATH = APP_DIR / "credentials.bin"
LOG_DIR = APP_DIR / "logs"
LOG_FILE = LOG_DIR / "tray.log"

# ---- 后端端点（均已核对真实代码） ----
# 登录：backend/apps/agent_api/views/auth.py L31-72（AuthLoginView）
# 公开媒体上传：backend/apps/agent_api/views/blog_articles.py L194-286（BlogImageUploadView，OPERATOR）
# 私有笔记图片：backend/apps/agent_api/views/blog_note_images.py L89-145（5MiB、60 张/时）
DEFAULT_BACKEND_BASE = "http://127.0.0.1:8001"
DEFAULT_BLOG_FRONTEND_BASE = "http://127.0.0.1:5174"
LOGIN_PATH = "/api/agent/auth/login/"
REFRESH_PATH = "/api/agent/auth/refresh/"
PUBLIC_IMAGE_PATH = "/api/agent/blog/images/"
NOTE_IMAGE_PATH = "/api/agent/blog/notes/images/"

# 后端错误码（backend/apps/agent_api/exceptions.py，小写字符串）
CODE_NOT_AUTHENTICATED = "not_authenticated"
CODE_FORBIDDEN = "forbidden"
CODE_VALIDATION_ERROR = "validation_error"
CODE_RATE_LIMITED = "rate_limited"
CODE_UPSTREAM_UNAVAILABLE = "upstream_unavailable"

# ---- HTTP ----
HTTP_CONNECT_TIMEOUT = 3
HTTP_READ_TIMEOUT = 15
HTTP_TIMEOUT = (HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT)

# ---- 上限 ----
MAX_UPLOAD_BYTES = 5 * 1024 * 1024          # 公开媒体 5MB
HANDOFF_MAX_BYTES = 20 * 1024 * 1024        # P1 端点持有上限（对齐前端 MAX_TOTAL_BYTES）
HANDOFF_TOKEN_TTL_SECONDS = 300             # token 5 分钟过期（TTL 内可重复取，供前端重试）

# ---- 时间与命名 ----
TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"

# ---- 默认配置（%APPDATA%/BlogScreenshotTool/config.json 缺字段用默认值） ----
DEFAULT_CONFIG: dict = {
    "backend_base": DEFAULT_BACKEND_BASE,
    "blog_frontend_base": DEFAULT_BLOG_FRONTEND_BASE,
    "hotkey": "ctrl+alt+a",
    "save_dir": str(Path.home() / "Pictures" / "BlogScreenshots"),
    "save_layout": "{yyyy}/{MM}/{yyyyMMdd-HHmmss}.png",
    "autostart": False,
}

# ---- 用户可读错误文案（docs/system_design.md §7 错误码映射） ----
MSG_NOT_LOGGED_IN = "未登录或登录已过期，请在托盘设置中登录"
MSG_FORBIDDEN = "无上传权限：公开博客媒体上传需要 OPERATOR 角色账号"
MSG_IMAGE_TOO_LARGE = "图片超过 5MB 或格式不支持"
MSG_RATE_LIMITED = "上传过于频繁，请稍后再试"
MSG_NO_BACKEND = "无法连接后端，请确认本地服务已启动"
MSG_BACKEND_DOWN = "后端暂不可用，请稍后再试"
MSG_UPLOAD_FAILED = "上传失败"
MSG_INVALID_CREDENTIALS = "账号或密码错误"

# ---- UI 文案 ----
UI_TOOL_TIP = "博客截图工具"
UI_TRAY_CAPTURE = "截图"
UI_TRAY_SCROLL_CAPTURE = "长截图"
UI_TRAY_SETTINGS = "打开设置…"
UI_TRAY_AUTOSTART = "开机自动启动"
UI_TRAY_QUIT = "退出"
UI_BTN_PUBLISH = "发博客"
UI_BTN_SAVE = "存本地"
UI_BTN_OCR = "OCR 识别"
UI_BTN_SCROLL = "长截图"
UI_BTN_CANCEL = "取消"
UI_TOAST_STARTED = "截图工具已启动，热键：{hotkey}"
UI_TOAST_HOTKEY_FAILED = "热键 {hotkey} 注册失败，可能已被其他程序占用"
UI_TOAST_BUSY = "已有待处理的截图，请先完成或取消"
UI_TOAST_COPY_OK = "已复制 Markdown 链接"
UI_TOAST_SAVED = "已保存：{path}"
UI_TOAST_FALLBACK = "上传失败（{reason}），已存本地：{path}"
UI_TOAST_SAVE_FAILED = "保存失败：{reason}"
UI_TOAST_UPLOADING = "正在上传…"
UI_TOAST_OCR_OPENED = "已在浏览器打开博客页进行 OCR 识别（截图 5 分钟内有效）"
UI_TOAST_SETTINGS_SAVED = "设置已保存"
UI_TOAST_PNG_ENCODE_FAILED = "图片编码失败"

# ---- 未登录引导（Bug2：auth 失败除气泡外直接弹设置） ----
UI_TOAST_AUTH_GUIDE = "尚未登录博客，已为你打开设置窗口，登录后重试即可"
UI_TOAST_FALLBACK_AUTH = "尚未登录博客，已为你打开设置窗口；截图已先存本地：{path}，登录后重试即可"
UI_TOAST_AUTH_TIMEOUT_MS = 8000          # 引导弹窗的气泡延长展示，避免一闪而过

# ---- 长截图（滚动截图）UI 文案 ----
UI_TOAST_SCROLL_DONE = "长截图完成，请选择去向"
UI_SCROLL_HINT = "请在选区内滚动页面，内容变化时会自动采集"
UI_SCROLL_BOTTOM_HINT = "疑似已到页面底部，点「完成」生成图片"
UI_SCROLL_LIMIT_HINT = "{message}，已自动暂停，点「完成」生成图片"
UI_SCROLL_FAIL_HINT = "拼接暂停：{message}。请滚回与上一帧重叠的位置再点「重试」，或点「完成」保留已拼部分"
UI_SCROLL_COLLECTED = "已采集 {count} 帧"
UI_SCROLL_BTN_FINISH = "完成"
UI_SCROLL_BTN_CANCEL = "取消"
UI_SCROLL_BTN_RETRY = "重试"

# ---- 拼接错误文案（services/stitcher.py 抛出，长截图控制窗展示） ----
MSG_STITCH_NO_OVERLAP = "未能识别重叠区域（滚动过快或固定/动画元素干扰）"
MSG_STITCH_LIMIT_FRAMES = "已达最大帧数（30 帧）"
MSG_STITCH_LIMIT_HEIGHT = "拼接总高度已达上限（约 30000px）"
MSG_STITCH_LIMIT_PIXELS = "拼接总像素已达上限"

# ---- 开机自启（HKCU Run 键，docs/system_design.md T05） ----
AUTOSTART_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = APP_NAME
