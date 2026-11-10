"""QK 双路匹配：稠密向量 + 关键词稀疏，固定阈值，RRF 融合。"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from .embed import cosine, embed_texts
from .normalize import normalize

RRF_K = 60
KEYWORD_THRESHOLD = 0.35
TOP_N = 5


def load_table(path: Path) -> list[tuple[str, str, list[str]]]:
    """读取 QK 表：每行 `名称: 问句1##问句2`，也兼容 JSON 的 {名称: [问句]}。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
        items = []
        for name, questions in payload.items():
            values = questions if isinstance(questions, list) else str(questions).split("##")
            items.append((str(name), str(name), [str(q).strip() for q in values if str(q).strip()]))
        return items

    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, rest = line.partition(":")
        questions = [q.strip() for q in rest.replace("＃", "#").split("##") if q.strip()]
        if name.strip() and questions:
            items.append((name.strip(), name.strip(), questions))
    return items


def tokenize(text: str) -> list[str]:
    value = normalize(text)
    tokens = [value[i:i + 2] for i in range(len(value) - 1)]
    tokens += re.findall(r"[a-z0-9]+", value)
    return tokens or [value] if value else []


def _sparse(tokens: list[str], idf: dict[str, float], max_idf: float) -> dict[str, float]:
    tf = Counter(tokens)
    vec = {t: (1 + math.log(c)) * idf.get(t, max_idf) for t, c in tf.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {t: v / norm for t, v in vec.items()}


def _sparse_cos(a: dict[str, float], b: dict[str, float]) -> float:
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def _rank(scores: list[float], gated: list[bool] | None = None) -> dict[int, int]:
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    ranks: dict[int, int] = {}
    pos = 0
    for idx in order:
        if gated is not None and not gated[idx]:
            continue
        ranks[idx] = pos
        pos += 1
    return ranks


def match(query: str, table_path: Path, backend: str = "auto", top_n: int = TOP_N) -> dict:
    items = load_table(table_path)
    if not items:
        raise SystemExit(f"{table_path} 里没有可用的 QK 条目")

    questions: list[str] = []
    slugs: list[str] = []
    names: dict[str, str] = {}
    for slug, name, qs in items:
        names[slug] = name
        for q in qs:
            questions.append(q)
            slugs.append(slug)

    vectors, actual_backend = embed_texts(questions + [query], backend)
    qvec = vectors[-1]
    dense_scores = [cosine(qvec, v) for v in vectors[:-1]]

    docs = [tokenize(q) for q in questions]
    df: Counter[str] = Counter()
    for tokens in docs:
        df.update(set(tokens))
    total = len(docs)
    idf = {t: math.log((total + 1) / (c + 0.5)) for t, c in df.items()}
    max_idf = max(idf.values(), default=1.0)
    qsparse = _sparse(tokenize(query), idf, max_idf)
    keyword_scores = [_sparse_cos(qsparse, _sparse(tokens, idf, max_idf)) for tokens in docs]
    gated = [score >= KEYWORD_THRESHOLD for score in keyword_scores]

    dense_rank = _rank(dense_scores)
    keyword_rank = _rank(keyword_scores, gated)
    fused: dict[str, float] = {}
    for idx, slug in enumerate(slugs):
        score = 0.0
        if idx in dense_rank:
            score += 1.0 / (RRF_K + dense_rank[idx])
        if idx in keyword_rank:
            score += 1.0 / (RRF_K + keyword_rank[idx])
        if score > fused.get(slug, 0.0):
            fused[slug] = score

    ranked = sorted(fused.items(), key=lambda kv: -kv[1])[:top_n]
    return {
        "query": query,
        "embedding": actual_backend,
        "matches": [
            {
                "name": names[slug],
                "slug": slug,
                "score": round(score, 6),
            }
            for slug, score in ranked
        ],
    }
