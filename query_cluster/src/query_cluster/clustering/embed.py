"""文本向量：优先 Ollama 的 bge-m3，失败时退回确定性的哈希向量。

工程上只依赖标准库；有 Ollama 时语义效果更好，没有也能跑通完整流程。
"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "bge-m3"
HASH_DIM = 512


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(size))
    na = math.sqrt(sum(x * x for x in a[:size]))
    nb = math.sqrt(sum(x * x for x in b[:size]))
    return dot / (na * nb) if na and nb else 0.0


def _hash_vec(text: str, dim: int = HASH_DIM) -> list[float]:
    """字符 uni/bi-gram 哈希到固定维度，输出归一化向量。"""
    from ..preprocess.normalize import normalize

    value = normalize(text)
    if not value:
        return [0.0] * dim
    feats: list[str] = list(value)
    feats += [value[i:i + 2] for i in range(len(value) - 1)]
    vec = [0.0] * dim
    for feat in feats:
        digest = hashlib.md5(feat.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _ollama_embed(texts: list[str]) -> list[list[float]]:
    body = json.dumps({"model": MODEL, "input": texts}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embed",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    vectors = payload.get("embeddings")
    if not vectors or len(vectors) != len(texts):
        raise ValueError("Ollama 返回的向量数量不匹配")
    return vectors


def embed_texts(texts: list[str], backend: str = "auto") -> tuple[list[list[float]], str]:
    """返回 (向量列表, 实际后端)。backend: auto / ollama / hash。"""
    if backend == "hash":
        return [_hash_vec(t) for t in texts], "hash"
    try:
        vectors = _ollama_embed(texts)
        return vectors, "ollama"
    except Exception:
        if backend == "ollama":
            raise
        return [_hash_vec(t) for t in texts], "hash"
