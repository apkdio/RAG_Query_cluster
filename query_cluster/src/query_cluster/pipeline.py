"""输入解析、聚类与结果 JSON 组装。"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import manual
from .cluster import THRESHOLD, cluster_terms, cohesion, similarity_matrix
from .embed import embed_texts


def parse_terms(raw: str) -> tuple[list[str], dict[str, int]]:
    """按 | 或换行切分，去掉空白与重复，保留首次出现顺序。"""
    parts = [p.strip() for p in raw.replace("\n", "|").split("|")]
    texts: list[str] = []
    counts: Counter[str] = Counter()
    for part in parts:
        if not part:
            continue
        counts[part] += 1
        if part not in texts:
            texts.append(part)
    return texts, dict(counts)


def load_input(path: Path | None, text: str | None) -> str:
    if text:
        return text
    if path is None:
        raise SystemExit("请提供 --input 文件或 --text \"词1|词2\"")
    return Path(path).read_text(encoding="utf-8")


def build_clusters(raw: str, backend: str = "auto", rules: list[dict] | None = None) -> dict:
    texts, counts = parse_terms(raw)
    if not texts:
        raise SystemExit("输入为空")
    vectors, actual_backend = embed_texts(texts, backend)
    sim = similarity_matrix(vectors)

    groups: list[tuple[str, str, list[int]]] = []
    remaining = list(range(len(texts)))
    if rules:
        buckets, remaining = manual.assign_clusters(texts, rules)
        groups.extend((name, "manual", members) for name, members in buckets)
    if remaining:
        auto_texts = [texts[i] for i in remaining]
        auto_vectors = [vectors[i] for i in remaining]
        auto_members = cluster_terms(auto_texts, auto_vectors, THRESHOLD)
        groups.extend(("自动聚类", "auto", [remaining[i] for i in group])
                      for group in auto_members)

    clusters = []
    for cid, (name, kind, group) in enumerate(groups, start=1):
        cluster_id = f"C{cid}"
        terms = []
        for qid, idx in enumerate(group, start=1):
            terms.append({
                "query_id": f"{cluster_id}:Q{qid}",
                "text": texts[idx],
                "count": counts[texts[idx]],
            })
        clusters.append({
            "cluster_id": cluster_id,
            "name": name,
            "kind": kind,
            "size": len(group),
            "cohesion": cohesion(group, sim),
            "terms": terms,
        })

    return {
        "meta": {
            "count": len(texts),
            "clusters": len(clusters),
            "threshold": THRESHOLD,
            "embedding": actual_backend,
            "manual_rules": [rule["name"] for rule in (rules or [])],
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "clusters": clusters,
    }


def write_result(result: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "clusters.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
