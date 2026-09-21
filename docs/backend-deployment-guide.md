# Django 后端部署指南

本指南将帮助你将 Django 后端部署到公网服务器。

## 📋 方案对比

| 特性 | PythonAnywhere（免费） | Railway（$5免费额度） | Render（$7/月） |
|------|----------------------|---------------------|----------------|
| 数据库 | SQLite | PostgreSQL ✅ | PostgreSQL ✅ |
| Redis/Celery | ❌ 不支持 | ✅ 支持 | ✅ 支持 |
| 部署难度 | ⭐ 简单 | ⭐⭐ 中等 | ⭐⭐ 中等 |
| 国内访问 | ✅ 可访问 | ✅ 可访问 | ✅ 可访问 |
| 自定义域名 | ❌ 付费 | ✅ 免费 | ✅ 免费 |

---

## 🚀 方案 1：PythonAnywhere（推荐新手）

### 1. 注册账号

1. 访问 [www.pythonanywhere.com](https://www.pythonanywhere.com)
2. 点击 **"Create a Beginner account"**（免费）
3. 验证邮箱完成注册

### 2. 上传代码

登录后，点击页面顶部的 **"Dashboard"**，然后点击 **"Bash"** 打开终端：

```bash
# 克隆仓库
git clone https://github.com/yuanbin2/IPBS.git
cd IPBS/backend
```

### 3. 创建虚拟环境

```bash
# 创建虚拟环境
mkvirtualenv --python=/usr/bin/python3.10 ipbs-env

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

### 4. 配置环境变量

创建 `.env` 文件：

```bash
cat > .env << 'EOF'
DJANGO_SECRET_KEY=your-random-secret-key-at-least-32-chars
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=yourusername.pythonanywhere.com
BLOG_LOCAL_MODE=true
APP_TIMEZONE=Asia/Shanghai
DATABASE_URL=sqlite:///home/yourusername/IPBS/backend/db.sqlite3
AGENT_SECURITY_ENFORCED=false
EOF
```

**重要**：将 `yourusername` 替换为你的 PythonAnywhere 用户名！

### 5. 初始化数据库

```bash
# 运行迁移
python manage.py migrate

# 创建管理员账号
python manage.py createsuperuser

# 收集静态文件
python manage.py collectstatic --noinput
```

### 6. 配置 Web 应用

1. 点击页面顶部的 **"Web"** 标签
2. 点击 **"Add a new web app"**
3. 确认域名（如 `yourusername.pythonanywhere.com`）
4. 选择 **"Manual configuration"**
5. 选择 **Python 3.10**

### 7. 配置 WSGI

在 Web 页面中，点击 **"WSGI configuration file"** 链接，将内容替换为：

```python
import os
import sys

# 添加项目路径
path = '/home/yourusername/IPBS/backend'
if path not in sys.path:
    sys.path.insert(0, path)

# 设置 Django 设置模块
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

# 启动 Django
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

### 8. 配置虚拟环境

在 Web 页面的 **"Virtualenv"** 部分，输入：
```
/home/yourusername/.virtualenvs/ipbs-env
```

### 9. 配置静态文件

在 Web 页面的 **"Static files"** 部分，添加：

| URL | Directory |
|-----|-----------|
| `/static/` | `/home/yourusername/IPBS/backend/staticfiles` |
| `/media/` | `/home/yourusername/IPBS/backend/media` |

### 10. 启动应用

点击页面顶部的绿色 **"Reload"** 按钮。

访问 `https://yourusername.pythonanywhere.com` 查看你的 API！

---

## 🚀 方案 2：Railway（推荐生产环境）

### 1. 注册 Railway

1. 访问 [railway.app](https://railway.app)
2. 使用 GitHub 账号登录
3. 获得 $5 免费额度

### 2. 安装 Railway CLI

```bash
npm install -g @railway/cli
```

### 3. 登录并部署

```bash
# 登录
railway login

# 进入后端目录
cd backend

# 初始化项目
railway init

# 添加 PostgreSQL
railway add postgresql

# 添加 Redis
railway add redis

# 设置环境变量
railway variables set DJANGO_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
railway variables set DJANGO_DEBUG=false
railway variables set BLOG_LOCAL_MODE=false
railway variables set APP_TIMEZONE=Asia/Shanghai
railway variables set AGENT_SECURITY_ENFORCED=true

# 部署
railway up
```

### 4. 绑定域名（可选）

在 Railway 项目设置中：
1. 点击 **"Settings"**
2. 找到 **"Domains"**
3. 点击 **"Generate Domain"** 获取免费子域名
4. 或者添加自定义域名

---

## 🔧 前后端连接配置

部署后端后，需要更新前端的 API 地址：

### 方法 1：环境变量

在 Cloudflare Pages 设置中添加环境变量：
```
VITE_API_BASE_URL=https://yourusername.pythonanywhere.com
```

### 方法 2：修改前端代码

编辑 `frontend/src/api/client.ts`，修改 API 基础 URL：

```typescript
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'https://yourusername.pythonanywhere.com'
```

然后重新部署前端：
```bash
cd frontend
npm run build
npx wrangler pages deploy dist --project-name=ipbs
```

---

## 📊 部署验证

### 检查后端是否运行

```bash
# 访问 API 根路径
curl https://yourusername.pythonanywhere.com/api/

# 或者访问管理后台
https://yourusername.pythonanywhere.com/admin/
```

### 检查前端是否连接

1. 访问 https://ipbs.pages.dev
2. 点击 "开始使用"
3. 尝试登录或注册

---

## 🐛 常见问题

### 1. 500 错误

检查 PythonAnywhere 的 **"Error log"**：
- Web 页面 → 点击 **"Error log"** 链接
- 查看具体错误信息

### 2. 静态文件 404

确保：
1. 运行了 `python manage.py collectstatic`
2. Web 页面中配置了正确的静态文件路径

### 3. 数据库错误

如果使用 SQLite：
```bash
# 重新运行迁移
python manage.py migrate
```

### 4. CORS 错误

确保 `settings.py` 中添加了前端域名：
```python
CORS_ALLOWED_ORIGINS = [
    'https://ipbs.pages.dev',
    'https://41e6d5c4.ipbs.pages.dev',
]
```

---

## 📚 更多资源

- [PythonAnywhere 帮助文档](https://help.pythonanywhere.com)
- [Railway 文档](https://docs.railway.app)
- [Django 部署清单](https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/)

---

## 🎉 部署完成！

部署成功后，你将拥有：

- ✅ **前端**：https://ipbs.pages.dev（Cloudflare Pages）
- ✅ **后端**：https://yourusername.pythonanywhere.com（PythonAnywhere）
- ✅ **管理后台**：https://yourusername.pythonanywhere.com/admin/

现在你可以：
1. 在前端注册账号
2. 登录使用所有功能
3. 通过管理后台管理数据

祝你部署顺利！🚀