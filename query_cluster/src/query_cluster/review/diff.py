"""两份 ReviewState 的差异计算。"""

from __future__ import annotations

from ..entities.state import ReviewState
from ..preprocess.normalize import normalize


class DiffError(ValueError):
    """两份结果无法对比。"""


def _location(state: ReviewState, qid: str) -> dict:
    for cluster_id, cluster in state.clusters.items():
        if qid in cluster.members:
            return {"kind": "cluster", "cluster_id": cluster_id, "name": cluster.name}
    if qid in state.pending:
        return {"kind": "pending"}
    if qid in state.trash:
        return {"kind": "trash"}
    raise DiffError(f"QID {qid} 没有位置")


def _text(state: ReviewState, qid: str) -> str:
    return state.queries[qid].text if qid in state.queries else qid


def _qid_map(base: ReviewState, target: ReviewState) -> tuple[dict[str, str], list[str], list[str]]:
    """把 target QID 对齐到 base QID：优先同 QID，其次归一化文本。"""
    base_by_text = {normalize(query.text): qid for qid, query in base.queries.items()}
    mapping: dict[str, str] = {}
    unmatched_target: list[str] = []
    for qid, query in target.queries.items():
        if qid in base.queries:
            mapping[qid] = qid
        elif normalize(query.text) in base_by_text:
            mapping[qid] = base_by_text[normalize(query.text)]
        else:
            unmatched_target.append(qid)
    matched = set(mapping.values())
    unmatched_base = [qid for qid in base.queries if qid not in matched]
    return mapping, unmatched_base, unmatched_target


def diff_states(base: ReviewState, target: ReviewState) -> dict:
    mapping, unmatched_base, unmatched_target = _qid_map(base, target)

    def canonical(qid: str) -> str:
        return mapping.get(qid, qid)

    base_clusters = base.clusters
    target_clusters = target.clusters
    clusters: list[dict] = []
    created: list[dict] = []
    deleted: list[dict] = []
    renames: list[dict] = []

    for cluster_id, cluster in target_clusters.items():
        before = base_clusters.get(cluster_id)
        raw_members = list(cluster.members)
        members_canonical = {canonical(qid) for qid in raw_members}
        before_members = set(before.members) if before else set()
        added = [qid for qid in raw_members if canonical(qid) not in before_members]
        removed = [qid for qid in (before.members if before else []) if qid not in members_canonical]
        if before is None:
            status = "new"
            created.append({"cluster_id": cluster_id, "name": cluster.name, "members": raw_members})
        elif added or removed or before.name != cluster.name:
            status = "changed"
        else:
            status = "unchanged"
        if before is not None and before.name != cluster.name:
            renames.append({"cluster_id": cluster_id, "from": before.name, "to": cluster.name})
        clusters.append({
            "cluster_id": cluster_id,
            "name": cluster.name,
            "before_name": before.name if before else "",
            "kind": cluster.kind,
            "status": status,
            "members": raw_members,
            "added": added,
            "removed": removed,
            "cohesion": cluster.cohesion,
        })

    for cluster_id, cluster in base_clusters.items():
        if cluster_id in target_clusters:
            continue
        deleted.append({
            "cluster_id": cluster_id,
            "name": cluster.name,
            "members": list(cluster.members),
        })

    moves = []
    for target_qid, base_qid in mapping.items():
        before = _location(base, base_qid)
        after = _location(target, target_qid)
        if (before["kind"], before.get("cluster_id")) != (after["kind"], after.get("cluster_id")):
            moves.append({
                "qid": target_qid,
                "text": _text(target, target_qid),
                "from": before,
                "to": after,
            })

    def pool_diff(name: str, base_ids: list[str], target_ids: list[str]) -> dict:
        target_canonical = {canonical(qid) for qid in target_ids}
        base_set = set(base_ids)
        return {
            "added": [qid for qid in target_ids if canonical(qid) not in base_set],
            "removed": [qid for qid in base_ids if qid not in target_canonical],
            "base_count": len(base_ids),
            "target_count": len(target_ids),
        }

    pending = pool_diff("pending", base.pending, target.pending)
    trash = pool_diff("trash", base.trash, target.trash)

    summary = {
        "base_clusters": len(base_clusters),
        "target_clusters": len(target_clusters),
        "moves": len(moves),
        "renames": len(renames),
        "created": len(created),
        "deleted": len(deleted),
        "pending_added": len(pending["added"]),
        "pending_removed": len(pending["removed"]),
        "trash_added": len(trash["added"]),
        "trash_removed": len(trash["removed"]),
        "unmatched_base": len(unmatched_base),
        "unmatched_target": len(unmatched_target),
    }
    return {
        "summary": summary,
        "clusters": clusters,
        "created": created,
        "deleted": deleted,
        "renames": renames,
        "moves": moves,
        "pending": pending,
        "trash": trash,
        "unmatched": {
            "base": [{"qid": qid, "text": _text(base, qid)} for qid in unmatched_base],
            "target": [{"qid": qid, "text": _text(target, qid)} for qid in unmatched_target],
        },
    }
