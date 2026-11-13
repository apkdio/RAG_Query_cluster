"""聚类配置的读取与校验。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..paths import CONFIG_DIR

DEFAULT_CONFIG = CONFIG_DIR / "clustering.json"
EXAMPLE_CONFIG = CONFIG_DIR / "clustering.example.json"
EMBEDDING_BACKENDS = frozenset({"auto", "ollama", "hash"})


class ClusteringConfigError(ValueError):
    """聚类配置缺失或不合法。"""


@dataclass(frozen=True)
class ClusteringConfig:
    threshold: float
    high_similarity_override: float
    lexical_guard: bool
    embedding: str
    ollama_url: str
    embedding_model: str
    hash_dim: int
    embedding_timeout: float
    stop_bigrams: frozenset[str]


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClusteringConfigError(f"{path}: 读取聚类配置失败：{exc}") from exc
    if not isinstance(payload, dict):
        raise ClusteringConfigError(f"{path}: 聚类配置必须是对象")
    return payload


def _number(payload: dict, key: str, path: Path) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ClusteringConfigError(f"{path}: {key} 必须是数字")
    if not 0 <= value <= 1:
        raise ClusteringConfigError(f"{path}: {key} 必须在 0 到 1 之间")
    return float(value)


def load_clustering_config(path: Path | str | None = None) -> ClusteringConfig:
    """读取聚类配置；未显式指定时优先 clustering.json，缺失则用 example。"""
    explicit = path is not None
    config_path = Path(path) if path else DEFAULT_CONFIG
    if not config_path.exists():
        if explicit:
            raise ClusteringConfigError(f"{config_path}: 聚类配置不存在")
        config_path = EXAMPLE_CONFIG
    if not config_path.exists():
        raise ClusteringConfigError(
            f"找不到聚类配置：{DEFAULT_CONFIG} 或 {EXAMPLE_CONFIG}"
        )

    payload = _read_json(EXAMPLE_CONFIG) if EXAMPLE_CONFIG.exists() else {}
    payload.update(_read_json(config_path))

    threshold = _number(payload, "threshold", config_path)
    override = _number(payload, "high_similarity_override", config_path)
    if override < threshold:
        raise ClusteringConfigError(
            f"{config_path}: high_similarity_override 不能小于 threshold"
        )

    lexical_guard = payload.get("lexical_guard")
    if not isinstance(lexical_guard, bool):
        raise ClusteringConfigError(f"{config_path}: lexical_guard 必须是布尔值")

    embedding = payload.get("embedding")
    if embedding not in EMBEDDING_BACKENDS:
        raise ClusteringConfigError(
            f"{config_path}: embedding 必须是 {sorted(EMBEDDING_BACKENDS)} 之一"
        )

    ollama_url = payload.get("ollama_url")
    if not isinstance(ollama_url, str) or not ollama_url.strip():
        raise ClusteringConfigError(f"{config_path}: ollama_url 必须是非空字符串")

    embedding_model = payload.get("embedding_model")
    if not isinstance(embedding_model, str) or not embedding_model.strip():
        raise ClusteringConfigError(f"{config_path}: embedding_model 必须是非空字符串")

    hash_dim = payload.get("hash_dim")
    if not isinstance(hash_dim, int) or isinstance(hash_dim, bool) or hash_dim <= 0:
        raise ClusteringConfigError(f"{config_path}: hash_dim 必须是正整数")

    timeout = payload.get("embedding_timeout")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ClusteringConfigError(f"{config_path}: embedding_timeout 必须是正数")

    raw_stop = payload.get("stop_bigrams")
    if not isinstance(raw_stop, list) or not all(isinstance(item, str) and item for item in raw_stop):
        raise ClusteringConfigError(f"{config_path}: stop_bigrams 必须是非空字符串数组")

    return ClusteringConfig(
        threshold=threshold,
        high_similarity_override=override,
        lexical_guard=lexical_guard,
        embedding=embedding,
        ollama_url=ollama_url.rstrip("/"),
        embedding_model=embedding_model,
        hash_dim=hash_dim,
        embedding_timeout=float(timeout),
        stop_bigrams=frozenset(raw_stop),
    )
