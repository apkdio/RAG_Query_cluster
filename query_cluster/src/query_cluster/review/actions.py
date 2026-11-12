"""人工复核动作：在 ReviewState 上移动、建簇、待定、丢弃、改名和删除。"""

from __future__ import annotations

from ..entities.cluster import Cluster
from ..entities.events import new_event
from ..entities.state import ReviewState, StateError


class ActionError(ValueError):
    """人工复核动作不合法。"""


def _qids(action: dict) -> list[str]:
    values = action.get("qids")
    if values is None and isinstance(action.get("qid"), str):
        values = [action["qid"]]
    if not isinstance(values, list) or not values or not all(isinstance(qid, str) for qid in values):
        raise ActionError("qids 必须是非空字符串数组")
    return list(dict.fromkeys(values))


def _take(work: ReviewState, qids: list[str]) -> set[str]:
    targets = set(qids)
    touched: set[str] = set()
    for cluster_id, cluster in work.clusters.items():
        before = len(cluster.members)
        cluster.members = [qid for qid in cluster.members if qid not in targets]
        if len(cluster.members) != before:
            touched.add(cluster_id)
    work.pending = [qid for qid in work.pending if qid not in targets]
    work.trash = [qid for qid in work.trash if qid not in targets]
    return touched


def _next_cluster_id(work: ReviewState) -> str:
    index = 1
    while f"N{index}" in work.clusters:
        index += 1
    return f"N{index}"


def apply_action(state: ReviewState, action: dict) -> ReviewState:
    if not isinstance(action, dict):
        raise ActionError("action 必须是对象")
    op = action.get("op")
    work = state.clone()
    touched: set[str] = set()

    if op == "move":
        qids = _qids(action)
        target = action.get("to")
        if not isinstance(target, str) or not target:
            raise ActionError("move: to 必须是 cluster_id 或 pending/trash")
        for qid in qids:
            if qid not in work.queries:
                raise ActionError(f"未知 QID {qid}")
        touched = _take(work, qids)
        if target.lower() in {"pending", "trash"}:
            pool = work.pending if target.lower() == "pending" else work.trash
            pool.extend(qids)
        else:
            if target not in work.clusters:
                raise ActionError(f"未知 cluster_id {target}")
            work.clusters[target].members.extend(qids)
            touched.add(target)
    elif op == "park":
        qids = _qids(action)
        touched = _take(work, qids)
        work.pending.extend(qids)
    elif op == "discard":
        qids = _qids(action)
        touched = _take(work, qids)
        work.trash.extend(qids)
    elif op == "create":
        qids = _qids(action)
        touched = _take(work, qids)
        cluster_id = _next_cluster_id(work)
        name = action.get("name", "")
        if not isinstance(name, str):
            raise ActionError("create: name 必须是字符串")
        work.clusters[cluster_id] = Cluster(
            cluster_id=cluster_id, name=name.strip(), members=qids, kind="llm",
        )
    elif op == "rename":
        cluster_id = action.get("cluster_id")
        name = action.get("name")
        if cluster_id not in work.clusters:
            raise ActionError(f"未知 cluster_id {cluster_id}")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40:
            raise ActionError("rename: name 必须是 1–40 个字符")
        work.clusters[cluster_id].name = name.strip()
    elif op == "delete":
        cluster_id = action.get("cluster_id")
        cluster = work.clusters.get(cluster_id)
        if cluster is None:
            raise ActionError(f"未知 cluster_id {cluster_id}")
        if cluster.members:
            raise ActionError("delete: 只能删除空簇")
        del work.clusters[cluster_id]
    else:
        raise ActionError(f"不支持的 op {op!r}")

    for cluster in work.clusters.values():
        if cluster.cluster_id in touched:
            cluster.cohesion = None
    for cluster_id in list(work.clusters):
        if not work.clusters[cluster_id].members:
            del work.clusters[cluster_id]
    work.events.append(new_event("human_action", action=action))
    try:
        work.validate()
    except StateError as exc:
        raise ActionError(str(exc)) from exc
    return work
