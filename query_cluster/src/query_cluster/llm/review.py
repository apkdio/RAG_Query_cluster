"""LLM 两阶段复核：归类 patch，然后命名。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..clustering.pipeline import write_state_file
from ..entities.events import new_event
from ..entities.state import ReviewState
from ..state_files import LLM_STATE
from .patch import PatchError, apply_patch
from .prompts import build_naming_messages, build_patch_messages

DEFAULT_INSTRUCTIONS = "请修正明显放错的 query；必要时新建簇、放入待定或不可聚类。没有把握时不要改。"


class LLMReviewError(RuntimeError):
    def __init__(self, message: str, attempts: list[dict]):
        super().__init__(message)
        self.attempts = attempts


@dataclass
class ReviewResult:
    state: ReviewState
    patch: dict
    log: dict
    naming: dict | None
    naming_attempts: list[dict]
    naming_failed: bool


def _parse_json(text: str) -> dict:
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
        payload = json.loads(value[start:end + 1])
    except json.JSONDecodeError as exc:
        raise PatchError(f"JSON 解析失败：{exc}") from exc
    if not isinstance(payload, dict):
        raise PatchError("输出必须是 JSON 对象")
    return payload


def _validate_names(payload: dict, state: ReviewState) -> dict[str, str]:
    renames = payload.get("renames")
    if not isinstance(renames, list) or not renames:
        raise PatchError("命名结果必须包含非空 renames 数组")
    names: dict[str, str] = {}
    for item in renames:
        if not isinstance(item, dict):
            raise PatchError("renames 的每一项都必须是对象")
        cluster_id = item.get("cluster_id")
        name = item.get("name")
        if cluster_id not in state.clusters:
            raise PatchError(f"命名引用了未知 cluster_id {cluster_id}")
        if cluster_id in names:
            raise PatchError(f"cluster_id {cluster_id} 被重复命名")
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 12:
            raise PatchError(f"{cluster_id} 的名称必须是 2–12 个字符")
        names[cluster_id] = name.strip()
    missing = sorted(set(state.clusters) - set(names))
    if missing:
        raise PatchError(f"以下簇没有命名：{missing}")
    return names


def _name_state(state: ReviewState, chat, max_attempts: int,
                prompt_dir: Path | str | None) -> tuple[ReviewState, dict | None, list[dict], bool]:
    messages = build_naming_messages(state, prompt_dir)
    attempts: list[dict] = []
    for attempt in range(1, max_attempts + 1):
        content = chat(messages)
        try:
            payload = _parse_json(content)
            names = _validate_names(payload, state)
            named = state.clone()
            for cluster_id, name in names.items():
                named.clusters[cluster_id].name = name
            named.events.append(new_event("llm_naming", count=len(names)))
            return named, payload, attempts + [{"attempt": attempt, "ok": True}], False
        except PatchError as exc:
            attempts.append({"attempt": attempt, "ok": False, "error": str(exc), "output": content})
            if attempt == max_attempts:
                break
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"上一次命名无法应用：{exc}\n请只返回修正后的完整 JSON，不要解释。"})
    return state, None, attempts, True


def review_state(state: ReviewState, instructions: str, chat, max_attempts: int = 3,
                  prompt_dir: Path | str | None = None) -> ReviewResult:
    messages = build_patch_messages(state, instructions, prompt_dir)
    attempts: list[dict] = []
    patch: dict | None = None
    applied: ReviewState | None = None
    log: dict = {}
    for attempt in range(1, max_attempts + 1):
        content = chat(messages)
        try:
            patch = _parse_json(content)
            applied, log = apply_patch(state, patch)
            attempts.append({"attempt": attempt, "ok": True})
            break
        except PatchError as exc:
            attempts.append({"attempt": attempt, "ok": False, "error": str(exc), "output": content})
            if attempt == max_attempts:
                raise LLMReviewError(f"连续 {max_attempts} 次输出未通过校验", attempts) from exc
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"上一次输出无法应用：{exc}\n请只返回修正后的完整 JSON patch，不要解释。"})

    assert applied is not None and patch is not None
    applied.meta["stage"] = "llm"
    applied.events.append(new_event("llm_patch", operations=patch.get("operations", [])))
    log["patch"] = patch
    log["attempts"] = attempts

    if not applied.clusters:
        return ReviewResult(applied, patch, log, None, [], False)

    named, naming_payload, naming_attempts, naming_failed = _name_state(
        applied, chat, max_attempts, prompt_dir,
    )
    if naming_failed:
        named.meta["naming_failed"] = True
    log["naming"] = {
        "payload": naming_payload,
        "attempts": naming_attempts,
        "failed": naming_failed,
    }
    return ReviewResult(named, patch, log, naming_payload, naming_attempts, naming_failed)


def save_result(result: ReviewResult, out_dir: Path | str) -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    state_path = write_state_file(result.state, out_path / LLM_STATE)
    (out_path / "patch.json").write_text(
        json.dumps(result.patch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_path / "patch_log.json").write_text(
        json.dumps(result.log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result.naming is not None:
        (out_path / "naming.json").write_text(
            json.dumps(result.naming, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result.naming_failed:
        (out_path / "llm_failure.json").write_text(
            json.dumps({"stage": "naming", "attempts": result.naming_attempts},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return state_path
