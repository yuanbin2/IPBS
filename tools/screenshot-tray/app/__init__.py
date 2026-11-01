"""托盘截图工具（screenshot-tray）主包。

分层结构（见 docs/system_design.md §1.3）：
- app/      编排层与常量、错误体系
- core/     配置、凭据（DPAPI）、日志、单实例
- services/ 认证、上传、存本地、剪贴板、热键
- ui/       遮罩选区、悬浮条、托盘、设置、气泡提示
- handoff/  P1 本地一次性 HTTP 端点（OCR 交接）
"""
