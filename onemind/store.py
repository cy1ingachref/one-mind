"""OneMind core — memory storage, retrieval, and lifecycle."""
from __future__ import annotations

import sqlite3
import time
import uuid
import re
import math
from typing import Any
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ─── Data model ──────────────────────────────────────────────────────────────

@dataclass
class Memory:
    """A single remembered fact with provenance."""
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


# ─── Tokenizer ───────────────────────────────────────────────────────────────

def tokenize(text: str) -> list[str]:
    """Simple tokenizer: lowercase, split on non-alphanumeric."""
    return re.findall(r'[a-z0-9]+', text.lower())


# ─── Store ───────────────────────────────────────────────────────────────────

class MemoryStore:
    """SQLite-backed memory store with BM25 retrieval and provenance."""

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
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_agent ON memories(agent_id)
        """)
        self._conn.commit()

    def remember(self, memory: Memory) -> Memory:
        """Store a new memory or update existing one (matched by id).
        
        Raises:
            ValueError: If content is empty
        """
        if not memory.content or not memory.content.strip():
            raise ValueError("content cannot be empty")
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
        """Search memories with BM25 scoring and optional filtering."""
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
            # Substring matching in SQL (broad recall, then score in Python)
            conditions.append("(content LIKE ? OR tags LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])

        sql = "SELECT * FROM memories"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(limit * 3, 50))  # Fetch more for scoring

        rows = self._conn.execute(sql, params).fetchall()
        memories = [Memory.from_dict(dict(row)) for row in rows]

        # Filter expired memories in Python (consistent with time.time())
        if not include_expired:
            memories = [m for m in memories if not m.is_expired]

        # Score using BM25 if query provided
        if query:
            for mem in memories:
                mem.score = self._bm25_score(mem, query)
            # Re-sort by score
            memories.sort(key=lambda m: m.score, reverse=True)

        # Apply limit
        return memories[:limit]

    def _bm25_score(self, mem: Memory, query: str) -> float:
        """
        BM25-inspired scoring for a memory against a query.
        
        This is a simplified BM25 implementation that doesn't require
        pre-computed IDF statistics across the corpus. It uses:
        - Term frequency (TF) with length normalization
        - Exact substring match bonus
        - Tag match bonus
        """
        q_tokens = tokenize(query)
        c_tokens = tokenize(mem.content)
        t_tokens = tokenize(" ".join(mem.tags))
        
        if not q_tokens:
            return 1.0
        
        # Exact substring match bonus
        q_lower = query.lower()
        c_lower = mem.content.lower()
        if q_lower == c_lower:
            return 10.0
        if q_lower in c_lower:
            return 5.0
        
        # TF-based scoring
        c_counter = Counter(c_tokens)
        t_counter = Counter(t_tokens)
        c_len = len(c_tokens) if c_tokens else 1
        
        # BM25 parameters
        k1 = 1.5
        b = 0.75
        avg_len = 10  # Assumed average document length
        
        score = 0.0
        for token in q_tokens:
            # Content TF
            tf = c_counter.get(token, 0)
            if tf > 0:
                # BM25 TF component with length normalization
                tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (c_len / avg_len)))
                score += tf_norm
            
            # Tag TF (boosted)
            tag_tf = t_counter.get(token, 0)
            if tag_tf > 0:
                score += tag_tf * 2.0  # Tag matches weighted higher
        
        return score

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
        agents = {}
        for row in self._conn.execute("SELECT scope, COUNT(*) FROM memories GROUP BY scope"):
            scopes[row[0]] = row[1]
        for row in self._conn.execute("SELECT agent_id, COUNT(*) FROM memories GROUP BY agent_id"):
            agents[row[0]] = row[1]
        return {"total": total, "scopes": scopes, "agents": agents}

    def gc(self) -> int:
        """Garbage collect: remove all expired memories. Returns count removed."""
        now = time.time()
        cursor = self._conn.execute(
            "DELETE FROM memories WHERE ttl_seconds > 0 AND (?) - updated_at > ttl_seconds",
            (now,)
        )
        self._conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
