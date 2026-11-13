import json
import threading
from urllib.request import Request, urlopen

import pytest

from query_cluster.entities import Cluster, Query, ReviewState
from query_cluster.review.actions import ActionError, apply_action, recompute_human_tags
from query_cluster.review.export import export_dict
from query_cluster.review.server import make_server
from query_cluster.clustering.pipeline import write_state


def sample_state() -> ReviewState:
    return ReviewState(
        queries={
            "Q0001": Query("Q0001", "苹果多少钱"),
            "Q0002": Query("Q0002", "香蕉价格"),
            "Q0003": Query("Q0003", "橙子怎么挑"),
            "Q0004": Query("Q0004", "附近水果店"),
        },
        clusters={
            "C1": Cluster("C1", "价格", ["Q0001", "Q0002"], cohesion=0.8),
            "C2": Cluster("C2", "挑选", ["Q0003"], cohesion=0.7),
        },
        pending=[],
        trash=["Q0004"],
        events=[{"type": "seed"}],
        meta={"stage": "clustering"},
    )


def test_move_last_member_removes_source_cluster():
    state = apply_action(sample_state(), {"op": "move", "qid": "Q0003", "to": "C1"})
    assert "C2" not in state.clusters
    assert state.location("Q0003") == ("cluster", "C1")
    assert state.clusters["C1"].cohesion is None
    assert state.meta["stage"] == "human"


def test_update_slug_and_keywords():
    state = apply_action(sample_state(), {
        "op": "update", "cluster_id": "C1", "slug": "price", "keywords": "价格,费用",
    })
    assert state.clusters["C1"].slug == "price"
    assert state.clusters["C1"].keywords == "价格,费用"


def test_move_to_pending_and_trash():
    state = apply_action(sample_state(), {"op": "move", "qid": "Q0002", "to": "pending"})
    assert state.location("Q0002") == ("pending", None)
    state = apply_action(state, {"op": "move", "qid": "Q0001", "to": "trash"})
    assert state.location("Q0001") == ("trash", None)


def test_create_rename_and_delete_empty_cluster():
    state = apply_action(sample_state(), {
        "op": "create", "qids": ["Q0003"], "name": "挑选技巧",
    })
    assert state.clusters["N1"].name == "挑选技巧"
    assert state.clusters["N1"].kind == "manual"
    state = apply_action(state, {"op": "rename", "cluster_id": "C1", "name": "价格咨询"})
    assert state.clusters["C1"].name == "价格咨询"
    with pytest.raises(ActionError):
        apply_action(state, {"op": "delete", "cluster_id": "C1"})


def test_human_tag_marks_and_reverts_to_baseline():
    baseline = sample_state()
    moved = apply_action(baseline, {"op": "move", "qid": "Q0001", "to": "C2"})
    recompute_human_tags(moved, baseline)
    assert moved.clusters["C1"].human_touched is True
    assert moved.clusters["C2"].human_touched is True

    restored = apply_action(moved, {"op": "move", "qid": "Q0001", "to": "C1"})
    recompute_human_tags(restored, baseline)
    assert restored.clusters["C1"].human_touched is False
    assert restored.clusters["C2"].human_touched is False


def test_export_drops_events_and_marks_human():
    payload = export_dict(sample_state())
    assert payload["meta"]["stage"] == "human"
    assert payload["events"] == []
    assert "events" not in payload["queries"]


def test_http_history_undo_redo(tmp_path):
    state_path = tmp_path / "state.json"
    write_state(sample_state(), tmp_path)
    server = make_server(sample_state(), state_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else b""
        request = Request(base + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        post("/api/action", {"op": "move", "qid": "Q0003", "to": "C1"})
        with urlopen(base + "/api/history") as response:
            history = json.loads(response.read().decode("utf-8"))
        assert history["undo"] is True and history["redo"] is False

        undone = post("/api/undo")
        assert "C2" in {cluster["cluster_id"] for cluster in undone["clusters"]}
        redone = post("/api/redo")
        assert "C2" not in {cluster["cluster_id"] for cluster in redone["clusters"]}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_http_review_api(tmp_path):
    state_path = tmp_path / "state.json"
    write_state(sample_state(), tmp_path)
    server = make_server(sample_state(), state_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/api/state") as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["version"] == 1
        assert len(payload["clusters"]) == 2

        request = Request(
            base + "/api/action",
            data=json.dumps({"op": "move", "qid": "Q0003", "to": "C1"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert "C2" not in {cluster["cluster_id"] for cluster in payload["clusters"]}

        with urlopen(base + "/api/export") as response:
            exported = json.loads(response.read().decode("utf-8"))
        assert exported["meta"]["stage"] == "human"
        assert exported["events"] == []
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        assert persisted["meta"]["stage"] == "human"
        assert "C2" not in {cluster["cluster_id"] for cluster in persisted["clusters"]}

        load = Request(
            base + "/api/load",
            data=json.dumps(sample_state().to_dict(), ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(load) as response:
            loaded = json.loads(response.read().decode("utf-8"))
        assert len(loaded["clusters"]) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
