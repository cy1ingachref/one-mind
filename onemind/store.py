"""Onemind core — memory storage, retrieval, and lifecycle."""
from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ─── Data model ──────────────────────────────────────────────────────────────

@dataclass
class Memory:
    """A single remembered fact."""
    id: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    scope: str = "project"
    agent_id: str = "default"
    created_at: float = 0.0
    updated_at: float = 0.0
    ttl_seconds: float = 0.0  # 0 = never expires
    score: float = 0.0  # retrieval score (set during recall)

    def __post_init__(self):
        if not self.id:
            self.id = self._make_id()
        if not self.created_at:
            self.created_at = time.time()
        if not self.updated_at:
            self.updated_at = self.created_at

    def _make_id(self) -> str:
        # UUID ensures no silent overwrites when same content is stored
        # in different scopes or with different tags
        return str(uuid.uuid4())[:16]

    @property
    def is_expired(self) -> bool:
        if self.ttl_seconds <= 0:
            return False
        return (time.time() - self.updated_at) > self.ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tags"] = ",".join(self.tags)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Memory":
        if isinstance(d.get("tags"), str):
            d["tags"] = [t.strip() for t in d["tags"].split(",") if t.strip()]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─── Store ───────────────────────────────────────────────────────────────────

class MemoryStore:
    """SQLite-backed memory store with semantic search."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                tags TEXT DEFAULT '',
                scope TEXT DEFAULT 'project',
                agent_id TEXT DEFAULT 'default',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                ttl_seconds REAL DEFAULT 0
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at)
        """)
        self._conn.commit()

    def remember(self, memory: Memory) -> Memory:
        """Store a new memory or update existing one (matched by id)."""
        memory.updated_at = time.time()
        self._conn.execute("""
            INSERT OR REPLACE INTO memories
                (id, content, tags, scope, agent_id, created_at, updated_at, ttl_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            memory.id,
            memory.content,
            ",".join(memory.tags),
            memory.scope,
            memory.agent_id,
            memory.created_at,
            memory.updated_at,
            memory.ttl_seconds,
        ))
        self._conn.commit()
        return memory

    def recall(
        self,
        query: str = "",
        *,
        scope: str | None = None,
        agent_id: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        include_expired: bool = False,
    ) -> list[Memory]:
        """Search memories with optional filtering."""
        # Build query dynamically
        conditions = []
        params: list[Any] = []

        if scope:
            conditions.append("scope = ?")
            params.append(scope)
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if tags:
            for tag in tags:
                conditions.append("tags LIKE ?")
                params.append(f"%{tag}%")
        if query:
            conditions.append("(content LIKE ? OR tags LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])

        sql = "SELECT * FROM memories"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        memories = [Memory.from_dict(dict(row)) for row in rows]

        # Filter expired memories in Python (consistent with time.time())
        if not include_expired:
            memories = [m for m in memories if not m.is_expired]

        # Simple relevance scoring (exact match > substring > tag match)
        for mem in memories:
            mem.score = self._score_memory(mem, query)

        # Re-sort by score
        memories.sort(key=lambda m: m.score, reverse=True)
        return memories

    def _score_memory(self, mem: Memory, query: str) -> float:
        """Score relevance (higher = more relevant)."""
        if not query:
            return 1.0
        q = query.lower()
        c = mem.content.lower()

        if q == c:
            return 3.0
        if q in c:
            return 2.0
        # Partial word overlap
        q_words = set(q.split())
        c_words = set(c.split())
        overlap = len(q_words & c_words)
        if overlap > 0:
            return 1.0 + (overlap / len(q_words))
        return 0.5

    def forget(self, memory_id: str) -> bool:
        """Delete a memory by id. Returns True if found and deleted."""
        cursor = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def clear_scope(self, scope: str) -> int:
        """Delete all memories in a scope. Returns count deleted."""
        cursor = self._conn.execute("DELETE FROM memories WHERE scope = ?", (scope,))
        self._conn.commit()
        return cursor.rowcount

    def count(self, scope: str | None = None) -> int:
        """Count memories, optionally filtered by scope."""
        sql = "SELECT COUNT(*) FROM memories"
        params: list[Any] = []
        if scope:
            sql += " WHERE scope = ?"
            params.append(scope)
        row = self._conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    def stats(self) -> dict[str, Any]:
        """Get store statistics."""
        total = self.count()
        scopes = {}
        for row in self._conn.execute("SELECT scope, COUNT(*) FROM memories GROUP BY scope"):
            scopes[row[0]] = row[1]
        return {"total": total, "scopes": scopes}

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
