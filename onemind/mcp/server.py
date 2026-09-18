"""OneMind MCP server — expose memory to Claude Code, Cursor, and any MCP-compatible tool."""
from __future__ import annotations

import sys
import json
import traceback
from typing import Any

from onemind.sdk import OneMind


def main():
    """Run the MCP server on stdio."""
    mem = OneMind()

    # Read JSON-RPC messages from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        params = msg.get("params", {})
        msg_id = msg.get("id")

        try:
            # Handle initialize handshake (required by MCP spec)
            # Echo the client's requested protocol version for compatibility
            if method == "initialize":
                client_version = params.get("protocolVersion", "2024-11-05")
                result = {
                    "protocolVersion": client_version,
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "onemind",
                        "version": "0.3.0"
                    }
                }
                _send_response(msg_id, result)

            elif method == "notifications/initialized":
                pass  # No response needed for notifications

            elif method == "ping":
                _send_response(msg_id, {})

            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "remember",
                            "description": "Store a fact in shared memory for other agents to recall later",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "content": {"type": "string", "description": "The fact to remember"},
                                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for categorization"},
                                    "scope": {"type": "string", "description": "Memory scope (default: project)"},
                                },
                                "required": ["content"],
                            },
                        },
                        {
                            "name": "recall",
                            "description": "Search memories by query, tags, or scope",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "Search query"},
                                    "scope": {"type": "string", "description": "Filter by scope"},
                                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Filter by tags"},
                                    "limit": {"type": "number", "description": "Max results (default: 10)"},
                                },
                            },
                        },
                        {
                            "name": "forget",
                            "description": "Delete a memory by id",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string", "description": "Memory id to delete"},
                                },
                                "required": ["id"],
                            },
                        },
                        {
                            "name": "stats",
                            "description": "Get memory statistics",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                    ]
                }
                _send_response(msg_id, result)

            elif method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})

                if tool_name == "remember":
                    content = arguments.get("content", "")
                    tags = arguments.get("tags", [])
                    scope = arguments.get("scope", "project")
                    memory = mem.remember(content, tags=tags, scope=scope)
                    _send_response(msg_id, {"content": [{"type": "text", "text": f"Remembered: {memory.id}"}]}, error=False)

                elif tool_name == "recall":
                    query = arguments.get("query", "")
                    scope = arguments.get("scope")
                    tags = arguments.get("tags")
                    limit = arguments.get("limit", 10)
                    results = mem.recall(query, scope=scope, tags=tags, limit=limit)
                    text = "\n".join(f"[{m.score:.1f}] {m.content}" for m in results)
                    _send_response(msg_id, {"content": [{"type": "text", "text": text or "No memories found."}]}, error=False)

                elif tool_name == "forget":
                    memory_id = arguments.get("id", "")
                    deleted = mem.forget(memory_id)
                    _send_response(msg_id, {"content": [{"type": "text", "text": f"Deleted: {deleted}"}]}, error=False)

                elif tool_name == "stats":
                    data = mem.stats()
                    _send_response(msg_id, {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}, error=False)

                else:
                    _send_response(msg_id, None, error={"code": -32601, "message": f"Unknown tool: {tool_name}"})

            else:
                _send_response(msg_id, None, error={"code": -32601, "message": f"Unknown method: {method}"})

        except Exception as e:
            # Catch all errors and return JSON-RPC error (don't crash the server loop)
            error_msg = f"{type(e).__name__}: {e}"
            _send_response(msg_id, None, error={"code": -32603, "message": error_msg})


def _send_response(msg_id: Any, result: dict | None, error: dict | None = None) -> None:
    """Send JSON-RPC response."""
    response: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id}
    if error:
        response["error"] = error
    else:
        response["result"] = result
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
