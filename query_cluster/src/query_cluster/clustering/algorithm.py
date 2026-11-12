"""固定阈值的平均链接聚类。"""

from __future__ import annotations

from .embed import cosine
from ..preprocess.normalize import content_bigrams

THRESHOLD = 0.62
OVERRIDE_SIM = 0.75


def similarity_matrix(vectors: list[list[float]]) -> list[list[float]]:
    n = len(vectors)
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        sim[i][i] = 1.0
        for j in range(i + 1, n):
            value = cosine(vectors[i], vectors[j])
            sim[i][j] = sim[j][i] = value
    return sim


def _guard_ok(members_a: list[int], members_b: list[int], texts: list[str],
              grams: list[set[str]], avg: float) -> bool:
    if avg >= OVERRIDE_SIM:
        return True
    shared = any(grams[i] & grams[j] for i in members_a for j in members_b)
    return shared


def cluster_terms(texts: list[str], vectors: list[list[float]],
                  threshold: float = THRESHOLD) -> list[list[int]]:
    """平均链接：每次合并平均相似度最高且过词面校验的两个簇。"""
    n = len(texts)
    if n == 0:
        return []
    sim = similarity_matrix(vectors)
    grams = [content_bigrams(t) for t in texts]
    members = [[i] for i in range(n)]

    while len(members) > 1:
        best = None
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                left, right = members[a], members[b]
                avg = sum(sim[i][j] for i in left for j in right) / (len(left) * len(right))
                if avg < threshold:
                    continue
                if not _guard_ok(left, right, texts, grams, avg):
                    continue
                if best is None or avg > best[0]:
                    best = (avg, a, b)
        if best is None:
            break
        _, a, b = best
        members[a] = sorted(members[a] + members[b])
        del members[b]

    return sorted(members, key=lambda m: (-len(m), min(m)))


def cohesion(members: list[int], sim: list[list[float]]) -> float:
    if len(members) < 2:
        return 1.0
    values = [sim[i][j] for x, i in enumerate(members) for j in members[x + 1:]]
    return round(sum(values) / len(values), 4) if values else 1.0
