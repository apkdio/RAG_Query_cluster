"""文本归一化与词面校验用的字符二元组。"""

from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    """全半角统一，去掉空白、标点和下划线，英文转小写。"""
    value = unicodedata.normalize("NFKC", str(text)).lower()
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)


def content_bigrams(text: str, stop_bigrams: set[str] | frozenset[str]) -> set[str]:
    value = normalize(text)
    grams = {value[i:i + 2] for i in range(len(value) - 1)}
    return grams - stop_bigrams
