import json

import pytest

from query_cluster.clustering.algorithm import cluster_terms
from query_cluster.clustering.config import ClusteringConfigError, load_clustering_config
from query_cluster.clustering.pipeline import build_state


def test_build_state_uses_configured_threshold_and_guard(tmp_path):
    path = tmp_path / "clustering.json"
    path.write_text(json.dumps({
        "threshold": 0.99,
        "high_similarity_override": 0.99,
        "lexical_guard": False,
    }), encoding="utf-8")

    state = build_state("苹果多少钱|香蕉价格", backend="hash", config_path=str(path))

    assert state.meta["threshold"] == 0.99
    assert state.meta["high_similarity_override"] == 0.99
    assert state.meta["lexical_guard"] is False


def test_lexical_guard_can_be_disabled_by_config():
    vectors = [[1.0, 0.0], [0.9, 0.1]]
    assert len(cluster_terms(["甲甲", "乙乙"], vectors, 0.5, 0.999, True, set())) == 2
    assert len(cluster_terms(["甲甲", "乙乙"], vectors, 0.5, 0.999, False, set())) == 1


def test_config_rejects_override_below_threshold(tmp_path):
    path = tmp_path / "clustering.json"
    path.write_text(json.dumps({
        "threshold": 0.8,
        "high_similarity_override": 0.7,
    }), encoding="utf-8")

    with pytest.raises(ClusteringConfigError):
        load_clustering_config(path)
