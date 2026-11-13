"""命令行入口：python -m query_cluster <cluster|llm-review|serve|migrate>。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .clustering.pipeline import build_state, write_state
from .entities.state import ReviewState
from .llm import LLMError, client_from_env
from .llm.client import load_config
from .llm.review import (
    DEFAULT_INSTRUCTIONS,
    LLMReviewError,
    review_state,
    save_result,
)
from .paths import OUT_DIR
from .review.server import serve as serve_review
from .state_files import CLUSTERING_STATE


def _read_input(path: str | None, text: str | None) -> str:
    if text:
        return text
    if path is None:
        raise SystemExit("请提供 --input 文件或 --text \"词1|词2\"")
    return Path(path).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="词汇聚类与人工复核")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cluster = sub.add_parser("cluster", help="自动聚类并输出 state.clustering.json")
    p_cluster.add_argument("--input", default=None, help="输入文件，词之间用 | 分隔")
    p_cluster.add_argument("--text", default=None, help="直接传入词串，词之间用 | 分隔")
    p_cluster.add_argument("--out", default=str(OUT_DIR), help="输出目录")
    p_cluster.add_argument("--config", default=None,
                           help="聚类配置，默认 config/clustering.json（缺失时用 example）")
    p_cluster.add_argument("--backend", choices=["auto", "ollama", "hash"], default=None,
                           help="覆盖配置里的 embedding 后端")

    p_serve = sub.add_parser("serve", help="启动 ReviewState 本地复核服务")
    p_serve.add_argument("--state", required=True, help="state.clustering/llm/human.json")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)

    p_migrate = sub.add_parser("migrate", help="把旧 clusters.json 转成 ReviewState")
    p_migrate.add_argument("--input", required=True, help="旧 clusters.json")
    p_migrate.add_argument("--out", required=True, help="输出 state.clustering.json 路径")

    p_llm = sub.add_parser("llm-review", help="ReviewState 的两阶段 LLM 复核")
    p_llm.add_argument("--state", required=True, help="输入 state.clustering.json")
    p_llm.add_argument("--out", default=None, help="输出目录；默认与 --state 同目录")
    p_llm.add_argument("--instructions", default=DEFAULT_INSTRUCTIONS)
    p_llm.add_argument("--instructions-file", default=None)
    p_llm.add_argument("--base-url", default=None, help="默认取 config/llm.json 或 LLM_BASE_URL")
    p_llm.add_argument("--model", default=None, help="默认取 config/llm.json 或 LLM_MODEL")
    p_llm.add_argument("--api-key-env", default=None, help="默认取 config/llm.json 或 LLM_API_KEY")
    p_llm.add_argument("--timeout", type=int, default=None, help="默认取 config/llm.json")
    p_llm.add_argument("--max-attempts", type=int, default=None,
                       help="默认取 config/llm.json 的 max_attempts")

    args = parser.parse_args(argv)

    if args.cmd == "cluster":
        raw = _read_input(args.input, args.text)
        state = build_state(raw, backend=args.backend, config_path=args.config)
        state_path = write_state(state, Path(args.out), filename=CLUSTERING_STATE)
        print(f"{len(state.queries)} 个词 -> {len(state.clusters)} 个簇")
        print(f"状态：{state_path}")
        return 0

    if args.cmd == "serve":
        return serve_review(args.state, args.host, args.port)

    if args.cmd == "migrate":
        from .tools.migrate import migrate_file

        state = migrate_file(args.input)
        state_path = write_state(state, Path(args.out).parent, filename=Path(args.out).name)
        print(f"{len(state.queries)} 个词 -> {len(state.clusters)} 个簇")
        print(f"状态：{state_path}")
        return 0

    if args.cmd == "llm-review":
        instructions = args.instructions
        if args.instructions_file:
            instructions = Path(args.instructions_file).read_text(encoding="utf-8")
        out_dir = Path(args.out) if args.out else Path(args.state).parent
        try:
            state = ReviewState.from_dict(json.loads(Path(args.state).read_text(encoding="utf-8")))
            client = client_from_env(args.base_url, args.model, args.api_key_env, args.timeout)
            max_attempts = (
                args.max_attempts if args.max_attempts is not None
                else int(load_config().get("max_attempts", 3))
            )
            result = review_state(state, instructions, client.chat, max_attempts)
        except (LLMError, LLMReviewError, ValueError) as exc:
            out_dir.mkdir(parents=True, exist_ok=True)
            attempts = getattr(exc, "attempts", [])
            (out_dir / "llm_failure.json").write_text(
                json.dumps({"error": str(exc), "attempts": attempts}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"LLM 初审失败：{exc}")
            print(f"失败记录：{out_dir / 'llm_failure.json'}")
            return 1
        state_path = save_result(result, out_dir)
        print(f"{len(state.clusters)} 个簇 -> {len(result.state.clusters)} 个簇；"
              f"移动 {len(result.log.get('moves', []))} / 新建 {len(result.log.get('created', []))}")
        if result.naming_failed:
            print("命名失败，已保留归类结果")
        print(f"状态：{state_path}")
        return 0

    parser.error(f"未知命令：{args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
