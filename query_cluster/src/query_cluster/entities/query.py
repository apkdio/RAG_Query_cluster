"""Query 实体与 QID 规则。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

QID_PATTERN = re.compile(r"^Q\d{4,}$")


@dataclass(frozen=True)
class Query:
    """一个去重后的 query；qid 是跨阶段稳定的身份。"""

    qid: str
    text: str

    def validate(self) -> None:
        if not isinstance(self.qid, str) or not QID_PATTERN.fullmatch(self.qid):
            raise ValueError(f"QID 格式非法：{self.qid!r}，应为 Q0001 形式")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError(f"{self.qid} 的 text 不能为空")

    def to_dict(self) -> dict:
        self.validate()
        return {"text": self.text}

    @classmethod
    def from_dict(cls, qid: str, payload: dict) -> "Query":
        if not isinstance(payload, dict):
            raise ValueError(f"{qid} 的 payload 必须是对象")
        query = cls(qid=qid, text=payload.get("text", ""))
        query.validate()
        return query


def format_qid(number: int) -> str:
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ValueError("QID 编号必须是正整数")
    return f"Q{number:04d}"


def next_qid(existing: Iterable[str]) -> str:
    """按已有 QID 的最大编号生成下一个，保证不回收旧身份。"""
    largest = 0
    for qid in existing:
        if not isinstance(qid, str) or not QID_PATTERN.fullmatch(qid):
            raise ValueError(f"已有 QID 格式非法：{qid!r}")
        largest = max(largest, int(qid[1:]))
    return format_qid(largest + 1)
