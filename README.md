# OneMind

**Shared memory layer for AI agents. Remember across sessions, across tools, across time.**

[![Tests](https://img.shields.io/badge/tests-19%20passed-brightgreen)](https://github.com/cy1ingachref/one-mind)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/cy1ingachref/one-mind/blob/main/LICENSE)

---

## The Problem

Every AI agent is an island. Session ends, context is gone. Two agents on the same project? Neither knows what the other learned.

OneMind solves this: a shared memory pool that any agent can read from or write to — via Python SDK, CLI, or MCP.

---

## Quick Start

```bash
pip install onemind

# Store a fact
onemind remember "Auth uses JWT with RS256" -t security -t auth

# Recall it later (hours later, different session, different tool)
onemind recall "authentication"

# Or use the Python SDK
```

```python
from onemind import remember, recall

remember("Auth uses JWT with RS256", tags=["security", "auth"], scope="project/myapp")
# ... hours later, different session, different tool
results = recall("authentication")
print(results[0].content)  # "Auth uses JWT with RS256"
```

---

## How It Works

```
┌─────────────────┐     ┌─────────────────┐
│   Agent A       │     │   Agent B       │
│  (Claude Code)  │     │  (Cursor)       │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────────────────────────────┐
│           OneMind Daemon                │
│         (SQLite + HTTP API)             │
│                                         │
│  remember() → Store fact                │
│  recall()   → Search facts              │
│  forget()   → Delete fact               │
└─────────────────────────────────────────┘
```

The SDK auto-detects a running daemon. If none is running, it silently falls back to direct SQLite access. No hard failures.

---

## Features

- **Shared** — Multiple agents, one memory pool
- **Persistent** — SQLite-backed, survives restarts
- **Scoped** — Isolate by project, user, agent, or global
- **Taggable** — Categorize facts for easy retrieval
- **TTL** — Auto-expire stale memories
- **Daemon** — Run as a local server (127.0.0.1 only, no auth) for any tool to use
- **MCP** — Built-in MCP server for Claude Code/Cursor integration
- **Zero deps** — No vector DB, no API keys, no cloud

> **Security note:** The daemon binds to 127.0.0.1 by default. Do not expose it to the network without adding authentication.

---

## CLI

```bash
# Store
onemind remember "Database uses PostgreSQL" -t database -t infra

# Search
onemind recall "database"

# Filter by scope
onemind recall -s project/myapp

# Delete
onemind forget abc123def456

# Stats
onemind stats

# Start daemon
onemind serve

# List all
onemind list
```

---

## Python SDK

```python
from onemind import OneMind

mem = OneMind()

# Remember
mem.remember("Auth uses JWT with RS256", tags=["security", "auth"], scope="project/myapp")

# Recall
results = mem.recall("authentication", limit=5)
for m in results:
    print(f"[{m.score:.1f}] {m.content}")

# Forget
mem.forget(memory_id)

# Stats
print(mem.stats())
```

---

## MCP Server (Claude Code / Cursor)

```bash
# Run MCP server on stdio
python -m onemind.mcp
```

Then add to your MCP config (e.g., `~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "onemind": {
      "command": "python",
      "args": ["-m", "onemind.mcp"]
    }
  }
}
```

Then add to your MCP config (e.g., `~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "onemind": {
      "command": "python",
      "args": ["-m", "onemind.mcp"]
    }
  }
}
```

Tools exposed:
- `remember` — Store a fact
- `recall` — Search memories
- `forget` — Delete by id
- `stats` — Get statistics

---

## Architecture

```
onemind/
├── __init__.py        # Public API exports
├── store.py           # SQLite storage + search
├── sdk.py             # Python client (daemon + direct)
├── daemon.py          # HTTP server
├── cli.py             # Click CLI
└── mcp/
    └── server.py      # MCP server for Claude Code/Cursor
```

---

## Known Limitations

- **Single-threaded daemon**: The daemon processes one request at a time. Suitable for localhost use with few agents, but not for concurrent multi-agent production workloads.
- **No daemon authentication**: Binds to 127.0.0.1 with no auth token. Do not expose to the network.
- **Recall quality**: Uses word-overlap scoring (not embeddings). Good enough for factual lookup, not for semantic search at scale.

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

---

## License

MIT — see [LICENSE](LICENSE) for details.
