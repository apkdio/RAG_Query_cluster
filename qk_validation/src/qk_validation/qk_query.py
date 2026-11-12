"""本地一条 query 的 QK 匹配 + 临时加 K + diff。

词表用 data/qk_keys.json（你手改的那份），阈值在 config/qk_config.json 里按来源配置。

用法：
    # 1) 匹配：这条 query 会被哪个节点接住
    python -m qk_validation.qk_query "怎么使用" --s 1

    # 2) 临时加一条 K，看排名变化（不写文件）
    python -m qk_validation.qk_query "如何查看说明" --s 1 --slug node_1 --add-key "说明在哪里看"

    # 3) 确认要加，落盘
    python -m qk_validation.qk_query "如何查看说明" --s 1 --slug node_1 --add-key "说明在哪里看" --save

    # 4) 看词表相对 raw 改了什么
    python -m qk_validation.qk_query "怎么使用" --s 1 --diff

口径：稠密 = bge-m3 cosine；关键词 = tf-idf 稀疏余弦 × 词覆盖率；
score = 1/(60+稠密位次) + 1/(60+关键词位次)，关键词需过该来源阈值才算进列表。
关键词分为本地近似，阈值附近的样本可能不稳定。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

from .qk_diff import load_keys
from .relevance_matrix import cosine, embed_batch, set_backend, tokenize

RRF_K = 60
BASE = Path(__file__).resolve().parents[2]
DEFAULT_KEYS = str(BASE / "data" / "qk_keys.json")
DEFAULT_BASE = str(BASE / "data" / "qk_corpus.json")
CONFIG_PATH = BASE / "config" / "qk_config.json"
CONFIG_EXAMPLE = BASE / "config" / "qk_config.example.json"


def load_sources() -> tuple[dict[int, tuple[str, float]], str | None]:
    """读取 config/qk_config.json；缺失时回退示例，再缺失用内置占位源。"""
    for path in (CONFIG_PATH, CONFIG_EXAMPLE):
        if path.exists():
            cfg = json.loads(path.read_text(encoding="utf-8-sig"))
            blocks = cfg.get("sources") or {}
            if blocks:
                mapping = {i: (name, float(block.get("threshold", 0.5)))
                           for i, (name, block) in enumerate(blocks.items())}
                return mapping, cfg.get("default_source")
    return {0: ("source_a", 0.5), 1: ("source_b", 0.5)}, None


def pick_source(raw: str | None, mapping: dict[int, tuple[str, float]],
                default_name: str | None) -> tuple[str, float]:
    if raw is None:
        for name, threshold in mapping.values():
            if name == default_name:
                return name, threshold
        return mapping[min(mapping)]
    if raw.isdigit():
        idx = int(raw)
        if idx not in mapping:
            raise SystemExit(f"没有第 {idx} 个来源，可用：{sorted(mapping)}")
        return mapping[idx]
    for name, threshold in mapping.values():
        if name == raw:
            return name, threshold
    raise SystemExit(f"未知来源 {raw}，可用：{[n for n, _ in mapping.values()]}")


def build_idf(docs: list[list[str]]) -> dict[str, float]:
    df: Counter = Counter()
    for toks in docs:
        for t in set(toks):
            df[t] += 1
    n = len(docs)
    return {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}


def sparse_vec(tokens: list[str], idf: dict[str, float], max_idf: float) -> dict[str, float]:
    """词表外的词保留并给最高 idf，用来稀释相似度——否则多一个「的」不会掉分。"""
    tf = Counter(tokens)
    vec = {t: (1 + math.log(c)) * idf.get(t, max_idf) for t, c in tf.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {t: v / norm for t, v in vec.items()}


def sparse_cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def rank_positions(scores: list[float], slugs: list[str], gated: list[bool] | None = None) -> dict[str, int]:
    out: dict[str, int] = {}
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    n = 0
    for i in order:
        if gated is not None and not gated[i]:
            continue
        if slugs[i] not in out:
            out[slugs[i]] = n
            n += 1
    return out


def score_query(query: str, questions: list[str], slugs: list[str], kw_thr: float):
    toks = [tokenize(q) for q in questions]
    idf = build_idf(toks)
    max_idf = math.log((len(toks) + 1) / 0.5)
    q_tokens = tokenize(query)
    qv_sparse = sparse_vec(q_tokens, idf, max_idf)
    q_set = set(q_tokens)

    kw_scores = []
    for t in toks:
        base = sparse_cos(qv_sparse, sparse_vec(t, idf, max_idf))
        coverage = (sum(1 for x in q_set if x in set(t)) / len(q_set)) if q_set else 0.0
        kw_scores.append(base * coverage)
    gated = [s >= kw_thr for s in kw_scores]

    qvec = embed_batch([query])[0]
    dense_scores = [cosine(qvec, v) for v in embed_batch(questions)]

    dense_pos = rank_positions(dense_scores, slugs)
    kw_pos = rank_positions(kw_scores, slugs, gated)

    fused: dict[str, float] = {}
    for slug in set(dense_pos) | set(kw_pos):
        s = 0.0
        if slug in dense_pos:
            s += 1.0 / (RRF_K + dense_pos[slug])
        if slug in kw_pos:
            s += 1.0 / (RRF_K + kw_pos[slug])
        fused[slug] = s
    return fused, dense_pos, kw_pos, dense_scores, sum(gated)


def save_key(path: str, slug: str, text: str) -> None:
    with open(path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if isinstance(data.get("nodes"), list):
        raise SystemExit(f"{path} 是旧版 nodes 格式，--save 只支持扁平的 {{slug: 问句串}} 词表")
    current = data.get(slug, "")
    qs = current if isinstance(current, list) else str(current).split("#")
    qs = [q for q in (str(x).strip() for x in qs) if q]
    if text in qs:
        print(f"（{slug} 里已有这句，未重复写入）")
        return
    qs.append(text)
    data[slug] = "#".join(qs) if isinstance(current, str) else qs
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"已写入 {path}：{slug} += 「{text}」")


def compact_diff(keys_path: str, base_path: str) -> None:
    from qk_diff import diff_slug
    from qk_diff import load_keys as load

    _, base_items = load(base_path)
    _, cur_items = load(keys_path)
    base = {s: qs for s, _, qs in base_items}
    cur = {s: qs for s, _, qs in cur_items}
    added = removed = modified = 0
    for slug in cur:
        a, r, m = diff_slug(base.get(slug, []), cur[slug], 0.4)
        added += len(a)
        removed += len(r)
        modified += len(m)
    print(f"diff vs {base_path}: 新增 {added} / 删除 {removed} / 修改 {modified}"
          f" / 新增节点 {len([s for s in cur if s not in base])}")


def print_top(fused: dict[str, float], names: dict[str, str], questions: list[str],
              slugs: list[str], dense_scores: list[float], top: int) -> None:
    for n, (slug, score) in enumerate(sorted(fused.items(), key=lambda kv: -kv[1])[:top], 1):
        best = max((i for i, s in enumerate(slugs) if s == slug), key=lambda i: dense_scores[i])
        print(f"  #{n}  {names.get(slug, slug)}（{slug}）  score={score:.6f}  hit=「{questions[best]}」")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--s", default=None, help="来源名或序号；默认取 config/qk_config.json 的 default_source")
    ap.add_argument("--keys", default=DEFAULT_KEYS)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--slug", default="", help="配合 --add-key：新问句归属的节点")
    ap.add_argument("--add-key", default="", help="临时加一条问句（只在内存里生效，除非加 --save）")
    ap.add_argument("--save", action="store_true", help="把 --add-key 写进词表文件")
    ap.add_argument("--diff", action="store_true", help="末尾附上相对基准词表的改动摘要")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--kw-threshold", type=float, default=None)
    ap.add_argument("--min-dense", type=float, default=0.0,
                    help="稠密最高分低于此值视为无结果（0=关闭；具体值按本地数据标定）")
    ap.add_argument("--embedding", choices=["auto", "ollama", "lite"], default="auto",
                    help="auto=优先 Ollama，失败退回哈希占位；ollama=必须可用；lite=直接哈希占位")
    args = ap.parse_args()
    set_backend(args.embedding)

    source_map, default_source = load_sources()
    source, default_kw = pick_source(args.s, source_map, default_source)
    kw_thr = args.kw_threshold if args.kw_threshold is not None else default_kw

    _, items = load_keys(args.keys)
    questions: list[str] = []
    slugs: list[str] = []
    names: dict[str, str] = {}
    for slug, name, qs in items:
        names[slug] = name
        for q in qs:
            text = str(q).strip()
            if text:
                questions.append(text)
                slugs.append(slug)

    print(f"query: {args.query}   来源: {source}")

    fused, dpos, kpos, dscores, gated_n = score_query(args.query, questions, slugs, kw_thr)
    top_dense = max(dscores) if dscores else 0.0
    if args.min_dense and top_dense < args.min_dense:
        print()
        print(f"无结果：稠密最高分 {top_dense:.4f} < 闸门 {args.min_dense}")
        return 0
    print()
    print(f"匹配结果（top {args.top}）")
    print_top(fused, names, questions, slugs, dscores, args.top)

    if args.add_key:
        if not args.slug:
            print("--add-key 需要同时给 --slug", file=sys.stderr)
            return 2
        ext_q = questions + [args.add_key]
        ext_s = slugs + [args.slug]
        fused2, dpos2, kpos2, dscores2, gated_n2 = score_query(args.query, ext_q, ext_s, kw_thr)
        base_rows = sorted(fused.items(), key=lambda kv: -kv[1])
        after_rows = sorted(fused2.items(), key=lambda kv: -kv[1])
        base_rank = ([s for s, _ in base_rows].index(args.slug) + 1) if args.slug in fused else None
        after_rank = ([s for s, _ in after_rows].index(args.slug) + 1) if args.slug in fused2 else None
        print()
        print(f"加入 K：{names.get(args.slug, args.slug)}（{args.slug}） += 「{args.add_key}」")
        print(f"  目标节点排名: {base_rank or '未入榜'} → {after_rank or '未入榜'}"
              f"   分数: {fused.get(args.slug, 0.0):.6f} → {fused2.get(args.slug, 0.0):.6f}")
        print()
        print(f"加 K 后（top {args.top}）")
        print_top(fused2, names, ext_q, ext_s, dscores2, args.top)
        if args.save:
            save_key(args.keys, args.slug, args.add_key)

    if args.diff:
        print()
        compact_diff(args.keys, args.base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
