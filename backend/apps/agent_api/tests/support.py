"""测试共享常量。"""

import tempfile
from pathlib import Path

NO_MODEL_ENV = {
    "OPENAI_API_KEY": "",
    "OPENAI_EMBEDDING_API_KEY": "",
    "BAILIAN_API_KEY": "",
    "DASHSCOPE_API_KEY": "",
    "LANGSMITH_TRACING": "false",
    "LANGCHAIN_TRACING_V2": "false",
}

TEST_MEDIA_ROOT = Path(tempfile.gettempdir()) / "knowledge_agent_test_media"
