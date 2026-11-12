"""ReviewState 上的 LLM 归类 patch：校验与按最终状态应用。"""

from __future__ import annotations

from ..entities.cluster import Cluster
from ..entities.state import ReviewState, StateError


class PatchError(ValueError):
    """patch 格式或引用不合法。"""


def _qids(op: dict, kind: str, state: ReviewState, used: set[str]) -> list[str]:
    values = op.get("qids")
    if not isinstance(values, list) or not values or not all(isinstance(qid, str) for qid in values):
        raise PatchError(f"{kind}: qids 必须是非空字符串数组")
    for qid in values:
        if qid not in state.queries:
            raise PatchError(f"{kind}: 未知 QID {qid}")
        if qid in used:
            raise PatchError(f"{kind}: QID {qid} 在 patch 里被重复处理")
        used.add(qid)
    return values


def validate_patch(patch: object, state: ReviewState) -> list[dict]:
    if not isinstance(patch, dict) or not isinstance(patch.get("operations"), list):
        raise PatchError("patch 必须是对象，且包含 operations 数组")
    operations = patch["operations"]
    if not operations:
        raise PatchError("operations 不能为空")

    used: set[str] = set()
    deleted_clusters: set[str] = set()
    for index, op in enumerate(operations):
        if not isinstance(op, dict):
            raise PatchError(f"operations[{index}] 必须是对象")
        kind = op.get("op")
        if kind == "move":
            _qids(op, "move", state, used)
            target = op.get("to")
            if not isinstance(target, dict) or not isinstance(target.get("cluster_id"), str):
                raise PatchError("move: to 必须是 {\"cluster_id\": \"C1\"}")
            if target["cluster_id"] not in state.clusters:
                raise PatchError(f"move: 未知 cluster_id {target['cluster_id']}")
        elif kind == "create":
            qids = _qids(op, "create", state, used)
            if len(qids) < 2:
                raise PatchError("create: 至少需要 2 个 QID")
        elif kind == "park":
            _qids(op, "park", state, used)
        elif kind == "discard":
            _qids(op, "discard", state, used)
            reason = op.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise PatchError("discard: reason 不能为空")
        elif kind == "delete":
            cluster_id = op.get("cluster_id")
            if cluster_id not in state.clusters:
                raise PatchError(f"delete: 未知 cluster_id {cluster_id}")
            if cluster_id in deleted_clusters:
                raise PatchError(f"delete: cluster_id {cluster_id} 被重复删除")
            if "qids" in op:
                raise PatchError("delete: 不接受 qids")
            deleted_clusters.add(cluster_id)
        else:
            raise PatchError(f"operations[{index}]: 不支持的 op {kind!r}")
    return operations


def _location(state: ReviewState, qid: str) -> str:
    for cluster_id, cluster in state.clusters.items():
        if qid in cluster.members:
            return cluster_id
    if qid in state.pending:
        return "pending"
    if qid in state.trash:
        return "trash"
    raise PatchError(f"QID {qid} 没有位置")


def apply_patch(state: ReviewState, patch: object) -> tuple[ReviewState, dict]:
    operations = validate_patch(patch, state)
    work = state.clone()

    before_names = {cid: cluster.name for cid, cluster in state.clusters.items()}
    before_members = {cid: list(cluster.members) for cid, cluster in state.clusters.items()}
    sources = {qid: _location(state, qid) for op in operations
               for qid in (op.get("qids") or [])}
    destinations: dict[str, str] = {}
    created_ids: list[str] = []
    next_new = 1

    for op in operations:
        kind = op["op"]
        if kind == "move":
            for qid in op["qids"]:
                destinations[qid] = op["to"]["cluster_id"]
        elif kind == "create":
            while f"N{next_new}" in work.clusters:
                next_new += 1
            cluster_id = f"N{next_new}"
            next_new += 1
            created_ids.append(cluster_id)
            for qid in op["qids"]:
                destinations[qid] = cluster_id
        elif kind == "park":
            for qid in op["qids"]:
                destinations[qid] = "pending"
        elif kind == "discard":
            for qid in op["qids"]:
                destinations[qid] = "trash"

    for cluster in work.clusters.values():
        cluster.members = [qid for qid in cluster.members if qid not in destinations]
    work.pending = [qid for qid in work.pending if qid not in destinations]
    work.trash = [qid for qid in work.trash if qid not in destinations]

    for op in operations:
        kind = op["op"]
        if kind in {"move", "create"}:
            cluster_id = destinations[op["qids"][0]]
            if cluster_id not in work.clusters:
                work.clusters[cluster_id] = Cluster(cluster_id=cluster_id, kind="llm")
            work.clusters[cluster_id].members.extend(op["qids"])
        elif kind == "park":
            work.pending.extend(op["qids"])
        elif kind == "discard":
            work.trash.extend(op["qids"])

    deleted: list[dict] = []
    for op in operations:
        if op["op"] != "delete":
            continue
        cluster_id = op["cluster_id"]
        cluster = work.clusters.get(cluster_id)
        if cluster is None:
            raise PatchError(f"delete: 簇 {cluster_id} 不存在")
        if cluster.members:
            raise PatchError(f"delete: 簇 {cluster_id} 最终仍有成员")
        del work.clusters[cluster_id]
        deleted.append({"cluster_id": cluster_id, "auto": False})

    for cluster_id in list(work.clusters):
        if not work.clusters[cluster_id].members:
            del work.clusters[cluster_id]
            deleted.append({"cluster_id": cluster_id, "auto": True})

    for cluster_id in created_ids:
        if cluster_id not in work.clusters:
            raise PatchError(f"create: 新建簇 {cluster_id} 没有成员")

    for cluster_id, cluster in work.clusters.items():
        previous = before_members.get(cluster_id)
        cluster.cohesion = None if previous != cluster.members else state.clusters[cluster_id].cohesion

    moves = [
        {
            "qid": qid,
            "text": state.queries[qid].text,
            "from": sources[qid],
            "to": destinations[qid],
        }
        for qid in destinations
    ]
    created = [
        {"cluster_id": cid, "size": len(work.clusters[cid].members)}
        for cid in created_ids
    ]
    log = {
        "moves": moves,
        "created": created,
        "parked": [qid for qid in destinations if destinations[qid] == "pending"],
        "discarded": [{"qid": qid, "reason": op.get("reason", "")} for op in operations
                      if op["op"] == "discard" for qid in op["qids"]],
        "deleted": deleted,
        "before": {cid: {"name": name, "members": before_members[cid]}
                   for cid, name in before_names.items()},
        "after": {cid: {"name": cluster.name, "members": list(cluster.members)}
                  for cid, cluster in work.clusters.items()},
    }

    try:
        work.validate()
    except StateError as exc:
        raise PatchError(str(exc)) from exc

    return work, log
