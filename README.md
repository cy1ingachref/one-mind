# OneMind

**Shared memory layer for AI agents. Remember across sessions, across tools, across time.**

[![Tests](https://img.shields.io/badge/tests-40%20passed-brightgreen)](https://github.com/cy1ingachref/one-mind)
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

# Recall it later (search by keyword or tag)
onemind recall "JWT"

# Or use the Python SDK
```

```python
from onemind import remember, recall

remember("Auth uses JWT with RS256", tags=["security", "auth"], scope="project/myapp")
# ... hours later, different session, different tool
results = recall("JWT")  # keyword search (substring match)
if results:
    print(f"[{results[0].score:.1f}] {results[0].content}")
else:
    print("No matching memories found")
```

> **Note:** Search is **substring + word-overlap matching** (not semantic/embedding). Use keywords that appear in the stored content or tags for best results. For semantic search, consider embedding-based alternatives like ChromaDB or Pinecone.

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

- **Shared** — Multiple agents, one memory pool (threaded daemon for concurrent access)
- **Persistent** — SQLite-backed, survives restarts
- **Scoped** — Isolate by project, user, agent, or global
- **Taggable** — Categorize facts for easy retrieval
- **TTL** — Auto-expire stale memories, with manual GC
- **Provenance** — Track who wrote what (agent_id) and query by source
- **BM25 retrieval** — Smarter than simple substring matching
- **Daemon** — Threaded local server (127.0.0.1 only, no auth) for any tool to use
- **MCP** — Built-in MCP server for Claude Code/Cursor integration
- **Zero deps** — No vector DB, no API keys, no cloud

> **Security note:** The daemon binds to 127.0.0.1 by default. Do not expose it to the network without adding authentication.

---

## CLI

```bash
# Store
onemind remember "Database uses PostgreSQL" -t database -t infra

# Search (substring matching)
onemind recall "database"

# Filter by scope
onemind recall -s project/myapp

# Delete
onemind forget abc123def456

# Stats
onemind stats

# Start daemon (single-threaded, localhost only)
onemind serve

# List all
onemind list
```

> **CLI mode:** Commands use the daemon if running, otherwise fall back to direct SQLite access. Set `ONEMIND_DB` to specify the database path.

---

## Python SDK

```python
from onemind import OneMind

mem = OneMind()

# Remember
mem.remember("Auth uses JWT with RS256", tags=["security", "auth"], scope="project/myapp")

# Recall (substring matching)
results = mem.recall("JWT", limit=5)
if results:
    for m in results:
        print(f"[{m.score:.1f}] {m.content}")
else:
    print("No matching memories found")

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

Add to your MCP config (e.g., `~/.claude/settings.json`):

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

## Garbage Collection

OneMind automatically filters expired memories from recall results. To permanently remove them:

```bash
# Via SDK
from onemind import OneMind
mem = OneMind()
removed = mem.gc()
print(f"Removed {removed} expired memories")

# Via HTTP daemon
curl -X POST http://127.0.0.1:7777/gc
```

---

- **No daemon authentication**: Binds to 127.0.0.1 with no auth token. Do not expose to the network.
- **Recall quality**: Uses BM25 scoring (not embeddings). Good enough for factual lookup, not for semantic search at scale.
- **Threaded but not async**: The daemon handles requests in threads but doesn't use async I/O. Sufficient for local multi-agent use, but not optimized for hundreds of concurrent agents.

---

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

---

## License

MIT — see [LICENSE](LICENSE) for details.
