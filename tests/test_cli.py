"""Tests for CLI."""
from __future__ import annotations

import os
import tempfile
import uuid
from click.testing import CliRunner
import pytest

from onemind.cli import cli


@pytest.fixture
def tmp_db():
    """Create a unique temporary database path."""
    db_path = os.path.join(tempfile.gettempdir(), f"test_cli_{uuid.uuid4().hex}.db")
    yield db_path
    # Cleanup
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
def runner():
    return CliRunner()


class TestCLIRemember:
    def test_remember_basic(self, runner, tmp_db):
        env = {"ONEMIND_DB": tmp_db}
        result = runner.invoke(cli, ["remember", "Test fact"], env=env)
        assert result.exit_code == 0
        assert "Remembered" in result.output

    def test_remember_with_tags(self, runner, tmp_db):
        env = {"ONEMIND_DB": tmp_db}
        result = runner.invoke(cli, ["remember", "Test fact", "-t", "security", "-t", "auth"], env=env)
        assert result.exit_code == 0
        assert "Remembered" in result.output

    def test_remember_empty_content(self, runner, tmp_db):
        """Empty content should be rejected."""
        env = {"ONEMIND_DB": tmp_db}
        result = runner.invoke(cli, ["remember", ""], env=env)
        assert result.exit_code != 0 or "empty" in result.output.lower()


class TestCLIRecall:
    def test_recall_basic(self, runner, tmp_db):
        env = {"ONEMIND_DB": tmp_db}
        # First store
        runner.invoke(cli, ["remember", "Auth uses JWT"], env=env)
        # Then recall
        result = runner.invoke(cli, ["recall", "JWT"], env=env)
        assert result.exit_code == 0
        assert "Auth uses JWT" in result.output

    def test_recall_no_results(self, runner, tmp_db):
        env = {"ONEMIND_DB": tmp_db}
        result = runner.invoke(cli, ["recall", "nonexistent"], env=env)
        assert result.exit_code == 0
        assert "No memories found" in result.output

    def test_recall_with_scope(self, runner, tmp_db):
        env = {"ONEMIND_DB": tmp_db}
        runner.invoke(cli, ["remember", "Scoped fact", "-s", "project/x"], env=env)
        result = runner.invoke(cli, ["recall", "-s", "project/x"], env=env)
        assert result.exit_code == 0
        assert "Scoped fact" in result.output

    def test_recall_with_tags(self, runner, tmp_db):
        env = {"ONEMIND_DB": tmp_db}
        runner.invoke(cli, ["remember", "Tagged fact", "-t", "security"], env=env)
        result = runner.invoke(cli, ["recall", "-t", "security"], env=env)
        assert result.exit_code == 0
        assert "Tagged fact" in result.output


class TestCLILimit:
    def test_recall_with_limit(self, runner, tmp_db):
        env = {"ONEMIND_DB": tmp_db}
        for i in range(5):
            runner.invoke(cli, ["remember", f"Fact {i}"], env=env)
        result = runner.invoke(cli, ["recall", "-l", "2"], env=env)
        assert result.exit_code == 0


class TestCLIDelete:
    def test_forget(self, runner, tmp_db):
        env = {"ONEMIND_DB": tmp_db}
        # Store
        runner.invoke(cli, ["remember", "To forget"], env=env)
        # List to get ID
        result = runner.invoke(cli, ["list"], env=env)
        assert result.exit_code == 0
        # Extract first ID
        lines = result.output.strip().split("\n")
        assert lines and lines[0]
        memory_id = lines[0].split()[0]
        # Forget
        result = runner.invoke(cli, ["forget", memory_id], env=env)
        assert result.exit_code == 0
        assert "Forgot" in result.output

    def test_forget_nonexistent(self, runner, tmp_db):
        env = {"ONEMIND_DB": tmp_db}
        result = runner.invoke(cli, ["forget", "nonexistent"], env=env)
        assert result.exit_code == 0
        assert "not found" in result.output.lower()


class TestCLIStats:
    def test_stats(self, runner, tmp_db):
        env = {"ONEMIND_DB": tmp_db}
        runner.invoke(cli, ["remember", "Test fact"], env=env)
        result = runner.invoke(cli, ["stats"], env=env)
        assert result.exit_code == 0
        assert "1" in result.output


class TestCLIList:
    def test_list(self, runner, tmp_db):
        env = {"ONEMIND_DB": tmp_db}
        runner.invoke(cli, ["remember", "Fact A"], env=env)
        runner.invoke(cli, ["remember", "Fact B"], env=env)
        result = runner.invoke(cli, ["list"], env=env)
        assert result.exit_code == 0
        assert "Fact" in result.output


class TestCLIServe:
    def test_serve_uses_env_var(self):
        """Test that serve command respects ONEMIND_DB env var."""
        import subprocess
        import sys
        import time

        db_path = os.path.join(tempfile.gettempdir(), f"test_serve_{uuid.uuid4().hex}.db")

        # Start daemon with env var
        env = os.environ.copy()
        env["ONEMIND_DB"] = db_path
        proc = subprocess.Popen(
            [sys.executable, "-m", "onemind.cli", "serve"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(2)

        try:
            import requests
            resp = requests.get("http://127.0.0.1:7777/ping", timeout=3)
            assert resp.status_code == 200
        finally:
            proc.terminate()
            proc.wait()
            # Cleanup
            try:
                os.unlink(db_path)
            except Exception:
                pass
