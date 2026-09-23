# PythonAnywhere 部署配置
# 将此文件内容添加到 .env 文件中

# 基本设置
DJANGO_SECRET_KEY=your-super-secret-key-change-this-to-random-32-chars
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=yourusername.pythonanywhere.com
BLOG_LOCAL_MODE=true
APP_TIMEZONE=Asia/Shanghai

# 数据库（使用 SQLite，PythonAnywhere 免费版不支持 PostgreSQL）
DATABASE_URL=sqlite:///home/yourusername/IPBS/backend/db.sqlite3

# 关闭需要 Redis/Celery 的功能
AGENT_SECURITY_ENFORCED=false

# OpenAI API（如果需要 AI 功能）
OPENAI_API_KEY=your-openai-api-key
OPENAI_BASE_URL=https://api.openai.com/v1/
OPENAI_MODEL=gpt-4o-mini