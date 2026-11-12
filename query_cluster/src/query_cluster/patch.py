"""LLM patch 的校验与应用。

patch 示例：

{
  "operations": [
    {"op": "rename", "cluster_id": "C1", "name": "价格咨询"},
    {"op": "move", "query_ids": ["C2:Q3"], "to": "C1"},
    {"op": "create", "name": "售后问题", "query_ids": ["C3:Q1"]},
    {"op": "merge", "clusters": ["C5", "C6"], "into": "C5"},
    {"op": "remove", "query_ids": ["C7:Q2"], "reason": "噪声"}
  ]
}
"""

from __future__ import annotations

import copy


class PatchError(ValueError):
    """patch 格式或引用不合法。"""


def validate_patch(patch: object, clusters: list[dict]) -> list[dict]:
    if not isinstance(patch, dict) or not isinstance(patch.get("operations"), list):
        raise PatchError("patch 必须是对象，且包含 operations 数组")
    operations = patch["operations"]
    if not operations:
        raise PatchError("operations 不能为空")

    cluster_ids = {c["cluster_id"] for c in clusters}
    query_ids = {t["query_id"] for c in clusters for t in c["terms"]}
    used_queries: set[str] = set()

    def check_queries(ids: object, op: str) -> list[str]:
        if not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids):
            raise PatchError(f"{op}: query_ids 必须是非空字符串数组")
        for qid in ids:
            if qid not in query_ids:
                raise PatchError(f"{op}: 未知 query_id {qid}")
            if qid in used_queries:
                raise PatchError(f"{op}: query_id {qid} 在 patch 里被重复处理")
            used_queries.add(qid)
        return ids

    def check_cluster(cid: object, op: str) -> str:
        if not isinstance(cid, str) or cid not in cluster_ids:
            raise PatchError(f"{op}: 未知 cluster_id {cid}")
        return cid

    for idx, op in enumerate(operations):
        if not isinstance(op, dict):
            raise PatchError(f"operations[{idx}] 必须是对象")
        kind = op.get("op")
        if kind == "rename":
            check_cluster(op.get("cluster_id"), "rename")
            name = op.get("name")
            if not isinstance(name, str) or not name.strip() or len(name) > 40:
                raise PatchError("rename: name 必须是 1–40 字的字符串")
        elif kind == "move":
            check_queries(op.get("query_ids"), "move")
            check_cluster(op.get("to"), "move")
        elif kind == "create":
            name = op.get("name")
            if not isinstance(name, str) or not name.strip() or len(name) > 40:
                raise PatchError("create: name 必须是 1–40 字的字符串")
            check_queries(op.get("query_ids"), "create")
        elif kind == "merge":
            sources = op.get("clusters")
            if not isinstance(sources, list) or not sources:
                raise PatchError("merge: clusters 必须是非空数组")
            for cid in sources:
                check_cluster(cid, "merge")
            target = check_cluster(op.get("into"), "merge")
            if target in sources:
                raise PatchError("merge: 目标簇不能同时出现在 clusters 里")
        elif kind == "remove":
            check_queries(op.get("query_ids"), "remove")
        else:
            raise PatchError(f"operations[{idx}]: 不支持的 op {kind!r}")
    return operations


def apply_patch(clusters: list[dict], patch: object) -> tuple[list[dict], list[dict], dict]:
    operations = validate_patch(patch, clusters)
    cmap = {c["cluster_id"]: copy.deepcopy(c) for c in clusters}
    order = [c["cluster_id"] for c in clusters]
    before_names = {c["cluster_id"]: c.get("name", "") for c in clusters}
    before_qids = {cid: [t["query_id"] for t in c["terms"]] for cid, c in cmap.items()}
    before_cohesion = {cid: c.get("cohesion") for cid, c in cmap.items()}

    def owner(qid: str) -> str:
        for cid in order:
            if any(t["query_id"] == qid for t in cmap[cid]["terms"]):
                return cid
        raise PatchError(f"未知 query_id {qid}")

    def take(qid: str) -> dict:
        src = owner(qid)
        for idx, term in enumerate(cmap[src]["terms"]):
            if term["query_id"] == qid:
                return cmap[src]["terms"].pop(idx)
        raise PatchError(f"未知 query_id {qid}")

    log = {"moves": [], "renames": [], "created": [], "merged": [], "removed": []}
    new_index = 1
    for op in operations:
        kind = op["op"]
        if kind == "rename":
            cid = op["cluster_id"]
            log["renames"].append({"cluster_id": cid, "from": cmap[cid].get("name", ""), "to": op["name"].strip()})
            cmap[cid]["name"] = op["name"].strip()
        elif kind == "move":
            target = op["to"]
            for qid in op["query_ids"]:
                src = owner(qid)
                term = take(qid)
                cmap[target]["terms"].append(term)
                log["moves"].append({"query_id": qid, "text": term["text"], "from": src, "to": target})
        elif kind == "create":
            while f"N{new_index}" in cmap:
                new_index += 1
            cid = f"N{new_index}"
            new_index += 1
            cmap[cid] = {"cluster_id": cid, "name": op["name"].strip(), "kind": "llm",
                         "cohesion": None, "terms": []}
            order.append(cid)
            for qid in op["query_ids"]:
                src = owner(qid)
                term = take(qid)
                cmap[cid]["terms"].append(term)
                log["moves"].append({"query_id": qid, "text": term["text"], "from": src, "to": cid})
            log["created"].append({"cluster_id": cid, "name": cmap[cid]["name"], "size": len(cmap[cid]["terms"])})
        elif kind == "merge":
            target = op["into"]
            moved = 0
            for src in op["clusters"]:
                for term in list(cmap[src]["terms"]):
                    cmap[target]["terms"].append(term)
                    log["moves"].append({"query_id": term["query_id"], "text": term["text"], "from": src, "to": target})
                    moved += 1
                cmap[src]["terms"] = []
                order.remove(src)
            log["merged"].append({"clusters": op["clusters"], "into": target, "moved": moved})
        elif kind == "remove":
            for qid in op["query_ids"]:
                src = owner(qid)
                term = take(qid)
                log["removed"].append({"query_id": qid, "text": term["text"], "from": src,
                                       "reason": op.get("reason", "")})

    result = []
    for cid in order:
        cluster = cmap[cid]
        if not cluster["terms"]:
            continue
        current = [t["query_id"] for t in cluster["terms"]]
        unchanged = before_qids.get(cid) == current
        cluster["size"] = len(cluster["terms"])
        cluster["cohesion"] = before_cohesion.get(cid) if unchanged else None
        for idx, term in enumerate(cluster["terms"], start=1):
            term["query_id"] = f"{cid}:Q{idx}"
        result.append(cluster)

    log["before"] = {cid: before_names.get(cid, "") for cid in before_names}
    log["after"] = {c["cluster_id"]: {"name": c.get("name", ""), "size": c["size"]} for c in result}
    return result, log["removed"], log
