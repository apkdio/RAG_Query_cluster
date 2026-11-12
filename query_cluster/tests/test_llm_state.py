import json

import pytest

from query_cluster.entities import Cluster, Query, ReviewState
from query_cluster.llm.patch import PatchError, apply_patch
from query_cluster.llm.prompts import render_prompt
from query_cluster.llm.review import review_state, save_result


def sample_state() -> ReviewState:
    return ReviewState(
        queries={
            "Q0001": Query("Q0001", "苹果多少钱"),
            "Q0002": Query("Q0002", "香蕉价格"),
            "Q0003": Query("Q0003", "橙子怎么挑"),
            "Q0004": Query("Q0004", "水果怎么保鲜"),
            "Q0005": Query("Q0005", "附近水果店"),
        },
        clusters={
            "C1": Cluster("C1", "价格", ["Q0001", "Q0002"], cohesion=0.8),
            "C2": Cluster("C2", "保存", ["Q0003", "Q0004"], cohesion=0.7),
        },
        pending=["Q0005"],
        meta={"stage": "clustering"},
    )


def test_apply_patch_move_create_and_auto_delete_empty_cluster():
    patch = {"operations": [
        {"op": "move", "qids": ["Q0003"], "to": {"cluster_id": "C1"}},
        {"op": "create", "qids": ["Q0004", "Q0005"]},
    ]}
    state, log = apply_patch(sample_state(), patch)
    state.validate()
    assert state.location("Q0003") == ("cluster", "C1")
    assert state.location("Q0004") == ("cluster", "N1")
    assert state.location("Q0005") == ("cluster", "N1")
    assert "C2" not in state.clusters
    assert log["created"] == [{"cluster_id": "N1", "size": 2}]
    assert state.clusters["N1"].kind == "llm"


def test_apply_patch_delete_is_final_state_not_order_dependent():
    patch = {"operations": [
        {"op": "delete", "cluster_id": "C2"},
        {"op": "move", "qids": ["Q0003", "Q0004"], "to": {"cluster_id": "C1"}},
    ]}
    state, log = apply_patch(sample_state(), patch)
    state.validate()
    assert "C2" not in state.clusters
    assert set(state.clusters["C1"].members) == {"Q0001", "Q0002", "Q0003", "Q0004"}
    assert any(item["cluster_id"] == "C2" and item["auto"] is False for item in log["deleted"])


def test_apply_patch_park_and_discard():
    patch = {"operations": [
        {"op": "park", "qids": ["Q0002"]},
        {"op": "discard", "qids": ["Q0004"], "reason": "噪声"},
    ]}
    state, _ = apply_patch(sample_state(), patch)
    state.validate()
    assert state.location("Q0002") == ("pending", None)
    assert state.location("Q0004") == ("trash", None)
    assert state.trash == ["Q0004"]


def test_apply_patch_rejects_invalid_operations():
    with pytest.raises(PatchError):
        apply_patch(sample_state(), {"operations": [
            {"op": "move", "qids": ["Q9999"], "to": {"cluster_id": "C1"}},
        ]})
    with pytest.raises(PatchError):
        apply_patch(sample_state(), {"operations": [
            {"op": "create", "qids": ["Q0001"]},
        ]})
    with pytest.raises(PatchError):
        apply_patch(sample_state(), {"operations": [
            {"op": "delete", "cluster_id": "C1"},
        ]})
    with pytest.raises(PatchError):
        apply_patch(sample_state(), {"operations": [
            {"op": "move", "qids": ["Q0001"], "to": {"cluster_id": "C9"}},
        ]})


def test_apply_patch_rejects_duplicate_qid_operations():
    with pytest.raises(PatchError):
        apply_patch(sample_state(), {"operations": [
            {"op": "move", "qids": ["Q0001"], "to": {"cluster_id": "C2"}},
            {"op": "park", "qids": ["Q0001"]},
        ]})
    with pytest.raises(PatchError):
        apply_patch(sample_state(), {"operations": [
            {"op": "delete", "cluster_id": "C1"},
            {"op": "delete", "cluster_id": "C1"},
        ]})


def test_prompt_render_has_no_leftover_placeholders():
    text = render_prompt("cluster_patch", STATE_JSON="{}", INSTRUCTIONS="只做明显修正")
    assert "只做明显修正" in text
    assert "{{" not in text
    naming = render_prompt("cluster_naming", CLUSTERS="| C1 | 价格 |")
    assert "| C1 | 价格 |" in naming
    assert "{{" not in naming


def test_review_state_runs_classification_then_naming():
    patch = {"operations": [
        {"op": "move", "qids": ["Q0003"], "to": {"cluster_id": "C1"}},
    ]}
    responses = [
        json.dumps(patch, ensure_ascii=False),
        json.dumps({"renames": [
            {"cluster_id": "C1", "name": "价格咨询"},
            {"cluster_id": "C2", "name": "保存方法"},
        ]}, ensure_ascii=False),
    ]
    calls = []

    def chat(messages):
        calls.append(messages)
        return responses.pop(0)

    result = review_state(sample_state(), "测试", chat)
    assert len(calls) == 2
    assert result.naming_failed is False
    assert result.state.clusters["C1"].name == "价格咨询"
    assert result.state.clusters["C2"].name == "保存方法"
    assert result.log["attempts"][0]["ok"] is True


def test_review_state_retries_invalid_patch():
    patch = {"operations": [
        {"op": "park", "qids": ["Q0004"]},
    ]}
    responses = [
        "not a patch",
        json.dumps(patch, ensure_ascii=False),
        json.dumps({"renames": [
            {"cluster_id": "C1", "name": "价格咨询"},
            {"cluster_id": "C2", "name": "保存方法"},
        ]}, ensure_ascii=False),
    ]

    def chat(messages):
        return responses.pop(0)

    result = review_state(sample_state(), "测试", chat)
    assert result.log["attempts"][0]["ok"] is False
    assert result.log["attempts"][1]["ok"] is True
    assert result.state.location("Q0004") == ("pending", None)


def test_review_state_keeps_classification_when_naming_fails():
    patch = {"operations": [
        {"op": "move", "qids": ["Q0003"], "to": {"cluster_id": "C1"}},
    ]}
    responses = [json.dumps(patch, ensure_ascii=False)] + ["bad naming"] * 3

    def chat(messages):
        return responses.pop(0)

    result = review_state(sample_state(), "测试", chat)
    assert result.naming_failed is True
    assert result.state.meta["naming_failed"] is True
    assert result.state.clusters["C1"].name == "价格"


def test_save_result_writes_state_and_naming(tmp_path):
    patch = {"operations": [
        {"op": "move", "qids": ["Q0003"], "to": {"cluster_id": "C1"}},
    ]}
    responses = [
        json.dumps(patch, ensure_ascii=False),
        json.dumps({"renames": [
            {"cluster_id": "C1", "name": "价格咨询"},
            {"cluster_id": "C2", "name": "保存方法"},
        ]}, ensure_ascii=False),
    ]

    def chat(messages):
        return responses.pop(0)

    result = review_state(sample_state(), "测试", chat)
    save_result(result, tmp_path)
    for name in ("state.llm.json", "patch.json", "patch_log.json", "naming.json"):
        assert (tmp_path / name).exists()
