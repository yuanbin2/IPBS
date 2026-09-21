#!/bin/bash
# PythonAnywhere 部署脚本
# 在 PythonAnywhere 的 Bash console 中运行此脚本

set -e

echo "🚀 开始部署 Django 到 PythonAnywhere..."

# 1. 克隆仓库（如果还没有）
if [ ! -d "$HOME/IPBS" ]; then
    echo "📥 克隆仓库..."
    cd $HOME
    git clone https://github.com/yuanbin2/IPBS.git
fi

# 2. 进入后端目录
cd $HOME/IPBS/backend

# 3. 创建虚拟环境
echo "🐍 创建虚拟环境..."
mkvirtualenv --python=/usr/bin/python3.10 ipbs-env

# 4. 安装依赖
echo "📦 安装依赖..."
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

# 5. 创建 .env 文件
echo "⚙️ 创建配置文件..."
cat > .env << 'EOF'
DJANGO_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=yourusername.pythonanywhere.com
BLOG_LOCAL_MODE=true
APP_TIMEZONE=Asia/Shanghai
DATABASE_URL=sqlite:///home/yourusername/IPBS/backend/db.sqlite3
AGENT_SECURITY_ENFORCED=false
EOF

# 6. 运行数据库迁移
echo "🗄️ 运行数据库迁移..."
python manage.py migrate

# 7. 创建超级用户
echo "👤 创建管理员账号..."
echo "请按照提示创建管理员账号："
python manage.py createsuperuser

# 8. 收集静态文件
echo "📁 收集静态文件..."
python manage.py collectstatic --noinput

echo "✅ 部署准备完成！"
echo ""
echo "📋 接下来请在 PythonAnywhere 的 Web 页面中："
echo "1. 点击 'Web' 标签"
echo "2. 点击 'Add a new web app'"
echo "3. 选择 'Manual configuration'"
echo "4. 选择 Python 3.10"
echo "5. 设置源代码路径：/home/yourusername/IPBS/backend"
echo "6. 设置虚拟环境：/home/yourusername/.virtualenvs/ipbs-env"
echo "7. 配置 WSGI 文件（见下方说明）"
echo ""
echo "📄 WSGI 文件内容："
cat << 'WSGI'
import os
import sys

path = '/home/yourusername/IPBS/backend'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
WSGI