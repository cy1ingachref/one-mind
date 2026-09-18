# AgentMemory

**Shared memory layer for AI agents. Remember across sessions, across tools, across time.**

[![Tests](https://img.shields.io/badge/tests-15%20passed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

---

## The Problem

Every AI agent is an island. Session ends, context is gone. Two agents on the same project? Neither knows what the other learned. Your agent forgets what it did yesterday.

AgentMemory solves this with a shared memory layer that any agent can plug into.

---

## Quick Start

```bash
# Install
pip install agentmemory

# Store a fact
agentmemory remember "Auth uses JWT with RS256" -t security -t auth

# Recall it later
agentmemory recall "authentication"

# Or use the Python SDK
```

```python
from agentmemory import remember, recall

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
│           AgentMemory Daemon            │
│         (SQLite + HTTP API)             │
│                                         │
│  remember() → Store fact                │
│  recall()   → Search facts              │
│  forget()   → Delete fact               │
└─────────────────────────────────────────┘
```

---

## Features

- **Shared** — Multiple agents, one memory pool
- **Persistent** — SQLite-backed, survives restarts
- **Scoped** — Isolate by project, user, agent, or global
- **Taggable** — Categorize facts for easy retrieval
- **TTL** — Auto-expire stale memories
- **Daemon** — Run as a local server for any tool to use
- **MCP** — Built-in MCP server for Claude Code/Cursor integration
- **Zero deps** — No vector DB, no API keys, no cloud

---

## CLI

```bash
# Store
agentmemory remember "Database uses PostgreSQL" -t database -t infra

# Search
agentmemory recall "database"

# Filter by scope
agentmemory recall -s project/myapp

# Delete
agentmemory forget abc123def456

# Stats
agentmemory stats

# Start daemon
agentmemory serve

# List all
agentmemory list
```

---

## Python SDK

```python
from agentmemory import AgentMemory

mem = AgentMemory()

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
python -m agentmemory.mcp
```

Then add to your MCP config:

```json
{
  "mcpServers": {
    "agentmemory": {
      "command": "python",
      "args": ["-m", "agentmemory.mcp"]
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
agentmemory/
├── __init__.py        # Public API exports
├── store.py           # SQLite storage + search
├── sdk.py             # Python client (daemon + direct)
├── daemon.py          # HTTP server
├── cli.py             # Click CLI
└── mcp/
    └── server.py      # MCP server for Claude Code/Cursor
```

---

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

---

## License

MIT
