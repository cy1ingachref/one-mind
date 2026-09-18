"""Tests for OneMind."""
from __future__ import annotations

import os
import json
import time
import tempfile
import uuid
from pathlib import Path

import pytest

from onemind import Memory, MemoryStore, OneMind


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

    def test_empty_content_rejected(self):
        """Empty content should raise ValueError."""
        store = MemoryStore(":memory:")
        with pytest.raises(ValueError, match="cannot be empty"):
            store.remember(Memory(content=""))
        with pytest.raises(ValueError, match="cannot be empty"):
            store.remember(Memory(content="   "))

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
        assert m1.id != m2.id


class TestMemoryStore:
    def test_remember_and_recall(self, store):
        store.remember(Memory(content="Auth uses JWT"))
        store.remember(Memory(content="DB uses PostgreSQL"))

        results = store.recall("JWT")
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

    def test_empty_content_rejected(self, store):
        """Empty content should raise ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            store.remember(Memory(content=""))
        with pytest.raises(ValueError, match="cannot be empty"):
            store.remember(Memory(content="   "))


class TestBM25Scoring:
    def test_bm25_exact_match_scores_highest(self, store):
        store.remember(Memory(content="JWT authentication"))
        store.remember(Memory(content="Something else entirely"))
        results = store.recall("JWT authentication")
        assert results[0].content == "JWT authentication"
        assert results[0].score >= 10.0

    def test_bm25_substring_match(self, store):
        store.remember(Memory(content="Auth uses JWT with RS256"))
        results = store.recall("JWT")
        assert len(results) >= 1
        assert results[0].score >= 5.0

    def test_bm25_tag_boost(self, store):
        store.remember(Memory(content="Some fact", tags=["authentication"]))
        store.remember(Memory(content="Another fact", tags=["database"]))
        results = store.recall("authentication")
        assert len(results) >= 1
        assert "authentication" in results[0].tags

    def test_bm25_no_query_returns_all(self, store):
        store.remember(Memory(content="Fact A"))
        store.remember(Memory(content="Fact B"))
        results = store.recall("")
        assert len(results) >= 2

    def test_bm25_sorted_by_score(self, store):
        store.remember(Memory(content="JWT token validation for security"))
        store.remember(Memory(content="Random unrelated content"))
        store.remember(Memory(content="JWT authentication module"))
        results = store.recall("JWT")
        # Higher score should come first
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score


class TestProvenance:
    def test_recall_by_agent_id(self, store):
        store.remember(Memory(content="Claude fact", agent_id="claude"))
        store.remember(Memory(content="GPT fact", agent_id="gpt"))
        store.remember(Memory(content="Another Claude fact", agent_id="claude"))

        results = store.recall(agent_id="claude")
        assert len(results) == 2
        assert all(r.agent_id == "claude" for r in results)

    def test_stats_includes_agents(self, store):
        store.remember(Memory(content="C1", agent_id="claude"))
        store.remember(Memory(content="G1", agent_id="gpt"))
        stats = store.stats()
        assert "agents" in stats
        assert stats["agents"].get("claude") == 1
        assert stats["agents"].get("gpt") == 1


class TestGarbageCollection:
    def test_gc_removes_expired(self, store):
        store.remember(Memory(content="Short lived", ttl_seconds=0.01))
        store.remember(Memory(content="Long lived", ttl_seconds=3600))
        store.remember(Memory(content="No TTL"))
        
        time.sleep(0.02)
        
        count = store.gc()
        assert count == 1
        assert store.count() == 2

    def test_gc_no_expired_returns_zero(self, store):
        store.remember(Memory(content="Long lived", ttl_seconds=3600))
        store.remember(Memory(content="No TTL"))
        
        count = store.gc()
        assert count == 0
        assert store.count() == 2

    def test_include_expired_parameter(self, store):
        store.remember(Memory(content="Expired", ttl_seconds=0.01))
        time.sleep(0.02)
        
        # Without include_expired
        results = store.recall("Expired", include_expired=False)
        assert len(results) == 0
        
        # With include_expired
        results = store.recall("Expired", include_expired=True)
        assert len(results) == 1


class TestOneMindSDK:
    def test_remember_and_recall_direct(self, tmp_db):
        """Test SDK with direct store (no daemon)."""
        sdk = OneMind(db_path=tmp_db)
        sdk.remember("Auth uses JWT with RS256", tags=["security", "auth"])

        results = sdk.recall("JWT")
        assert len(results) >= 1
        assert any("JWT" in r.content for r in results)

    def test_recall_empty_query_returns_all(self, tmp_db):
        sdk = OneMind(db_path=tmp_db)
        sdk.remember("Fact A")
        sdk.remember("Fact B")

        results = sdk.recall("")
        assert len(results) >= 2

    def test_forget_via_sdk(self, tmp_db):
        sdk = OneMind(db_path=tmp_db)
        mem = sdk.remember("To delete")
        assert sdk.forget(mem.id)
        assert not sdk.forget(mem.id)

    def test_clear_scope_via_sdk(self, tmp_db):
        sdk = OneMind(db_path=tmp_db)
        sdk.remember("A", scope="project/x")
        sdk.remember("B", scope="project/x")
        count = sdk.clear_scope("project/x")
        assert count == 2

    def test_stats_via_sdk(self, tmp_db):
        sdk = OneMind(db_path=tmp_db)
        sdk.remember("Test fact", scope="test")
        stats = sdk.stats()
        assert stats["total"] == 1
        assert "test" in stats["scopes"]

    def test_empty_content_rejected_via_sdk(self, tmp_db):
        """Empty content should raise ValueError via SDK."""
        sdk = OneMind(db_path=tmp_db)
        with pytest.raises(ValueError, match="cannot be empty"):
            sdk.remember("")
        with pytest.raises(ValueError, match="cannot be empty"):
            sdk.remember("   ")

    def test_gc_via_sdk(self, tmp_db):
        """Test garbage collection via SDK."""
        sdk = OneMind(db_path=tmp_db)
        sdk.remember("Short lived", ttl_seconds=0.01)
        sdk.remember("Long lived", ttl_seconds=3600)
        
        time.sleep(0.02)
        count = sdk.gc()
        assert count == 1
        assert sdk.stats()["total"] == 1


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

                # Empty content rejected
                resp = requests.post(
                    "http://127.0.0.1:7777/remember",
                    json={"content": ""},
                    timeout=5,
                )
                assert resp.status_code == 400

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

    def test_daemon_gc_endpoint(self):
        """Test garbage collection via daemon."""
        import requests
        from onemind.daemon import MemoryDaemon
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "daemon_gc_test.db")
            daemon = MemoryDaemon(port=7779, db_path=db_path)
            daemon.start(blocking=False)
            time.sleep(1)

            try:
                # Add short-lived and long-lived
                requests.post(
                    "http://127.0.0.1:7779/remember",
                    json={"content": "Short lived", "ttl_seconds": 0.01},
                    timeout=5,
                )
                requests.post(
                    "http://127.0.0.1:7779/remember",
                    json={"content": "Long lived", "ttl_seconds": 3600},
                    timeout=5,
                )

                time.sleep(0.02)

                # Trigger GC
                resp = requests.post("http://127.0.0.1:7779/gc", timeout=5)
                assert resp.status_code == 200
                assert resp.json()["cleaned"] == 1

            finally:
                daemon.stop()

    def test_daemon_threaded_concurrent_access(self):
        """Test concurrent access to threaded daemon."""
        import requests
        from onemind.daemon import MemoryDaemon
        import tempfile
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "daemon_threaded_test.db")
            daemon = MemoryDaemon(port=7780, db_path=db_path)
            daemon.start(blocking=False)
            time.sleep(1)

            errors = []

            def remember_fact(i):
                try:
                    resp = requests.post(
                        "http://127.0.0.1:7780/remember",
                        json={"content": f"Thread fact {i}", "agent_id": f"agent_{i}"},
                        timeout=5,
                    )
                    assert resp.status_code == 200
                except Exception as e:
                    errors.append(e)

            try:
                threads = [threading.Thread(target=remember_fact, args=(i,)) for i in range(10)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                assert len(errors) == 0, f"Concurrent errors: {errors}"

                # Verify all facts stored
                resp = requests.get("http://127.0.0.1:7780/stats", timeout=5)
                stats = resp.json()
                assert stats["total"] == 10

            finally:
                daemon.stop()


class TestMCPProtocol:
    """Test MCP server protocol handling."""

    def run_mcp(self, messages: list[dict]) -> list[dict]:
        """Run MCP server with given messages and return responses."""
        import subprocess
        import sys

        # Build input
        input_text = "\n".join(json.dumps(m) for m in messages) + "\n"

        # Run server as subprocess
        proc = subprocess.run(
            [sys.executable, "-m", "onemind.mcp"],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=5,
        )

        # Parse responses
        responses = []
        for line in proc.stdout.strip().split("\n"):
            if line:
                responses.append(json.loads(line))
        return responses

    def test_initialize_handshake(self):
        """Test proper MCP initialize handshake."""
        responses = self.run_mcp([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}
        ])
        assert len(responses) == 1
        assert responses[0]["id"] == 1
        assert responses[0]["result"]["protocolVersion"] == "2025-03-26"
        assert "tools" in responses[0]["result"]["capabilities"]

    def test_tools_list(self):
        """Test tools/list returns available tools."""
        responses = self.run_mcp([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        ])
        assert len(responses) == 1
        tools = responses[0]["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        assert "remember" in tool_names
        assert "recall" in tool_names
        assert "forget" in tool_names
        assert "stats" in tool_names

    def test_unknown_tool_returns_error(self):
        """Test unknown tool returns JSON-RPC error."""
        responses = self.run_mcp([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "nonexistent", "arguments": {}}}
        ])
        assert len(responses) == 1
        assert "error" in responses[0]
        assert responses[0]["error"]["code"] == -32601

    def test_unknown_method_returns_error(self):
        """Test unknown method returns JSON-RPC error."""
        responses = self.run_mcp([
            {"jsonrpc": "2.0", "id": 1, "method": "nonexistent/method", "params": {}}
        ])
        assert len(responses) == 1
        assert "error" in responses[0]

    def test_remember_and_recall(self):
        """Test remember and recall via MCP."""
        import tempfile
        tmpdir = tempfile.mkdtemp()
        os.environ["ONEMIND_DB"] = os.path.join(tmpdir, "mcp_test.db")

        try:
            responses = self.run_mcp([
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "remember", "arguments": {"content": "MCP test fact", "tags": ["test"]}}},
            ])
            assert len(responses) == 1
            assert "Remembered" in responses[0]["result"]["content"][0]["text"]

            responses = self.run_mcp([
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "recall", "arguments": {"query": "MCP"}}},
            ])
            assert len(responses) == 1
            assert "MCP test fact" in responses[0]["result"]["content"][0]["text"]
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
            os.environ.pop("ONEMIND_DB", None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
