from pathlib import Path

from query_cluster.canvas import build_canvas
from query_cluster.cluster import cluster_terms
from query_cluster.pipeline import build_clusters, parse_terms
from query_cluster.qk import match

ROOT = Path(__file__).resolve().parents[1]


def test_parse_dedupes_and_counts():
    texts, counts = parse_terms("苹果多少钱 | 香蕉价格 | 苹果多少钱 || 橙子")
    assert texts == ["苹果多少钱", "香蕉价格", "橙子"]
    assert counts["苹果多少钱"] == 2


def test_cluster_merges_related_terms():
    texts = ["苹果价格", "香蕉价格", "苹果保存", "苹果保存方法"]
    vectors = [[1.0, 0.0, 0.0], [0.95, 0.1, 0.0], [0.0, 1.0, 0.0], [0.0, 0.9, 0.1]]
    groups = cluster_terms(texts, vectors)
    assert sorted(len(g) for g in groups) == [2, 2]


def test_pipeline_outputs_ids():
    result = build_clusters("苹果多少钱|香蕉价格|橙子怎么挑", backend="hash")
    assert result["meta"]["count"] == 3
    ids = [term["query_id"] for cluster in result["clusters"] for term in cluster["terms"]]
    assert all(part.startswith("C") and ":Q" in part for part in ids)
    assert len(ids) == 3


def _rule(name, keywords=None, regex=None, match="any"):
    return {"name": name, "keywords": keywords or [], "regex": regex or [],
            "exclude": [], "match": match}


def test_manual_rules_take_priority():
    rules = [
        _rule("价格相关", regex=["多少钱|价格"]),
        _rule("保存相关", regex=["保存|保鲜"]),
    ]
    result = build_clusters("苹果多少钱|香蕉价格|怎么保存|苹果保鲜|橙子", backend="hash", rules=rules)
    by_name = {c["name"]: [t["text"] for t in c["terms"]] for c in result["clusters"]}
    assert by_name["价格相关"] == ["苹果多少钱", "香蕉价格"]
    assert by_name["保存相关"] == ["怎么保存", "苹果保鲜"]
    assert by_name["自动聚类"] == ["橙子"]


def test_manual_rules_first_match_wins():
    rules = [
        _rule("价格相关", regex=["价格"]),
        _rule("保存相关", regex=["保存"]),
    ]
    result = build_clusters("价格保存", backend="hash", rules=rules)
    assert result["clusters"][0]["name"] == "价格相关"
    assert result["clusters"][0]["terms"][0]["text"] == "价格保存"


def test_keywords_and_regex_combine_by_match():
    any_rule = [_rule("价格相关", keywords=["价格"], regex=[r"\d+元"], match="any")]
    result = build_clusters("价格多少|500元|苹果", backend="hash", rules=any_rule)
    manual = [t["text"] for c in result["clusters"] if c["kind"] == "manual" for t in c["terms"]]
    assert manual == ["价格多少", "500元"]

    all_rule = [_rule("价格相关", keywords=["价格"], regex=[r"\d+元"], match="all")]
    result = build_clusters("价格500元|价格|500元", backend="hash", rules=all_rule)
    manual = [t["text"] for c in result["clusters"] if c["kind"] == "manual" for t in c["terms"]]
    assert manual == ["价格500元"]


def test_canvas_review_embeds_result(tmp_path):
    result = build_clusters("苹果多少钱|香蕉价格", backend="hash")
    out = build_canvas(result, tmp_path / "review.html", title="测试复核", key="unit")
    html = out.read_text(encoding="utf-8")
    assert "苹果多少钱" in html
    assert "__DATA__" not in html
    assert "测试复核" in html


def test_qk_matches_fruit_table():
    result = match("苹果多少钱", ROOT / "examples" / "qk_table.txt", backend="hash")
    assert result["matches"][0]["slug"] == "水果咨询"
