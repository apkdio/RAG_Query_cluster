"""ReviewState：Query、Cluster、pending、trash 的唯一状态源。"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .cluster import CLUSTER_KINDS, Cluster
from .query import QID_PATTERN, Query

STATE_VERSION = 1


class StateError(ValueError):
    """状态不合法。"""


@dataclass
class ReviewState:
    queries: dict[str, Query] = field(default_factory=dict)
    clusters: dict[str, Cluster] = field(default_factory=dict)
    pending: list[str] = field(default_factory=list)
    trash: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def validate(self) -> None:
        errors: list[str] = []
        if not isinstance(self.queries, dict):
            raise StateError("queries 必须是字典")
        if not isinstance(self.clusters, dict):
            raise StateError("clusters 必须是字典")
        if not isinstance(self.meta, dict):
            raise StateError("meta 必须是字典")
        if not isinstance(self.events, list):
            raise StateError("events 必须是列表")

        for qid, query in self.queries.items():
            if not isinstance(qid, str) or not QID_PATTERN.fullmatch(qid):
                errors.append(f"QID 格式非法：{qid!r}")
                continue
            if not isinstance(query, Query):
                errors.append(f"{qid} 不是 Query")
                continue
            if query.qid != qid:
                errors.append(f"{qid} 的 qid 不一致：{query.qid}")
            try:
                query.validate()
            except ValueError as exc:
                errors.append(str(exc))

        owner: dict[str, str] = {}
        for cluster_id, cluster in self.clusters.items():
            if not isinstance(cluster_id, str) or not cluster_id.strip():
                errors.append("cluster_id 不能为空")
                continue
            if not isinstance(cluster, Cluster):
                errors.append(f"{cluster_id} 不是 Cluster")
                continue
            if cluster.cluster_id != cluster_id:
                errors.append(f"{cluster_id} 的 cluster_id 不一致：{cluster.cluster_id}")
            if cluster.kind not in CLUSTER_KINDS:
                errors.append(f"{cluster_id} 的 kind 非法：{cluster.kind!r}")
            if not isinstance(cluster.members, list) or not cluster.members:
                errors.append(f"{cluster_id} 的 members 不能为空")
                continue
            seen: set[str] = set()
            for qid in cluster.members:
                if not isinstance(qid, str) or qid not in self.queries:
                    errors.append(f"{cluster_id} 引用了未知 QID：{qid!r}")
                    continue
                if qid in seen:
                    errors.append(f"{cluster_id} 的 members 有重复 QID：{qid}")
                    continue
                seen.add(qid)
                if qid in owner:
                    errors.append(f"QID {qid} 同时出现在 {owner[qid]} 和 {cluster_id}")
                else:
                    owner[qid] = cluster_id
            if not isinstance(cluster.name, str):
                errors.append(f"{cluster_id} 的 name 必须是字符串")
            if cluster.cohesion is not None and (
                not isinstance(cluster.cohesion, (int, float)) or isinstance(cluster.cohesion, bool)
            ):
                errors.append(f"{cluster_id} 的 cohesion 必须是数字或 None")
            for field_name in ("slug", "keywords"):
                if not isinstance(getattr(cluster, field_name), str):
                    errors.append(f"{cluster_id} 的 {field_name} 必须是字符串")
            if not isinstance(cluster.no_action, bool):
                errors.append(f"{cluster_id} 的 no_action 必须是布尔值")

        for pool_name, pool in (("pending", self.pending), ("trash", self.trash)):
            if not isinstance(pool, list):
                errors.append(f"{pool_name} 必须是列表")
                continue
            seen: set[str] = set()
            for qid in pool:
                if not isinstance(qid, str) or qid not in self.queries:
                    errors.append(f"{pool_name} 引用了未知 QID：{qid!r}")
                    continue
                if qid in seen:
                    errors.append(f"{pool_name} 有重复 QID：{qid}")
                    continue
                seen.add(qid)
                if qid in owner:
                    errors.append(f"QID {qid} 同时出现在 {owner[qid]} 和 {pool_name}")
                else:
                    owner[qid] = pool_name

        placed = set(owner)
        missing = sorted(set(self.queries) - placed)
        unknown = sorted(placed - set(self.queries))
        if missing:
            errors.append(f"以下 QID 没有位置：{missing}")
        if unknown:
            errors.append(f"以下 QID 不存在：{unknown}")
        if not all(isinstance(event, dict) for event in self.events):
            errors.append("events 的每一项都必须是对象")

        if errors:
            raise StateError("；".join(errors))

    def to_dict(self) -> dict:
        self.validate()
        return {
            "version": STATE_VERSION,
            "meta": copy.deepcopy(self.meta),
            "queries": {qid: query.to_dict() for qid, query in self.queries.items()},
            "clusters": [
                {
                    "cluster_id": cluster.cluster_id,
                    "name": cluster.name,
                    "kind": cluster.kind,
                    "cohesion": cluster.cohesion,
                    "members": list(cluster.members),
                    "no_action": cluster.no_action,
                    "slug": cluster.slug,
                    "keywords": cluster.keywords,
                }
                for cluster in self.clusters.values()
            ],
            "pending": list(self.pending),
            "trash": list(self.trash),
            "events": copy.deepcopy(self.events),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ReviewState":
        if not isinstance(payload, dict):
            raise StateError("state 必须是对象")
        version = payload.get("version", STATE_VERSION)
        if not isinstance(version, int) or isinstance(version, bool) or version != STATE_VERSION:
            raise StateError(f"不支持的 state version：{version!r}")

        raw_queries = payload.get("queries")
        if not isinstance(raw_queries, dict):
            raise StateError("queries 必须是字典")
        queries: dict[str, Query] = {}
        for qid, raw in raw_queries.items():
            try:
                queries[qid] = Query.from_dict(qid, raw)
            except ValueError as exc:
                raise StateError(str(exc)) from exc

        raw_clusters = payload.get("clusters", [])
        if not isinstance(raw_clusters, list):
            raise StateError("clusters 必须是列表")
        clusters: dict[str, Cluster] = {}
        for raw in raw_clusters:
            if not isinstance(raw, dict):
                raise StateError("clusters 的每一项都必须是对象")
            cluster_id = raw.get("cluster_id")
            if not isinstance(cluster_id, str) or not cluster_id.strip():
                raise StateError("cluster_id 不能为空")
            if cluster_id in clusters:
                raise StateError(f"cluster_id 重复：{cluster_id}")
            members = raw.get("members", [])
            if not isinstance(members, list):
                raise StateError(f"{cluster_id} 的 members 必须是列表")
            clusters[cluster_id] = Cluster(
                cluster_id=cluster_id,
                name=raw.get("name", ""),
                members=list(members),
                kind=raw.get("kind", "auto"),
                cohesion=raw.get("cohesion"),
                no_action=raw.get("no_action", False),
                slug=raw.get("slug", ""),
                keywords=raw.get("keywords", ""),
            )

        pending = payload.get("pending", [])
        trash = payload.get("trash", [])
        events = payload.get("events", [])
        meta = payload.get("meta", {})
        for name, value in (("pending", pending), ("trash", trash), ("events", events)):
            if not isinstance(value, list):
                raise StateError(f"{name} 必须是列表")
        if not isinstance(meta, dict):
            raise StateError("meta 必须是对象")

        state = cls(
            queries=queries,
            clusters=clusters,
            pending=list(pending),
            trash=list(trash),
            events=list(events),
            meta=dict(meta),
        )
        state.validate()
        return state

    def location(self, qid: str) -> tuple[str, str | None]:
        """返回 ('cluster', cluster_id) / ('pending', None) / ('trash', None)。"""
        for cluster_id, cluster in self.clusters.items():
            if qid in cluster.members:
                return "cluster", cluster_id
        if qid in self.pending:
            return "pending", None
        if qid in self.trash:
            return "trash", None
        raise KeyError(f"未知 QID：{qid}")

    def final_members(self, cluster_id: str) -> list[str]:
        return list(self.clusters[cluster_id].members)

    def clone(self) -> "ReviewState":
        return copy.deepcopy(self)
