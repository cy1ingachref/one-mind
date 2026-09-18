"""OneMind daemon — lightweight local server for memory storage."""
from __future__ import annotations

import json
import threading
import http.server
import socketserver
from typing import Any
from pathlib import Path

from .store import MemoryStore, Memory


class MemoryHTTPHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the memory daemon."""

    db_path: str = ""  # Set at server startup

    def _get_store(self) -> MemoryStore:
        """Create a new store for this request (thread-safe)."""
        return MemoryStore(self.db_path)

    def _close_store(self, store: MemoryStore) -> None:
        """Close a store after request handling."""
        store.close()

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status)

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        body = self.rfile.read(length)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        store = self._get_store()
        try:
            if self.path == "/ping":
                self._send_json({"status": "ok"})
            elif self.path == "/stats":
                self._send_json(store.stats())
            elif self.path.startswith("/recall"):
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                query = params.get("q", [""])[0]
                scope = params.get("scope", [None])[0]
                limit = int(params.get("limit", ["10"])[0])
                results = store.recall(query, scope=scope, limit=limit)
                self._send_json([
                    {"id": m.id, "content": m.content, "tags": m.tags, "scope": m.scope, "score": m.score, "updated_at": m.updated_at}
                    for m in results
                ])
            elif self.path == "/memories":
                results = store.recall(limit=100)
                self._send_json([
                    {"id": m.id, "content": m.content, "tags": m.tags, "scope": m.scope, "updated_at": m.updated_at}
                    for m in results
                ])
            else:
                self._send_error("Not found", 404)
        finally:
            store.close()

    def do_POST(self):
        store = self._get_store()
        try:
            body = self._read_body()
            if self.path == "/remember":
                content = body.get("content", "")
                if not content:
                    return self._send_error("content is required", 400)
                memory = Memory(
                    content=content,
                    tags=body.get("tags", []),
                    scope=body.get("scope", "project"),
                    agent_id=body.get("agent_id", "default"),
                    ttl_seconds=body.get("ttl_seconds", 0),
                )
                store.remember(memory)
                self._send_json({"status": "ok", "id": memory.id})
            else:
                self._send_error("Not found", 404)
        finally:
            store.close()

    def do_DELETE(self):
        store = self._get_store()
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if self.path.startswith("/forget"):
                memory_id = params.get("id", [""])[0]
                if not memory_id:
                    return self._send_error("id is required", 400)
                deleted = store.forget(memory_id)
                self._send_json({"status": "ok" if deleted else "not_found"})
            elif self.path.startswith("/clear"):
                scope = params.get("scope", [""])[0]
                if not scope:
                    return self._send_error("scope is required", 400)
                count = store.clear_scope(scope)
                self._send_json({"status": "ok", "deleted": count})
            else:
                self._send_error("Not found", 404)
        finally:
            store.close()


class MemoryDaemon:
    """HTTP daemon for memory storage."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7777, db_path: str | Path = "~/.one_mind/default.db"):
        self.host = host
        self.port = port
        self.db_path = Path(db_path).expanduser()
        self._server: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, blocking: bool = False) -> None:
        """Start the daemon."""
        MemoryHTTPHandler.db_path = str(self.db_path)

        class ReusableTCPServer(socketserver.TCPServer):
            allow_reuse_address = True

        self._server = ReusableTCPServer((self.host, self.port), MemoryHTTPHandler)

        if blocking:
            self._server.serve_forever()
        else:
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the daemon."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    def __enter__(self) -> "MemoryDaemon":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()
