"""事件记录。"""

from __future__ import annotations

from datetime import datetime, timezone


def new_event(kind: str, **payload) -> dict:
    """生成一条可序列化事件；payload 由调用方决定。"""
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("事件类型不能为空")
    if "type" in payload or "at" in payload:
        raise ValueError("payload 不能覆盖 type / at")
    event = {
        "type": kind.strip(),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    event.update(payload)
    return event
