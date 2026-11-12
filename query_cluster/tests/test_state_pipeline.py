import json

import pytest

from query_cluster.clustering.pipeline import build_state, write_state
from query_cluster.preprocess.dedupe import dedupe_queries, split_terms


def test_split_terms_handles_pipe_and_newlines():
    assert split_terms("苹果|香蕉\n橙子||") == ["苹果", "香蕉", "橙子"]


def test_dedupe_uses_normalized_text_and_assigns_qids():
    queries = dedupe_queries("苹果|香蕉| 苹果 |Ａ|a")
    assert [query.qid for query in queries] == ["Q0001", "Q0002", "Q0003"]
    assert [query.text for query in queries] == ["苹果", "香蕉", "Ａ"]


def test_build_state_has_all_queries_in_one_place():
    state = build_state("苹果多少钱|香蕉价格|苹果怎么保存", backend="hash",
                        now="2026-01-01T00:00:00")
    assert len(state.queries) == 3
    assert state.meta["stage"] == "clustering"
    assert state.meta["count"] == 3
    assert state.meta["created_at"] == "2026-01-01T00:00:00"
    state.validate()

    placed = [qid for cluster in state.clusters.values() for qid in cluster.members]
    placed += state.pending + state.trash
    assert sorted(placed) == ["Q0001", "Q0002", "Q0003"]


def test_build_state_rejects_empty_input():
    with pytest.raises(ValueError):
        build_state(" | \n ", backend="hash")


def test_write_state_roundtrip(tmp_path):
    state = build_state("苹果多少钱|香蕉价格", backend="hash")
    path = write_state(state, tmp_path)
    assert path.name == "state.json"

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["meta"]["stage"] == "clustering"
    assert "count" not in payload["queries"]["Q0001"]
    assert "label" not in payload["clusters"][0]
