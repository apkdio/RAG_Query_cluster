"""按归一化文本去重，并分配稳定 QID。"""

from __future__ import annotations

from ..entities.query import Query, format_qid
from .normalize import normalize


def split_terms(raw: str) -> list[str]:
    """按 | 或换行切分，保留空项过滤前的原始顺序。"""
    return [part.strip() for part in raw.replace("\n", "|").split("|") if part.strip()]


def dedupe_queries(raw: str) -> list[Query]:
    """按归一化文本去重，保留首次出现的原始写法。"""
    queries: list[Query] = []
    seen: set[str] = set()
    for part in split_terms(raw):
        key = normalize(part)
        if not key or key in seen:
            continue
        seen.add(key)
        qid = format_qid(len(queries) + 1)
        query = Query(qid=qid, text=part)
        query.validate()
        queries.append(query)
    return queries
