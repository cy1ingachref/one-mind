"""Tests for OneMind."""
from __future__ import annotations

import os
import io
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

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
        # IDs should differ (no silent overwrite)
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


class TestMCPProtocol:
    """Test MCP server protocol handling."""

    def run_mcp(self, messages: list[dict]) -> list[dict]:
        """Run MCP server with given messages and return responses."""
        from onemind.mcp.server import main
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
