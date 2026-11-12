"""Prompt 读取、占位替换与消息组装。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..entities.state import ReviewState

DEFAULT_PROMPT_DIR = Path(__file__).resolve().parents[3] / "prompts"
PLACEHOLDER = re.compile(r"\{\{[A-Z0-9_]+\}\}")


def load_prompt(name: str, prompt_dir: Path | str | None = None) -> str:
    directory = Path(prompt_dir) if prompt_dir else DEFAULT_PROMPT_DIR
    path = directory / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt 不存在：{path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, prompt_dir: Path | str | None = None, **values) -> str:
    text = load_prompt(name, prompt_dir)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    leftover = sorted(set(PLACEHOLDER.findall(text)))
    if leftover:
        raise ValueError(f"prompt {name} 还有未填充占位：{leftover}")
    return text


def state_json(state: ReviewState) -> str:
    return json.dumps(state.to_dict(), ensure_ascii=False, indent=2)


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def cluster_table(state: ReviewState) -> str:
    lines = ["| cluster_id | 名称 | 成员 |", "|---|---|---|"]
    for cluster in state.clusters.values():
        texts = "、".join(_cell(state.queries[qid].text) for qid in cluster.members)
        lines.append(f"| {_cell(cluster.cluster_id)} | {_cell(cluster.name)} | {texts} |")
    return "\n".join(lines)


def build_patch_messages(state: ReviewState, instructions: str,
                         prompt_dir: Path | str | None = None) -> list[dict]:
    content = render_prompt(
        "cluster_patch",
        prompt_dir=prompt_dir,
        STATE_JSON=state_json(state),
        INSTRUCTIONS=instructions,
    )
    return [{"role": "system", "content": content}]


def build_naming_messages(state: ReviewState, prompt_dir: Path | str | None = None) -> list[dict]:
    content = render_prompt(
        "cluster_naming",
        prompt_dir=prompt_dir,
        CLUSTERS=cluster_table(state),
    )
    return [{"role": "system", "content": content}]
