"""Tests for Onemind."""
from __future__ import annotations

import os
import time
import tempfile
from pathlib import Path

import pytest

from onemind import Memory, MemoryStore, Onemind


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test.db")


@pytest.fixture
def store(tmp_db):
    """Create a MemoryStore with a temporary database."""
    return MemoryStore(tmp_db)


class TestMemory:
    def test_memory_has_default_id(self):
        m = Memory(content="test fact")
        assert m.id
        assert len(m.id) == 16

    def test_memory_is_not_expired_by_default(self):
        m = Memory(content="test")
        assert not m.is_expired

    def test_memory_expires_after_ttl(self):
        m = Memory(content="test", ttl_seconds=0.01)
        time.sleep(0.02)
        assert m.is_expired

    def test_memory_to_dict_roundtrip(self):
        m = Memory(content="test", tags=["a", "b"], scope="project/x")
        d = m.to_dict()
        m2 = Memory.from_dict(d)
        assert m2.content == m.content
        assert m2.tags == m.tags
        assert m2.scope == m.scope

    def test_no_overwrite_same_content_different_scope(self):
        """Same content in different scopes should create separate memories."""
        store = MemoryStore(":memory:")
        m1 = store.remember(Memory(content="Auth uses JWT", scope="project/a"))
        m2 = store.remember(Memory(content="Auth uses JWT", scope="project/b"))
        # IDs should differ (no silent overwrite)
        assert m1.id != m2.id


class TestMemoryStore:
    def test_remember_and_recall(self, store):
        store.remember(Memory(content="Auth uses JWT"))
        store.remember(Memory(content="DB uses PostgreSQL"))

        results = store.recall("auth")
        assert len(results) >= 1
        assert any("JWT" in r.content for r in results)

    def test_recall_by_scope(self, store):
        store.remember(Memory(content="Fact 1", scope="project/a"))
        store.remember(Memory(content="Fact 2", scope="project/b"))

        results = store.recall("Fact", scope="project/a")
        assert all(r.scope == "project/a" for r in results)

    def test_recall_by_tags(self, store):
        store.remember(Memory(content="Security fact", tags=["security", "auth"]))
        store.remember(Memory(content="Performance fact", tags=["perf"]))

        results = store.recall(tags=["security"])
        assert all("security" in r.tags for r in results)

    def test_forget(self, store):
        m = store.remember(Memory(content="To delete"))
        assert store.forget(m.id)
        assert not store.forget(m.id)

    def test_clear_scope(self, store):
        store.remember(Memory(content="Fact 1", scope="project/x"))
        store.remember(Memory(content="Fact 2", scope="project/x"))
        store.remember(Memory(content="Fact 3", scope="project/y"))

        count = store.clear_scope("project/x")
        assert count == 2
        assert store.count(scope="project/y") == 1

    def test_stats(self, store):
        store.remember(Memory(content="A", scope="project/a"))
        store.remember(Memory(content="B", scope="project/b"))

        stats = store.stats()
        assert stats["total"] == 2
        assert "project/a" in stats["scopes"]

    def test_count(self, store):
        assert store.count() == 0
        store.remember(Memory(content="test"))
        assert store.count() == 1


class TestOnemindSDK:
    def test_remember_and_recall_direct(self, tmp_db):
        """Test SDK with direct store (no daemon)."""
        sdk = Onemind(db_path=tmp_db)
        sdk.remember("Auth uses JWT with RS256", tags=["security", "auth"])

        results = sdk.recall("jwt")
        assert len(results) >= 1
        assert any("JWT" in r.content for r in results)

    def test_recall_empty_query_returns_all(self, tmp_db):
        sdk = Onemind(db_path=tmp_db)
        sdk.remember("Fact A")
        sdk.remember("Fact B")

        results = sdk.recall("")
        assert len(results) >= 2

    def test_forget_via_sdk(self, tmp_db):
        sdk = Onemind(db_path=tmp_db)
        mem = sdk.remember("To delete")
        assert sdk.forget(mem.id)
        assert not sdk.forget(mem.id)

    def test_clear_scope_via_sdk(self, tmp_db):
        sdk = Onemind(db_path=tmp_db)
        sdk.remember("A", scope="project/x")
        sdk.remember("B", scope="project/x")
        count = sdk.clear_scope("project/x")
        assert count == 2

    def test_stats_via_sdk(self, tmp_db):
        sdk = Onemind(db_path=tmp_db)
        sdk.remember("Test fact", scope="test")
        stats = sdk.stats()
        assert stats["total"] == 1
        assert "test" in stats["scopes"]


class TestDaemonIntegration:
    """Test the HTTP daemon with a local instance."""

    def test_daemon_remember_and_recall(self):
        """Test daemon remember/recall with a real local daemon."""
        import requests
        from onemind.daemon import MemoryDaemon
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "daemon_test.db")
            daemon = MemoryDaemon(port=7777, db_path=db_path)
            daemon.start(blocking=False)
            time.sleep(1)

            try:
                # Ping
                resp = requests.get("http://127.0.0.1:7777/ping", timeout=5)
                assert resp.status_code == 200
                assert resp.json()["status"] == "ok"

                # Remember
                resp = requests.post(
                    "http://127.0.0.1:7777/remember",
                    json={"content": "Integration test fact", "tags": ["test", "integration"]},
                    timeout=5,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "ok"
                memory_id = data["id"]

                # Recall
                resp = requests.get(
                    "http://127.0.0.1:7777/recall?q=integration",
                    timeout=5,
                )
                assert resp.status_code == 200
                results = resp.json()
                assert len(results) >= 1
                assert any("Integration" in r["content"] for r in results)

                # Stats
                resp = requests.get("http://127.0.0.1:7777/stats", timeout=5)
                assert resp.status_code == 200
                stats = resp.json()
                assert stats["total"] >= 1

                # Forget
                resp = requests.delete(
                    f"http://127.0.0.1:7777/forget?id={memory_id}",
                    timeout=5,
                )
                assert resp.status_code == 200

                # Verify deleted
                resp = requests.get(
                    "http://127.0.0.1:7777/recall?q=integration",
                    timeout=5,
                )
                results = resp.json()
                assert not any(r["id"] == memory_id for r in results)

            finally:
                daemon.stop()

    def test_daemon_clear_scope(self):
        """Test daemon scope clearing."""
        import requests
        from onemind.daemon import MemoryDaemon
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "daemon_scope_test.db")
            daemon = MemoryDaemon(port=7778, db_path=db_path)
            daemon.start(blocking=False)
            time.sleep(1)

            try:
                # Add memories in different scopes
                for i in range(3):
                    requests.post(
                        "http://127.0.0.1:7778/remember",
                        json={"content": f"Scope A fact {i}", "scope": "project/a"},
                        timeout=5,
                    )
                for i in range(2):
                    requests.post(
                        "http://127.0.0.1:7778/remember",
                        json={"content": f"Scope B fact {i}", "scope": "project/b"},
                        timeout=5,
                    )

                # Clear scope A
                resp = requests.delete(
                    "http://127.0.0.1:7778/clear?scope=project/a",
                    timeout=5,
                )
                assert resp.status_code == 200
                assert resp.json()["deleted"] == 3

                # Verify scope B still has memories
                resp = requests.get("http://127.0.0.1:7778/stats", timeout=5)
                stats = resp.json()
                assert stats["total"] == 2
                assert stats["scopes"].get("project/b") == 2

            finally:
                daemon.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
