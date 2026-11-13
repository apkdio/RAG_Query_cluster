"""Cluster 实体。"""

from __future__ import annotations

from dataclasses import dataclass, field

CLUSTER_KINDS = frozenset({"auto", "manual", "llm"})


@dataclass
class Cluster:
    """一个簇；members 只存 QID，顺序用于展示。"""

    cluster_id: str
    name: str = ""
    members: list[str] = field(default_factory=list)
    kind: str = "auto"
    cohesion: float | None = None
    no_action: bool = False
    slug: str = ""
    keywords: str = ""
    llm_touched: bool = False
    human_touched: bool = False
