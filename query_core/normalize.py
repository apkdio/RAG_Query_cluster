"""文本归一化与词面校验用的字符二元组。"""

from __future__ import annotations

import re
import unicodedata

# 只有疑问壳、没有主题信息的二元组，不参与词面校验
STOP_BIGRAMS = {
    "如何", "是否", "可以", "什么", "怎么", "哪里", "哪些", "多少",
    "能否", "需要", "要求", "一下", "请问", "这个", "那个", "到底",
    "还是", "没有", "不是", "我们", "你们", "他们",
}


def normalize(text: str) -> str:
    """全半角统一，去掉空白、标点和下划线，英文转小写。"""
    value = unicodedata.normalize("NFKC", str(text)).lower()
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)


def content_bigrams(text: str) -> set[str]:
    value = normalize(text)
    grams = {value[i:i + 2] for i in range(len(value) - 1)}
    return grams - STOP_BIGRAMS
