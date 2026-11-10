"""命令行入口：python -m query_core <cluster|review|qk>。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .canvas import build_canvas
from .manual import load_rules
from .pipeline import build_clusters, load_input, write_result
from .qk import match

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="词汇聚类与 QK 双路匹配")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cluster = sub.add_parser("cluster", help="聚类并输出 JSON 与复核页")
    p_cluster.add_argument("--input", default=None, help="输入文件，词之间用 | 分隔")
    p_cluster.add_argument("--text", default=None, help="直接传入词串，词之间用 | 分隔")
    p_cluster.add_argument("--out", default=str(ROOT / "out"), help="输出目录")
    p_cluster.add_argument("--backend", choices=["auto", "ollama", "hash"], default="auto")
    p_cluster.add_argument("--rules", default=None, help="手动规则簇 JSON；命中的先归到指定类")

    p_review = sub.add_parser("review", help="从已有 clusters.json 生成复核页")
    p_review.add_argument("--clusters", required=True)
    p_review.add_argument("--out", required=True)

    p_qk = sub.add_parser("qk", help="单条 query 的 QK 双路匹配")
    p_qk.add_argument("query")
    p_qk.add_argument("--table", default=str(ROOT / "examples" / "qk_table.txt"))
    p_qk.add_argument("--backend", choices=["auto", "ollama", "hash"], default="auto")
    p_qk.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "cluster":
        raw = load_input(Path(args.input) if args.input else None, args.text)
        rules = load_rules(args.rules) if args.rules else None
        result = build_clusters(raw, backend=args.backend, rules=rules)
        out_dir = Path(args.out)
        json_path = write_result(result, out_dir)
        html_path = build_canvas(result, out_dir / "review.html", key=out_dir.name)
        print(f"{result['meta']['count']} 个词 -> {result['meta']['clusters']} 个簇")
        print(f"结果：{json_path}")
        print(f"复核页：{html_path}")
        return 0

    if args.cmd == "review":
        payload = json.loads(Path(args.clusters).read_text(encoding="utf-8"))
        out_path = Path(args.out)
        path = build_canvas(payload, out_path, key=out_path.parent.name)
        print(f"复核页：{path}")
        return 0

    result = match(args.query, Path(args.table), backend=args.backend)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"query: {result['query']}    向量: {result['embedding']}\n")
        for idx, item in enumerate(result["matches"], start=1):
            print(f"  #{idx}  {item['name']}（{item['slug']}）  score={item['score']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
