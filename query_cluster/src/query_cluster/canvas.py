"""把聚类结果注入画布式复核页。"""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "legacy_review.html"


def build_canvas(result: dict, out_path: Path, title: str | None = None, key: str = "review") -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    clusters = []
    themes: dict[str, str] = {}
    for idx, cluster in enumerate(result["clusters"], start=1):
        texts = [term["text"] for term in cluster["terms"]]
        for term in cluster["terms"]:
            label = term.get("theme") or ""
            if label:
                themes[term["text"]] = label
        manual_name = cluster.get("name") if cluster.get("kind") == "manual" else ""
        cohesion = cluster.get("cohesion")
        clusters.append({
            "id": f"{idx:04d}",
            "theme": manual_name,
            "meta": f'{len(texts)} 条 / 内聚 {cohesion if cohesion is not None else "—"}',
            "core": texts,
            "calls": [term.get("count", 1) for term in cluster["terms"]],
            "users": None,
            "cohesion": cohesion,
            "out": [],
            "in": [],
        })

    data = {
        "key": key,
        "title": title or "簇复核",
        "fileName": "clusters.json",
        "clusters": clusters,
        "themes": themes,
        "source": key,
        "stats": {"calls_total": result["meta"]["count"], "clusters": len(clusters)},
    }
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    html = html.replace("__TITLE__", json.dumps(title or "簇复核", ensure_ascii=False))
    out_path.write_text(html, encoding="utf-8")
    return out_path
