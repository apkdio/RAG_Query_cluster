import pytest

from query_cluster.tools.migrate import MigrationError, migrate_payload


def test_migrate_legacy_terms():
    payload = {
        "clusters": [
            {
                "cluster_id": "C1",
                "name": "价格",
                "kind": "auto",
                "terms": [
                    {"query_id": "C1:Q1", "text": "苹果多少钱", "count": 2},
                    {"query_id": "C1:Q2", "text": "香蕉价格", "count": 1},
                ],
            },
            {
                "cluster_id": "C2",
                "name": "保存",
                "terms": [{"query_id": "C2:Q1", "text": "苹果怎么保存", "count": 1}],
            },
        ],
        "pending": [],
        "trash": ["C2:Q1"],
    }
    state = migrate_payload(payload)
    assert [query.qid for query in state.queries.values()] == ["Q0001", "Q0002", "Q0003"]
    assert state.clusters["C1"].members == ["Q0001", "Q0002"]
    assert state.location("Q0003") == ("trash", None)


def test_migrate_rejects_duplicate_query_across_clusters():
    payload = {
        "clusters": [
            {"cluster_id": "C1", "terms": [{"text": "苹果多少钱"}]},
            {"cluster_id": "C2", "terms": [{"text": "苹果多少钱"}]},
        ]
    }
    with pytest.raises(MigrationError):
        migrate_payload(payload)


def test_migrate_accepts_new_state():
    from query_cluster.entities import Cluster, Query, ReviewState

    state = ReviewState(
        queries={"Q0001": Query("Q0001", "苹果多少钱")},
        clusters={"C1": Cluster("C1", "价格", ["Q0001"])},
    )
    assert migrate_payload(state.to_dict()) == state
