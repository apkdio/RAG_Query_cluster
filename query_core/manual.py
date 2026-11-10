"""手动指定簇：按规则文件把 query 先归到指定簇。

规则示例见 examples/rules.json：

{
  "clusters": [
    {"name": "价格相关", "regex": ["多少钱|价格|费用"]},
    {"name": "保存相关", "regex": ["保存|保鲜|存放"]}
  ]
}

支持 `keywords` 和 `regex`；两者是两个独立字段，可同时写。
`match: any`（默认）表示任一关键词或任一条正则命中；`match: all` 表示所有关键词和所有正则都要命中。
`exclude` 用于排除；一条 query 命中多个规则时按顺序取第一个，都没命中的进入自动聚类。
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def load_rules(path: Path | str) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    rules = payload.get("clusters") if isinstance(payload, dict) else payload
    if not isinstance(rules, list):
        raise SystemExit(f"{path}: 规则文件应为列表，或含 clusters 列表")

    cleaned = []
    for rule in rules:
        name = str(rule.get("name") or "").strip()
        keywords = [str(k).strip() for k in (rule.get("keywords") or []) if str(k).strip()]
        regex = [str(r) for r in (rule.get("regex") or []) if str(r)]
        if not name or (not keywords and not regex):
            raise SystemExit(f"{path}: 每条规则都需要 name，以及 keywords 或 regex")
        try:
            for pattern in regex:
                re.compile(pattern)
        except re.error as exc:
            raise SystemExit(f"{path}: 规则「{name}」的正则无效：{exc}") from exc
        cleaned.append({
            "name": name,
            "keywords": keywords,
            "regex": regex,
            "exclude": [str(k).strip() for k in (rule.get("exclude") or []) if str(k).strip()],
            "match": str(rule.get("match") or "any").lower(),
        })
    return cleaned


def _match(text: str, rule: dict) -> bool:
    value = text.casefold()
    hits = [keyword.casefold() in value for keyword in rule["keywords"]]
    hits += [bool(re.search(pattern, text)) for pattern in rule["regex"]]
    if not hits:
        return False
    return all(hits) if rule["match"] == "all" else any(hits)


def _excluded(text: str, rule: dict) -> bool:
    value = text.casefold()
    return any(keyword.casefold() in value for keyword in rule["exclude"])


def assign_clusters(texts: list[str], rules: list[dict]) -> tuple[list[tuple[str, list[int]]], list[int]]:
    """返回 ([(规则名, 下标)], 未命中下标)。"""
    buckets: list[tuple[str, list[int]]] = [(rule["name"], []) for rule in rules]
    remaining: list[int] = []
    for idx, text in enumerate(texts):
        matched = None
        for rule, bucket in zip(rules, buckets):
            if _excluded(text, rule) or not _match(text, rule):
                continue
            matched = bucket
            break
        if matched is None:
            remaining.append(idx)
        else:
            matched[1].append(idx)
    return [(name, members) for name, members in buckets if members], remaining
