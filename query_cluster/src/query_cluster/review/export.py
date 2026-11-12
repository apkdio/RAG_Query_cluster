"""人工复核结果导出：只保留最终状态，不带 LLM patch / diff / 事件。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..entities.state import ReviewState


def export_dict(state: ReviewState) -> dict:
    exported = state.clone()
    exported.meta = {
        "stage": "human",
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "source": "human_review",
    }
    exported.events = []
    return exported.to_dict()


def export_file(state: ReviewState, path: Path | str) -> Path:
    import json

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(export_dict(state), ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(target)
    return target
