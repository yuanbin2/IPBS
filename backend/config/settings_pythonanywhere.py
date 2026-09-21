# PythonAnywhere 特定设置
# 在 settings.py 中导入此文件以覆盖默认设置

import os

# 使用 SQLite 数据库
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# 关闭需要 Redis 的功能
CELERY_BROKER_URL = None
CELERY_RESULT_BACKEND = None
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# 关闭 RAG 向量搜索（需要 PostgreSQL + pgvector）
RAG_VECTOR_BACKEND = 'simple'

# 允许 PythonAnywhere 域名
ALLOWED_HOSTS = [
    'yourusername.pythonanywhere.com',
    'www.yourusername.pythonanywhere.com',
    'localhost',
    '127.0.0.1',
]

# 静态文件配置
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# 媒体文件配置
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# CORS 配置（允许前端访问）
CORS_ALLOWED_ORIGINS = [
    'https://ipbs.pages.dev',
    'https://41e6d5c4.ipbs.pages.dev',
    'http://localhost:5173',
]

CORS_ALLOW_CREDENTIALS = True

# 日志配置
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'WARNING',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'django.log'),
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'WARNING',
            'propagate': True,
        },
    },
}