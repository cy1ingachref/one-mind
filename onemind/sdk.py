"""Onemind SDK — Python client for the memory daemon."""
from __future__ import annotations

import os
from typing import Any
from pathlib import Path

import requests

from .store import Memory, MemoryStore

# Default daemon connection
DEFAULT_HOST = os.environ.get("ONEMIND_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("ONEMIND_PORT", "7777"))
DEFAULT_DB = os.environ.get("ONEMIND_DB", "~/.onemind/default.db")


class Onemind:
    """Main SDK class for interacting with Onemind.

    Usage:
        from onemind import Onemind

        mem = Onemind()
        mem.remember("Auth uses JWT with RS256", tags=["security", "auth"])
        results = mem.recall("authentication strategy")
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        db_path: str | Path | None = None,
    ):
        self.host = host or DEFAULT_HOST
        self.port = port or DEFAULT_PORT
        self.base_url = f"http://{self.host}:{self.port}"
        self.db_path = Path(db_path or DEFAULT_DB).expanduser()

        # Try daemon first, fall back to direct store
        self._use_daemon = self._check_daemon()
        if not self._use_daemon:
            self._store = MemoryStore(self.db_path)

    def _check_daemon(self) -> bool:
        """Check if the daemon is running."""
        try:
            resp = requests.get(f"{self.base_url}/ping", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def remember(
        self,
        content: str,
        *,
        tags: list[str] | None = None,
        scope: str = "project",
        agent_id: str = "default",
        ttl_seconds: float = 0,
    ) -> Memory:
        """Store a new memory.

        Args:
            content: The fact/principle to remember
            tags: Optional tags for categorization
            scope: Memory scope (project, user, agent, global)
            agent_id: Identifier for the agent storing this
            ttl_seconds: Time-to-live in seconds (0 = never expires)

        Returns:
            The stored Memory object
        """
        memory = Memory(
            content=content,
            tags=tags or [],
            scope=scope,
            agent_id=agent_id,
            ttl_seconds=ttl_seconds,
        )

        if self._use_daemon:
            try:
                resp = requests.post(
                    f"{self.base_url}/remember",
                    json={
                        "content": content,
                        "tags": tags or [],
                        "scope": scope,
                        "agent_id": agent_id,
                        "ttl_seconds": ttl_seconds,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
            except Exception:
                # Fall back to direct store
                self._use_daemon = False
                self._store = MemoryStore(self.db_path)
                self._store.remember(memory)
        else:
            self._store.remember(memory)

        return memory

    def recall(
        self,
        query: str = "",
        *,
        scope: str | None = None,
        agent_id: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[Memory]:
        """Search for memories.

        Args:
            query: Search query (searches content and tags)
            scope: Filter by scope
            agent_id: Filter by agent
            tags: Filter by tags (matches any)
            limit: Maximum results to return

        Returns:
            List of Memory objects sorted by relevance
        """
        if self._use_daemon:
            try:
                params: dict[str, Any] = {"q": query, "limit": limit}
                if scope:
                    params["scope"] = scope
                resp = requests.get(
                    f"{self.base_url}/recall",
                    params=params,
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                return [
                    Memory(
                        id=m["id"],
                        content=m["content"],
                        tags=m["tags"],
                        scope=m["scope"],
                        score=m["score"],
                        updated_at=m["updated_at"],
                    )
                    for m in data
                ]
            except Exception:
                # Fall back to direct store
                self._use_daemon = False
                self._store = MemoryStore(self.db_path)

        return self._store.recall(
            query,
            scope=scope,
            agent_id=agent_id,
            tags=tags,
            limit=limit,
        )

    def forget(self, memory_id: str) -> bool:
        """Delete a memory by id."""
        if self._use_daemon:
            try:
                resp = requests.delete(
                    f"{self.base_url}/forget",
                    params={"id": memory_id},
                    timeout=10,
                )
                resp.raise_for_status()
                return True
            except Exception:
                self._use_daemon = False
                self._store = MemoryStore(self.db_path)

        return self._store.forget(memory_id)

    def clear_scope(self, scope: str) -> int:
        """Delete all memories in a scope."""
        if self._use_daemon:
            try:
                resp = requests.delete(
                    f"{self.base_url}/clear",
                    params={"scope": scope},
                    timeout=10,
                )
                resp.raise_for_status()
                return resp.json().get("deleted", 0)
            except Exception:
                self._use_daemon = False
                self._store = MemoryStore(self.db_path)

        return self._store.clear_scope(scope)

    def stats(self) -> dict[str, Any]:
        """Get memory store statistics."""
        if self._use_daemon:
            try:
                resp = requests.get(f"{self.base_url}/stats", timeout=10)
                resp.raise_for_status()
                return resp.json()
            except Exception:
                self._use_daemon = False
                self._store = MemoryStore(self.db_path)

        return self._store.stats()

    @property
    def using_daemon(self) -> bool:
        """Whether we're connected to a daemon or using direct store."""
        return self._use_daemon


# ─── Convenience functions ───────────────────────────────────────────────────

_default_memory: Onemind | None = None


def _get_default() -> Onemind:
    global _default_memory
    if _default_memory is None:
        _default_memory = Onemind()
    return _default_memory


def remember(content: str, **kwargs: Any) -> Memory:
    """Store a memory using the default client."""
    return _get_default().remember(content, **kwargs)


def recall(query: str = "", **kwargs: Any) -> list[Memory]:
    """Search memories using the default client."""
    return _get_default().recall(query, **kwargs)


def forget(memory_id: str) -> bool:
    """Delete a memory using the default client."""
    return _get_default().forget(memory_id)


def stats() -> dict[str, Any]:
    """Get stats using the default client."""
    return _get_default().stats()
