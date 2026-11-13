"""本地单实例复核服务：持有 ReviewState，前端通过 JSON API 操作。"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from ..clustering.pipeline import write_state_file
from ..entities.state import ReviewState, StateError
from ..paths import TEMPLATES_DIR
from ..state_files import HUMAN_STATE
from .actions import ActionError, apply_action, recompute_human_tags
from .diff import diff_states
from .export import export_dict

DEFAULT_TEMPLATE = TEMPLATES_DIR / "review.html"


def make_server(state: ReviewState, state_path: Path | str,
                host: str = "127.0.0.1", port: int = 8765,
                template_path: Path | str | None = None) -> HTTPServer:
    state_file = Path(state_path)
    template = Path(template_path) if template_path else DEFAULT_TEMPLATE

    class Handler(BaseHTTPRequestHandler):
        review_state = state
        baseline = state.clone()
        undo_stack: list[dict] = []
        redo_stack: list[dict] = []
        history_limit = 100

        def _history(self) -> dict:
            return {
                "undo": len(type(self).undo_stack) > 0,
                "redo": len(type(self).redo_stack) > 0,
                "undo_count": len(type(self).undo_stack),
                "redo_count": len(type(self).redo_stack),
            }

        def _commit(self, next_state: ReviewState) -> None:
            recompute_human_tags(next_state, type(self).baseline)
            previous = type(self).review_state
            type(self).review_state = next_state
            try:
                self._persist()
            except OSError:
                type(self).review_state = previous
                raise
            type(self).undo_stack.append(previous.to_dict())
            if len(type(self).undo_stack) > type(self).history_limit:
                type(self).undo_stack.pop(0)
            type(self).redo_stack.clear()

        def _undo(self) -> ReviewState:
            if not type(self).undo_stack:
                raise ActionError("没有可撤销的操作")
            previous = type(self).review_state
            snapshot = type(self).undo_stack.pop()
            try:
                restored = ReviewState.from_dict(snapshot)
                recompute_human_tags(restored, type(self).baseline)
                type(self).review_state = restored
                self._persist()
            except (OSError, StateError):
                type(self).review_state = previous
                type(self).undo_stack.append(snapshot)
                raise
            type(self).redo_stack.append(previous.to_dict())
            return restored

        def _redo(self) -> ReviewState:
            if not type(self).redo_stack:
                raise ActionError("没有可重做的操作")
            previous = type(self).review_state
            snapshot = type(self).redo_stack.pop()
            try:
                restored = ReviewState.from_dict(snapshot)
                recompute_human_tags(restored, type(self).baseline)
                type(self).review_state = restored
                self._persist()
            except (OSError, StateError):
                type(self).review_state = previous
                type(self).redo_stack.append(snapshot)
                raise
            type(self).undo_stack.append(previous.to_dict())
            if len(type(self).undo_stack) > type(self).history_limit:
                type(self).undo_stack.pop(0)
            return restored

        def _json(self, payload: object, status: int = 200, extra: dict | None = None) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _error(self, message: str, status: int = 400) -> None:
            self._json({"error": message}, status)

        def _read_json(self) -> object:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ActionError("Content-Length 非法") from exc
            if length <= 0 or length > 2_000_000:
                raise ActionError("请求体为空或过大")
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ActionError("请求体不是合法 JSON") from exc

        def _persist(self) -> None:
            write_state_file(type(self).review_state, state_file)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/state":
                self._json(type(self).review_state.to_dict())
                return
            if path == "/api/health":
                self._json({"ok": True})
                return
            if path == "/api/history":
                self._json(self._history())
                return
            if path == "/api/export":
                payload = export_dict(type(self).review_state)
                self._json(payload, extra={
                    "Content-Disposition": f'attachment; filename="{HUMAN_STATE}"',
                })
                return
            if path in {"/", "/index.html"}:
                if not template.exists():
                    self._error(f"模板不存在：{template}", 500)
                    return
                body = template.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._error("not found", 404)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == "/api/undo":
                    self._json(self._undo().to_dict())
                    return
                if path == "/api/redo":
                    self._json(self._redo().to_dict())
                    return
                payload = self._read_json()
                if path == "/api/action":
                    if not isinstance(payload, dict):
                        raise ActionError("action 必须是对象")
                    next_state = apply_action(type(self).review_state, payload)
                    self._commit(next_state)
                    self._json(next_state.to_dict())
                    return
                if path == "/api/load":
                    if not isinstance(payload, dict):
                        raise ActionError("state 必须是对象")
                    next_state = ReviewState.from_dict(payload)
                    type(self).baseline = next_state.clone()
                    self._commit(next_state)
                    self._json(next_state.to_dict())
                    return
                if path == "/api/diff":
                    if not isinstance(payload, dict):
                        raise ActionError("diff 请求必须是对象")
                    base = ReviewState.from_dict(payload.get("base"))
                    target = ReviewState.from_dict(payload.get("target"))
                    self._json(diff_states(base, target))
                    return
                self._error("not found", 404)
            except (ActionError, StateError, ValueError) as exc:
                self._error(str(exc))
            except OSError as exc:
                self._error(f"写入失败：{exc}", 500)

        def log_message(self, fmt: str, *args) -> None:
            print(f"[review] {self.address_string()} {fmt % args}")

    return HTTPServer((host, port), Handler)


def serve(state_path: Path | str, host: str = "127.0.0.1", port: int = 8765,
          template_path: Path | str | None = None) -> int:
    state_file = Path(state_path)
    state = ReviewState.from_dict(json.loads(state_file.read_text(encoding="utf-8")))
    server = make_server(state, state_file, host, port, template_path)
    actual_host, actual_port = server.server_address[:2]
    print(f"复核服务：http://{actual_host}:{actual_port}/")
    print(f"状态文件：{state_file}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
    return 0
