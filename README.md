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

# Recall it later (BM25-ranked search)
onemind recall "JWT"
```

```python
from onemind import remember, recall

remember("Auth uses JWT with RS256", tags=["security", "auth"], scope="project/myapp")
# ... hours later, different session, different tool
results = recall("JWT")  # BM25-ranked retrieval
if results:
    print(f"[{results[0].score:.1f}] {results[0].content}")
else:
    print("No matching memories found")
```

> **How search works:** OneMind uses **BM25 retrieval** — a ranked scoring model that weighs term frequency, document length, and tag matches. This is smarter than simple substring matching: longer memories don't drown out shorter ones, and tag matches get a boost. For full semantic/embedding search, consider ChromaDB or Pinecone as alternatives.

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
│  recall()   → BM25-ranked search        │
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
- **BM25 retrieval** — Ranked scoring (TF + length normalization + tag boost), not just substring matching
- **Daemon** — Threaded local server (127.0.0.1 only, no auth) for any tool to use
- **MCP** — Built-in MCP server for Claude Code/Cursor integration
- **Zero deps** — No vector DB, no API keys, no cloud

> **Security note:** The daemon binds to 127.0.0.1 by default. Do not expose it to the network without adding authentication.

---

## CLI

```bash
# Store
onemind remember "Database uses PostgreSQL" -t database -t infra

# Search (BM25-ranked)
onemind recall "database"

# Filter by scope
onemind recall -s project/myapp
```
