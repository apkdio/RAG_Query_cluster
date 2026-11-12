"""对比两份 QK 词表，定位「新增 / 删除 / 修改」了哪些问句。

典型用法：先在 data/qk_keys.json 里手动改（模拟改完的效果），再和 raw 版本对比。

    python -m qk_validation.table                          # 默认 base=data/qk_corpus.json, current=data/qk_keys.json
    python -m qk_validation.table --base raw.json --current data/qk_keys.json
    python -m qk_validation.table --json
    python -m qk_validation.table --threshold 0.6          # 判定「修改」的相似度阈值（默认 0.4）

判定规则：
- 同一 slug 下，问句原文比对：多了 = 新增，少了 = 删除
- 删除项与新增项按文本相似度配对（≥ threshold）→ 视为「修改」
- slug 级：新 slug / 消失的 slug 单独列出
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
DEFAULT_BASE = str(BASE / "data" / "qk_corpus.json")
DEFAULT_CURRENT = str(BASE / "data" / "qk_keys.json")


def load_keys(path: str = DEFAULT_CURRENT) -> tuple[str, list[tuple[str, str, list[str]]]]:
    """读取 QK 词表，返回 (日期, [(slug, name, [问句...])])。

    支持两种文件：
    1) 最简（推荐，手改方便）：{"slug_name_1": "xxx##xxx##xxx"}
    2) 旧格式：{"d": "YYYY-MM-DD", "nodes": [{"slug": ..., "name": ..., "questions": [...]}]}
    """
    if not os.path.isfile(path):
        raise SystemExit(f"找不到词表文件 {path}（格式见 README「准备词表」）")

    with open(path, "r", encoding="utf-8-sig") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path} 不是合法 JSON：{exc}") from exc

    items: list[tuple[str, str, list[str]]] = []
    day = ""

    if isinstance(data, dict) and isinstance(data.get("nodes"), list):
        day = str(data.get("date") or data.get("d") or "")
        for node in data["nodes"]:
            slug = str(node.get("slug") or node.get("file_id") or "").strip()
            if not slug:
                continue
            name = str(node.get("name") or node.get("title") or slug)
            qs = [str(q).strip() for q in (node.get("questions") or []) if str(q).strip()]
            items.append((slug, name, qs))
        return day, items

    if isinstance(data, dict):
        name_map = data.get("_names") if isinstance(data.get("_names"), dict) else {}
        for slug, value in data.items():
            key = str(slug).strip()
            if not key or key.startswith("_"):
                continue
            if isinstance(value, str):
                qs = [q.strip() for q in value.replace("＃", "#").split("#") if q.strip()]
            elif isinstance(value, list):
                qs = [str(q).strip() for q in value if str(q).strip()]
            else:
                continue
            items.append((key, str(name_map.get(key) or key), qs))
        return day, items

    raise SystemExit(f"{path} 格式不支持：应为 {{slug: \"问句#问句\"}} 或 {{\"nodes\": [...]}}")


def as_map(items: list[tuple[str, str, list[str]]]) -> tuple[dict[str, list[str]], dict[str, str]]:
    qmap: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for slug, name, qs in items:
        qmap[slug] = list(dict.fromkeys(q.strip() for q in qs if q.strip()))
        names[slug] = name
    return qmap, names


def similarity(a: str, b: str) -> float:
    """中文改写场景的相似度：取「整体序列相似度」与「最长公共子串占比」的较大值。

    例：两句整体相似度很低，但共享一个核心短语时，判为改写更合理。
    """
    sm = difflib.SequenceMatcher(None, a, b)
    ratio = sm.ratio()
    match = sm.find_longest_match(0, len(a), 0, len(b))
    shorter = min(len(a), len(b)) or 1
    return max(ratio, match.size / shorter)


def best_match(text: str, candidates: list[str], threshold: float) -> tuple[str, float] | None:
    best: tuple[str, float] | None = None
    for cand in candidates:
        ratio = similarity(text, cand)
        if ratio >= threshold and (best is None or ratio > best[1]):
            best = (cand, ratio)
    return best


def diff_slug(base_qs: list[str], cur_qs: list[str], threshold: float):
    base_set, cur_set = set(base_qs), set(cur_qs)
    removed = [q for q in base_qs if q not in cur_set]
    added = [q for q in cur_qs if q not in base_set]

    modified: list[tuple[str, str, float]] = []
    matched_added: set[str] = set()
    for old in removed:
        # 只在「还没配对的 added」里找最像的
        pool = [a for a in added if a not in matched_added]
        hit = best_match(old, pool, threshold)
        if hit:
            new, ratio = hit
            matched_added.add(new)
            modified.append((old, new, ratio))

    removed_pure = [q for q in removed if all(q != m[0] for m in modified)]
    added_pure = [a for a in added if a not in matched_added]
    return added_pure, removed_pure, modified


def print_list(title: str, items: list[str], prefix: str) -> None:
    if not items:
        return
    print(f"  {title} ({len(items)})")
    for q in items:
        print(f"    {prefix} {q}")


def run(args: argparse.Namespace) -> int:
    base_day, base_items = load_keys(args.base)
    cur_day, cur_items = load_keys(args.current)
    base_qmap, base_names = as_map(base_items)
    cur_qmap, cur_names = as_map(cur_items)

    all_slugs = list(dict.fromkeys(list(base_qmap) + list(cur_qmap)))
    new_slugs = [s for s in cur_qmap if s not in base_qmap]
    gone_slugs = [s for s in base_qmap if s not in cur_qmap]

    report = {
        "base": {"path": args.base, "day": base_day, "slugs": len(base_qmap),
                 "questions": sum(len(v) for v in base_qmap.values())},
        "current": {"path": args.current, "day": cur_day, "slugs": len(cur_qmap),
                    "questions": sum(len(v) for v in cur_qmap.values())},
        "new_slugs": [],
        "gone_slugs": [],
        "slugs": [],
    }

    print(f"base   : {args.base}（{len(base_qmap)} slug / {sum(len(v) for v in base_qmap.values())} 问句）")
    print(f"current: {args.current}（{len(cur_qmap)} slug / {sum(len(v) for v in cur_qmap.values())} 问句）")
    print(f"阈值   : {args.threshold}")

    if new_slugs:
        print("\n【新增 slug】")
        for s in new_slugs:
            print(f"  + {s}（{cur_names.get(s, s)}）：{len(cur_qmap[s])} 条")
            report["new_slugs"].append({"slug": s, "name": cur_names.get(s, s), "count": len(cur_qmap[s])})

    if gone_slugs:
        print("\n【消失 slug】")
        for s in gone_slugs:
            print(f"  - {s}（{base_names.get(s, s)}）：{len(base_qmap[s])} 条")
            report["gone_slugs"].append({"slug": s, "name": base_names.get(s, s), "count": len(base_qmap[s])})

    total_added = total_removed = total_modified = 0

    for slug in all_slugs:
        if slug in new_slugs or slug in gone_slugs:
            continue
        added, removed, modified = diff_slug(base_qmap[slug], cur_qmap[slug], args.threshold)
        if not (added or removed or modified):
            continue

        total_added += len(added)
        total_removed += len(removed)
        total_modified += len(modified)

        print(f"\n【{slug}】{cur_names.get(slug, slug)}")
        print_list("新增", added, "+")
        print_list("删除", removed, "-")
        if modified:
            print(f"  修改 ({len(modified)})")
            for old, new, ratio in modified:
                print(f"    ~ {old}")
                print(f"      → {new}   (相似度 {ratio:.2f})")

        report["slugs"].append(
            {
                "slug": slug,
                "name": cur_names.get(slug, slug),
                "added": added,
                "removed": removed,
                "modified": [{"old": o, "new": n, "ratio": round(r, 4)} for o, n, r in modified],
            }
        )

    print("\n" + "=" * 60)
    print(f"合计：新增 {total_added}  删除 {total_removed}  修改 {total_modified}"
          f"  新增slug {len(new_slugs)}  消失slug {len(gone_slugs)}")
    if not report["slugs"] and not new_slugs and not gone_slugs:
        print("（两份词表完全一致）")

    report["totals"] = {
        "added": total_added,
        "removed": total_removed,
        "modified": total_modified,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE, help="基准（raw）词表")
    ap.add_argument("--current", default=DEFAULT_CURRENT, help="当前词表（你手改的那份）")
    ap.add_argument("--threshold", type=float, default=0.4,
                    help="判定「修改」的相似度阈值（默认 0.4；调高更严格，改写会显示为 +/−）")
    ap.add_argument("--json", action="store_true")
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
