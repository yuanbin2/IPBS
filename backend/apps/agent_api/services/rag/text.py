"""RAG 纯文本/向量工具：分词、归一化、余弦相似度与本地降级向量。"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable

LOCAL_EMBEDDING_DIMENSIONS = 384


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def keyword_tokens(text: str) -> list[str]:
    normalized = text.lower()
    english_tokens = re.findall(r"[a-z0-9_]{2,}", normalized)
    chinese_sequences = re.findall(r"[\u4e00-\u9fff]+", normalized)

    tokens: list[str] = [*english_tokens]
    for sequence in chinese_sequences:
        if len(sequence) <= 12:
            tokens.append(sequence)
        tokens.extend(sequence[index : index + 2] for index in range(max(0, len(sequence) - 1)))
        tokens.extend(sequence[index : index + 3] for index in range(max(0, len(sequence) - 2)))

    seen: set[str] = set()
    unique_tokens: list[str] = []
    for token in tokens:
        if token and token not in seen:
            seen.add(token)
            unique_tokens.append(token)
    return unique_tokens


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = list(left)
    right_values = list(right)
    if not left_values or not right_values or len(left_values) != len(right_values):
        return 0.0
    numerator = sum(a * b for a, b in zip(left_values, right_values, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left_values))
    right_norm = math.sqrt(sum(b * b for b in right_values))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def local_embedding(text: str, dimensions: int = LOCAL_EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    tokens = keyword_tokens(text)
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = -1.0 if digest[4] % 2 else 1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]
