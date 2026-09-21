#!/bin/bash
# Railway 部署脚本
# 在本地运行此脚本准备部署

set -e

echo "🚀 准备部署 Django 到 Railway..."

# 1. 安装 Railway CLI
echo "📥 安装 Railway CLI..."
npm install -g @railway/cli

# 2. 登录 Railway
echo "🔐 登录 Railway..."
railway login

# 3. 创建项目
echo "📦 创建 Railway 项目..."
railway init

# 4. 添加 PostgreSQL
echo "🗄️ 添加 PostgreSQL 数据库..."
railway add postgresql

# 5. 添加 Redis
echo "📮 添加 Redis..."
railway add redis

# 6. 设置环境变量
echo "⚙️ 设置环境变量..."
railway variables set DJANGO_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
railway variables set DJANGO_DEBUG=false
railway variables set BLOG_LOCAL_MODE=false
railway variables set APP_TIMEZONE=Asia/Shanghai
railway variables set AGENT_SECURITY_ENFORCED=true

# 7. 部署
echo "🚀 部署到 Railway..."
railway up

echo "✅ 部署完成！"
echo ""
echo "📋 接下来："
echo "1. 访问 https://railway.app 查看部署状态"
echo "2. 在 Settings 中绑定自定义域名（可选）"
echo "3. 在 Variables 中添加其他环境变量（如 OPENAI_API_KEY）"