"""把旧 clusters.json（terms 结构）迁移成 ReviewState。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..entities.cluster import CLUSTER_KINDS, Cluster
from ..entities.query import Query, format_qid
from ..entities.state import ReviewState, StateError
from ..preprocess.normalize import normalize


class MigrationError(ValueError):
    """旧数据无法无损迁移。"""


def _legacy_terms(payload: dict) -> tuple[dict[str, Query], dict[str, Cluster], dict[str, str]]:
    queries: dict[str, Query] = {}
    by_text: dict[str, str] = {}
    old_ids: dict[str, str] = {}
    clusters: dict[str, Cluster] = {}
    owners: dict[str, str] = {}

    for raw_cluster in payload.get("clusters", []):
        if not isinstance(raw_cluster, dict):
            raise MigrationError("clusters 的每一项都必须是对象")
        cluster_id = str(raw_cluster.get("cluster_id") or "")
        if not cluster_id:
            raise MigrationError("旧簇缺少 cluster_id")
        if cluster_id in clusters:
            raise MigrationError(f"旧簇重复：{cluster_id}")
        members: list[str] = []
        for term in raw_cluster.get("terms", []):
            if not isinstance(term, dict):
                raise MigrationError(f"{cluster_id} 的 terms 必须是对象")
            text = str(term.get("text") or "").strip()
            if not text:
                raise MigrationError(f"{cluster_id} 有空的 query")
            key = normalize(text)
            qid = by_text.get(key)
            if qid is None:
                qid = format_qid(len(queries) + 1)
                by_text[key] = qid
                queries[qid] = Query(qid=qid, text=text)
            old_id = term.get("query_id")
            if old_id:
                old_ids[str(old_id)] = qid
            if qid in owners and owners[qid] != cluster_id:
                raise MigrationError(f"query「{text}」同时出现在 {owners[qid]} 和 {cluster_id}")
            owners[qid] = cluster_id
            if qid not in members:
                members.append(qid)
        if not members:
            raise MigrationError(f"旧簇 {cluster_id} 没有成员")
        kind = str(raw_cluster.get("kind") or "auto")
        if kind not in CLUSTER_KINDS:
            kind = "auto"
        clusters[cluster_id] = Cluster(
            cluster_id=cluster_id,
            name=str(raw_cluster.get("name") or ""),
            members=members,
            kind=kind,
            cohesion=raw_cluster.get("cohesion"),
            no_action=bool(raw_cluster.get("no_action", False)),
            slug=str(raw_cluster.get("slug") or ""),
            keywords=str(raw_cluster.get("keywords") or ""),
        )
    return queries, clusters, old_ids


def migrate_payload(payload: dict) -> ReviewState:
    if not isinstance(payload, dict):
        raise MigrationError("旧结果必须是对象")
    if isinstance(payload.get("queries"), dict) and isinstance(payload.get("clusters"), list):
        try:
            return ReviewState.from_dict(payload)
        except StateError as exc:
            raise MigrationError(str(exc)) from exc
    if not isinstance(payload.get("clusters"), list):
        raise MigrationError("旧结果缺少 clusters 列表")

    queries, clusters, old_ids = _legacy_terms(payload)
    pending = [old_ids[str(qid)] for qid in payload.get("pending", []) if str(qid) in old_ids]
    trash = [old_ids[str(qid)] for qid in payload.get("trash", []) if str(qid) in old_ids]
    for removed in payload.get("removed", []):
        if isinstance(removed, dict) and str(removed.get("query_id")) in old_ids:
            trash.append(old_ids[str(removed["query_id"])])
    pending = list(dict.fromkeys(pending))
    trash = list(dict.fromkeys(trash))
    pooled = set(pending) | set(trash)
    for cluster in clusters.values():
        cluster.members = [qid for qid in cluster.members if qid not in pooled]
    clusters = {cid: cluster for cid, cluster in clusters.items() if cluster.members}
    state = ReviewState(
        queries=queries,
        clusters=clusters,
        pending=pending,
        trash=trash,
        meta={
            "stage": "clustering",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source": "legacy_migration",
        },
    )
    state.validate()
    return state


def migrate_file(path: Path | str) -> ReviewState:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return migrate_payload(payload)
