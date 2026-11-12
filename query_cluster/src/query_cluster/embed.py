"""兼容入口：向量实现已移到 query_cluster.clustering。"""

from .clustering.embed import HASH_DIM, MODEL, OLLAMA_URL, cosine, embed_texts

__all__ = ["HASH_DIM", "MODEL", "OLLAMA_URL", "cosine", "embed_texts"]
