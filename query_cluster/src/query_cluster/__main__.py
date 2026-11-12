"""命令行入口：python -m query_cluster <cluster|review|qk>。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .canvas import build_canvas
from .clustering.pipeline import build_state, write_state
from .llm import LLMError, client_from_env
from .llm_review import DEFAULT_INSTRUCTIONS, LLMReviewError, review as llm_review, save_outputs
from .manual import load_rules
from .pipeline import build_clusters, load_input, write_result
from .qk import match

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="词汇聚类与 QK 双路匹配")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cluster = sub.add_parser("cluster", help="聚类并输出 JSON 与复核页")
    p_cluster.add_argument("--input", default=None, help="输入文件，词之间用 | 分隔")
    p_cluster.add_argument("--text", default=None, help="直接传入词串，词之间用 | 分隔")
    p_cluster.add_argument("--out", default=str(ROOT / "out"), help="输出目录")
    p_cluster.add_argument("--backend", choices=["auto", "ollama", "hash"], default="auto")
    p_cluster.add_argument("--rules", default=None, help="手动规则簇 JSON；命中的先归到指定类")
    p_cluster.add_argument("--state", action="store_true", help="输出新的 ReviewState state.json")

    p_review = sub.add_parser("review", help="从已有 clusters.json 生成复核页")
    p_review.add_argument("--clusters", required=True)
    p_review.add_argument("--out", required=True)

    p_qk = sub.add_parser("qk", help="单条 query 的 QK 双路匹配")
    p_qk.add_argument("query")
    p_qk.add_argument("--table", default=str(ROOT / "examples" / "qk_table.txt"))
    p_qk.add_argument("--backend", choices=["auto", "ollama", "hash"], default="auto")
    p_qk.add_argument("--json", action="store_true")

    p_llm = sub.add_parser("llm-review", help="LLM 初审并应用 patch")
    p_llm.add_argument("--clusters", required=True, help="输入 clusters.json")
    p_llm.add_argument("--out", required=True, help="输出目录")
    p_llm.add_argument("--instructions", default=DEFAULT_INSTRUCTIONS)
    p_llm.add_argument("--instructions-file", default=None)
    p_llm.add_argument("--base-url", default=None, help="OpenAI 兼容接口，默认 LLM_BASE_URL")
    p_llm.add_argument("--model", default=None, help="模型名，默认 LLM_MODEL")
    p_llm.add_argument("--api-key-env", default="LLM_API_KEY")
    p_llm.add_argument("--timeout", type=int, default=90)
    p_llm.add_argument("--max-attempts", type=int, default=3)

    args = parser.parse_args(argv)

    if args.cmd == "cluster":
        raw = load_input(Path(args.input) if args.input else None, args.text)
        out_dir = Path(args.out)
        if args.state:
            if args.rules:
                parser.error("--state 暂不支持 --rules")
            state = build_state(raw, backend=args.backend)
            state_path = write_state(state, out_dir)
            print(f"{len(state.queries)} 个词 -> {len(state.clusters)} 个簇")
            print(f"状态：{state_path}")
            return 0
        rules = load_rules(args.rules) if args.rules else None
        result = build_clusters(raw, backend=args.backend, rules=rules)
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

    if args.cmd == "llm-review":
        original = json.loads(Path(args.clusters).read_text(encoding="utf-8"))
        clusters = original.get("clusters") or []
        instructions = args.instructions
        if args.instructions_file:
            instructions = Path(args.instructions_file).read_text(encoding="utf-8")
        out_dir = Path(args.out)
        try:
            client = client_from_env(args.base_url, args.model, args.api_key_env, args.timeout)
            new_clusters, removed, log, patch = llm_review(clusters, instructions,
                                                           client.chat, args.max_attempts)
        except (LLMError, LLMReviewError) as exc:
            out_dir.mkdir(parents=True, exist_ok=True)
            attempts = getattr(exc, "attempts", [])
            (out_dir / "llm_failure.json").write_text(
                json.dumps({"error": str(exc), "attempts": attempts}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"LLM 初审失败：{exc}")
            print(f"失败记录：{out_dir / 'llm_failure.json'}")
            return 1
        result = save_outputs(original, new_clusters, removed, log, out_dir,
                              title=f"LLM 初审 · {out_dir.name}")
        print(f"{len(clusters)} 个簇 -> {len(new_clusters)} 个簇；"
              f"移动 {len(log.get('moves', []))} / 改名 {len(log.get('renames', []))} / 移除 {len(log.get('removed', []))}")
        print(f"结果：{out_dir / 'clusters.json'}")
        print(f"复核页：{out_dir / 'review.html'}")
        print(f"变更视图：{out_dir / 'diff.html'}")
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
