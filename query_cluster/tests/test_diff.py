from query_cluster.entities import Cluster, Query, ReviewState
from query_cluster.review.diff import diff_states


def make_state(clusters, pending=None, trash=None) -> ReviewState:
    queries = {
        "Q0001": Query("Q0001", "苹果多少钱"),
        "Q0002": Query("Q0002", "香蕉价格"),
        "Q0003": Query("Q0003", "橙子怎么挑"),
        "Q0004": Query("Q0004", "附近水果店"),
    }
    pending = list(pending or [])
    trash = list(trash or [])
    placed = {qid for cluster in clusters.values() for qid in cluster.members}
    placed.update(pending)
    placed.update(trash)
    pending.extend(qid for qid in queries if qid not in placed)
    return ReviewState(queries=queries, clusters=clusters, pending=pending, trash=trash)


def test_diff_moves_renames_and_deleted_cluster():
    base = make_state({
        "C1": Cluster("C1", "价格", ["Q0001", "Q0002"]),
        "C2": Cluster("C2", "挑选", ["Q0003", "Q0004"]),
    })
    target = make_state({
        "C1": Cluster("C1", "价格咨询", ["Q0001", "Q0002", "Q0003"]),
    }, pending=["Q0004"])
    diff = diff_states(base, target)
    assert diff["summary"]["moves"] == 2
    assert diff["summary"]["renames"] == 1
    assert diff["summary"]["deleted"] == 1
    assert diff["renames"][0]["to"] == "价格咨询"
    assert [item["cluster_id"] for item in diff["deleted"]] == ["C2"]
    assert {item["qid"] for item in diff["moves"]} == {"Q0003", "Q0004"}


def test_diff_new_cluster_and_pools():
    base = make_state({
        "C1": Cluster("C1", "价格", ["Q0001", "Q0002"]),
    }, pending=["Q0003"], trash=["Q0004"])
    target = make_state({
        "C1": Cluster("C1", "价格", ["Q0001"]),
        "N1": Cluster("N1", "其他", ["Q0002", "Q0003"]),
    }, trash=["Q0004"])
    diff = diff_states(base, target)
    assert diff["summary"]["created"] == 1
    assert diff["summary"]["moves"] == 2
    assert diff["summary"]["pending_removed"] == 1
    assert diff["pending"]["removed"] == ["Q0003"]


def test_diff_aligns_qid_by_normalized_text():
    base = ReviewState(
        queries={"Q0001": Query("Q0001", "苹果多少钱")},
        clusters={"C1": Cluster("C1", "价格", ["Q0001"])},
    )
    target = ReviewState(
        queries={"Q0009": Query("Q0009", "苹果多少钱")},
        clusters={"C1": Cluster("C1", "价格", ["Q0009"])},
    )
    diff = diff_states(base, target)
    assert diff["summary"]["unmatched_target"] == 0
    assert diff["summary"]["unmatched_base"] == 0
    assert diff["clusters"][0]["added"] == []
    assert diff["clusters"][0]["removed"] == []


def test_diff_reports_unmatched_qids():
    base = ReviewState(
        queries={"Q0001": Query("Q0001", "苹果多少钱")},
        clusters={"C1": Cluster("C1", "价格", ["Q0001"])},
    )
    target = ReviewState(
        queries={
            "Q0001": Query("Q0001", "苹果多少钱"),
            "Q0005": Query("Q0005", "新出现的词"),
        },
        clusters={"C1": Cluster("C1", "价格", ["Q0001", "Q0005"])},
    )
    diff = diff_states(base, target)
    assert diff["summary"]["unmatched_target"] == 1
    assert [item["qid"] for item in diff["unmatched"]["target"]] == ["Q0005"]
    assert diff["clusters"][0]["added"] == ["Q0005"]
