import json
from pathlib import Path

import pytest

from query_cluster.llm_review import LLMReviewError, review, save_outputs
from query_cluster.patch import PatchError, apply_patch


def sample_clusters():
    return [
        {"cluster_id": "C1", "name": "价格", "kind": "auto", "size": 2, "cohesion": 0.8, "terms": [
            {"query_id": "C1:Q1", "text": "苹果多少钱", "count": 1},
            {"query_id": "C1:Q2", "text": "香蕉价格", "count": 1},
        ]},
        {"cluster_id": "C2", "name": "保存", "kind": "auto", "size": 2, "cohesion": 0.7, "terms": [
            {"query_id": "C2:Q1", "text": "苹果怎么保存", "count": 1},
            {"query_id": "C2:Q2", "text": "水果怎么保鲜", "count": 1},
        ]},
    ]


def test_apply_patch_move_rename_create():
    patch = {"operations": [
        {"op": "rename", "cluster_id": "C1", "name": "价格咨询"},
        {"op": "move", "query_ids": ["C2:Q2"], "to": "C1"},
        {"op": "create", "name": "其他", "query_ids": ["C2:Q1"]},
    ]}
    clusters, removed, log = apply_patch(sample_clusters(), patch)
    assert not removed
    by_name = {c["name"]: [t["text"] for t in c["terms"]] for c in clusters}
    assert by_name["价格咨询"] == ["苹果多少钱", "香蕉价格", "水果怎么保鲜"]
    assert by_name["其他"] == ["苹果怎么保存"]
    assert len(log["moves"]) == 2


def test_apply_patch_merge_and_remove():
    patch = {"operations": [
        {"op": "merge", "clusters": ["C2"], "into": "C1"},
        {"op": "remove", "query_ids": ["C1:Q2"], "reason": "噪声"},
    ]}
    clusters, removed, _ = apply_patch(sample_clusters(), patch)
    assert [r["text"] for r in removed] == ["香蕉价格"]
    assert len(clusters) == 1
    assert clusters[0]["size"] == 3


def test_apply_patch_rejects_unknown_query():
    with pytest.raises(PatchError):
        apply_patch(sample_clusters(), {"operations": [{"op": "move", "query_ids": ["C9:Q1"], "to": "C1"}]})


def test_apply_patch_rejects_duplicate_query_ops():
    patch = {"operations": [
        {"op": "move", "query_ids": ["C2:Q1"], "to": "C1"},
        {"op": "remove", "query_ids": ["C2:Q1"]},
    ]}
    with pytest.raises(PatchError):
        apply_patch(sample_clusters(), patch)


def test_llm_review_retries_after_invalid_output():
    calls = []
    responses = [
        "not a patch",
        json.dumps({"operations": [{"op": "rename", "cluster_id": "C1", "name": "价格咨询"}]}),
    ]

    def chat(messages):
        calls.append(messages)
        return responses.pop(0)

    clusters, removed, log, patch = review(sample_clusters(), "测试", chat, max_attempts=3)
    assert len(calls) == 2
    assert log["attempts"][0]["ok"] is False
    assert log["attempts"][1]["ok"] is True
    assert clusters[0]["name"] == "价格咨询"


def test_llm_review_fails_after_max_attempts():
    def chat(messages):
        return "still not json"

    with pytest.raises(LLMReviewError):
        review(sample_clusters(), "测试", chat, max_attempts=3)


def test_save_outputs(tmp_path):
    clusters = sample_clusters()
    result, removed, log = apply_patch(clusters, {"operations": [
        {"op": "rename", "cluster_id": "C1", "name": "价格咨询"},
    ]})
    save_outputs({"meta": {"count": 4}, "clusters": clusters}, result, removed, log, tmp_path)
    for name in ("clusters.json", "patch.json", "patch_log.json", "diff.html", "review.html"):
        assert (tmp_path / name).exists()
    html = (tmp_path / "diff.html").read_text(encoding="utf-8")
    assert "价格咨询" in html
