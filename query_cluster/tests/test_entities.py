import pytest

from query_cluster.entities import (
    Cluster,
    Query,
    ReviewState,
    StateError,
    format_qid,
    new_event,
    next_qid,
)


def make_state() -> ReviewState:
    return ReviewState(
        queries={
            "Q0001": Query("Q0001", "苹果多少钱"),
            "Q0002": Query("Q0002", "香蕉价格"),
            "Q0003": Query("Q0003", "橙子怎么挑"),
            "Q0004": Query("Q0004", "附近水果店"),
        },
        clusters={
            "C1": Cluster("C1", "价格咨询", ["Q0001", "Q0002"], cohesion=0.8),
        },
        pending=["Q0003"],
        trash=["Q0004"],
        events=[new_event("created", source="unit")],
        meta={"stage": "clustering"},
    )


def test_query_roundtrip_and_validation():
    query = Query("Q0001", "苹果多少钱")
    assert query.to_dict() == {"text": "苹果多少钱"}
    assert Query.from_dict("Q0001", query.to_dict()) == query

    with pytest.raises(ValueError):
        Query("Q1", "苹果").validate()
    with pytest.raises(ValueError):
        Query("Q0001", "  ").validate()


def test_qid_allocation_is_monotonic():
    assert format_qid(1) == "Q0001"
    assert next_qid([]) == "Q0001"
    assert next_qid(["Q0001", "Q0009"]) == "Q0010"
    with pytest.raises(ValueError):
        next_qid(["C1:Q1"])


def test_event_shape():
    event = new_event("created", source="unit")
    assert event["type"] == "created"
    assert event["source"] == "unit"
    assert "at" in event
    with pytest.raises(ValueError):
        new_event("created", type="other")


def test_state_roundtrip():
    state = make_state()
    payload = state.to_dict()
    assert payload["version"] == 1
    assert payload["queries"]["Q0001"] == {"text": "苹果多少钱"}
    assert "count" not in payload["queries"]["Q0001"]
    assert payload["clusters"][0]["members"] == ["Q0001", "Q0002"]
    assert "label" not in payload["clusters"][0]
    assert payload["pending"] == ["Q0003"]
    assert payload["trash"] == ["Q0004"]

    restored = ReviewState.from_dict(payload)
    assert restored == state
    assert restored.location("Q0001") == ("cluster", "C1")
    assert restored.location("Q0003") == ("pending", None)
    assert restored.location("Q0004") == ("trash", None)


def test_state_rejects_duplicate_qid_placement():
    state = make_state()
    state.clusters["C2"] = Cluster("C2", "另一个簇", ["Q0001"])
    with pytest.raises(StateError):
        state.validate()


def test_state_rejects_empty_cluster():
    state = make_state()
    state.clusters["C2"] = Cluster("C2", "空簇", [])
    with pytest.raises(StateError):
        state.validate()


def test_state_rejects_unknown_qid():
    state = make_state()
    state.clusters["C1"].members.append("Q9999")
    with pytest.raises(StateError):
        state.validate()


def test_state_rejects_missing_position():
    state = make_state()
    state.pending.remove("Q0003")
    with pytest.raises(StateError):
        state.validate()


def test_state_rejects_pool_overlap():
    state = make_state()
    state.trash.append("Q0003")
    with pytest.raises(StateError):
        state.validate()


def test_state_rejects_invalid_kind():
    state = make_state()
    state.clusters["C1"].kind = "manual"
    with pytest.raises(StateError):
        state.validate()


def test_state_rejects_unsupported_version():
    payload = make_state().to_dict()
    payload["version"] = 2
    with pytest.raises(StateError):
        ReviewState.from_dict(payload)
    payload["version"] = True
    with pytest.raises(StateError):
        ReviewState.from_dict(payload)


def test_state_rejects_malformed_pool():
    payload = make_state().to_dict()
    payload["pending"] = "Q0003"
    with pytest.raises(StateError):
        ReviewState.from_dict(payload)


def test_clone_is_independent():
    state = make_state()
    other = state.clone()
    other.clusters["C1"].members.append("Q0003")
    other.pending.remove("Q0003")
    assert state.clusters["C1"].members == ["Q0001", "Q0002"]
