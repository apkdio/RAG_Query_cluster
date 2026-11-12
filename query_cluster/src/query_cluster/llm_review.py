"""LLM 初审：生成 patch、校验、重试、应用并产出复核页。"""

from __future__ import annotations

import html
import json
from pathlib import Path

from .canvas import build_canvas
from .patch import PatchError, apply_patch

SYSTEM_PROMPT = """你是 query 主题聚类的复核助手。输入是一组已经聚好的簇，每个簇有 cluster_id、name 和 terms（query_id 与文本）。

你的任务是给出一个可执行的 JSON patch，修正明显错误的归类，并给簇起简短中文名。

只允许以下操作：
1. rename：{"op":"rename","cluster_id":"C1","name":"新簇名"}
2. move：{"op":"move","query_ids":["C2:Q3"],"to":"C1"}
3. create：{"op":"create","name":"新簇名","query_ids":["C3:Q1"]}
4. merge：{"op":"merge","clusters":["C5","C6"],"into":"C5"}
5. remove：{"op":"remove","query_ids":["C7:Q2"],"reason":"噪声"}

输出格式必须是：
{"operations":[...]}

规则：
- 只能引用输入里出现过的 cluster_id 和 query_id；
- 每个 query 在一次 patch 里最多出现在一个操作中；
- move 的目标簇必须已存在，新簇用 create；
- 不要把正常 query 放进 remove，remove 只用于明确噪声或无法归类的内容；
- 没有把握时宁可不动；
- 只输出 JSON，不要 Markdown、解释或注释。
"""

DEFAULT_INSTRUCTIONS = "请初审这些簇：修正明显放错的 query，必要时新建簇并命名，给每个簇起简洁中文名。只处理明显错误，不要为了改而改。"


class LLMReviewError(RuntimeError):
    def __init__(self, message: str, attempts: list[dict]):
        super().__init__(message)
        self.attempts = attempts


def parse_patch(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end < start:
        raise PatchError("输出里找不到 JSON 对象")
    try:
        return json.loads(value[start:end + 1])
    except json.JSONDecodeError as exc:
        raise PatchError(f"JSON 解析失败：{exc}") from exc


def review(clusters: list[dict], instructions: str, chat, max_attempts: int = 3) -> tuple[list[dict], list[dict], dict, dict]:
    payload = json.dumps({"clusters": clusters}, ensure_ascii=False)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{instructions}\n\n输入：\n{payload}"},
    ]
    attempts = []
    for attempt in range(1, max_attempts + 1):
        content = chat(messages)
        try:
            patch = parse_patch(content)
            new_clusters, removed, log = apply_patch(clusters, patch)
            log["attempts"] = attempts + [{"attempt": attempt, "ok": True}]
            log["patch"] = patch
            return new_clusters, removed, log, patch
        except PatchError as exc:
            attempts.append({"attempt": attempt, "ok": False, "error": str(exc), "output": content})
            if attempt == max_attempts:
                break
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"上一次输出无法应用：{exc}\n请只返回修正后的完整 JSON patch，不要解释。"})
    raise LLMReviewError(f"连续 {max_attempts} 次输出未通过校验", attempts)


def _diff_html(log: dict, title: str) -> str:
    esc = lambda value: html.escape(str(value or ""))
    before = log.get("before", {})
    after = log.get("after", {})
    names_before = {cid: before.get(cid, "") for cid in before}
    names_after = {cid: (after.get(cid) or {}).get("name", "") for cid in after}

    def table(headers, rows):
        if not rows:
            return "<p class='muted'>无</p>"
        head = "".join(f"<th>{esc(h)}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    moves = [[m["text"], names_before.get(m["from"], m["from"]), names_after.get(m["to"], m["to"])]
             for m in log.get("moves", [])]
    renames = [[r["cluster_id"], r["from"], r["to"]] for r in log.get("renames", [])]
    created = [[c["cluster_id"], c["name"], c["size"]] for c in log.get("created", [])]
    merged = [["、".join(m["clusters"]), names_after.get(m["into"], m["into"]), m["moved"]]
              for m in log.get("merged", [])]
    removed = [[r["text"], names_before.get(r["from"], r["from"]), r.get("reason", "")]
              for r in log.get("removed", [])]
    clusters = [[cid, info.get("name", ""), info.get("size", 0)] for cid, info in after.items()]

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{esc(title)}</title>
<style>
body{{margin:0;background:#f4f7fb;color:#0f172a;font:14px/1.6 -apple-system,"Microsoft YaHei",sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px}}
h1{{font-size:20px;margin:0 0 6px}} h2{{font-size:15px;margin:24px 0 8px}}
.sub{{color:#64748b;font-size:12px;margin-bottom:16px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}
.card{{background:#fff;border:1px solid #dbe3ee;border-radius:10px;padding:12px 16px;min-width:120px}}
.card b{{display:block;font-size:20px}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #dbe3ee;border-radius:8px;overflow:hidden}}
th,td{{padding:7px 10px;border-bottom:1px solid #eef2f7;text-align:left;vertical-align:top}}
th{{background:#f8fafc;color:#475569;font-weight:600;font-size:12px}}
.muted{{color:#94a3b8}}
</style></head><body><main>
<h1>LLM 初审变更</h1>
<div class="sub">{esc(title)} · 共 {len(log.get('moves',[]))} 次移动、{len(log.get('renames',[]))} 次改名、{len(log.get('created',[]))} 个新簇</div>
<div class="cards">
<div class="card"><span>原簇</span><b>{len(before)}</b></div>
<div class="card"><span>新簇</span><b>{len(after)}</b></div>
<div class="card"><span>移动</span><b>{len(log.get('moves',[]))}</b></div>
<div class="card"><span>移除</span><b>{len(log.get('removed',[]))}</b></div>
</div>
<h2>簇改名</h2>{table(["簇", "原名", "新名"], renames)}
<h2>新建簇</h2>{table(["簇", "名称", "成员数"], created)}
<h2>合并</h2>{table(["被合并", "合并到", "移动数"], merged)}
<h2>query 移动</h2>{table(["query", "从", "到"], moves)}
<h2>移除</h2>{table(["query", "原簇", "原因"], removed)}
<h2>最终簇</h2>{table(["簇", "名称", "成员数"], clusters)}
</main></body></html>
"""


def save_outputs(original: dict, clusters: list[dict], removed: list[dict], log: dict,
                 out_dir: Path, title: str = "LLM 初审") -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "meta": {**original.get("meta", {}), "clusters": len(clusters),
                 "llm_attempts": len(log.get("attempts", []))},
        "clusters": clusters,
        "removed": removed,
    }
    (out_dir / "clusters.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "patch.json").write_text(json.dumps(log.get("patch", {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "patch_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "diff.html").write_text(_diff_html(log, title), encoding="utf-8")
    build_canvas(result, out_dir / "review.html", title=title, key=out_dir.name)
    return result
