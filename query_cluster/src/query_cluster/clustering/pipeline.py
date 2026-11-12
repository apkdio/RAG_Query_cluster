"""输入 → 去重/QID → 自动聚类 → ReviewState。"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from ..entities.cluster import Cluster
from ..entities.state import ReviewState
from ..preprocess.dedupe import dedupe_queries
from .algorithm import THRESHOLD, cluster_terms, cohesion, similarity_matrix
from .embed import embed_texts


def build_state(raw: str, backend: str = "auto", threshold: float = THRESHOLD,
                now: str | None = None) -> ReviewState:
    """把一批用 | 分隔的词聚成 ReviewState。"""
    queries = dedupe_queries(raw)
    if not queries:
        raise ValueError("输入为空")

    texts = [query.text for query in queries]
    vectors, actual_backend = embed_texts(texts, backend)
    sim = similarity_matrix(vectors)
    groups = cluster_terms(texts, vectors, threshold)

    clusters: dict[str, Cluster] = {}
    for index, group in enumerate(groups, start=1):
        cluster_id = f"C{index}"
        clusters[cluster_id] = Cluster(
            cluster_id=cluster_id,
            members=[queries[position].qid for position in group],
            kind="auto",
            cohesion=cohesion(group, sim),
        )

    state = ReviewState(
        queries={query.qid: query for query in queries},
        clusters=clusters,
        meta={
            "stage": "clustering",
            "created_at": now or datetime.now().isoformat(timespec="seconds"),
            "source": "average_link",
            "threshold": threshold,
            "embedding": actual_backend,
            "count": len(queries),
            "clusters": len(clusters),
        },
    )
    state.validate()
    return state


def write_state_file(state: ReviewState, path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    body = json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n"
    for attempt in range(3):
        try:
            temporary.write_text(body, encoding="utf-8")
            temporary.replace(target)
            return target
        except OSError:
            if attempt < 2:
                time.sleep(0.05)
    # 某些 Windows 临时目录不允许 rename 覆盖，退化为直接写目标文件。
    target.write_text(body, encoding="utf-8")
    temporary.unlink(missing_ok=True)
    return target


def write_state(state: ReviewState, out_dir: Path | str,
                filename: str = "state.json") -> Path:
    return write_state_file(state, Path(out_dir) / filename)
