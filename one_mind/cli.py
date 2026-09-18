"""OneMind CLI — command-line interface."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .sdk import OneMind

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="one_mind")
def cli():
    """OneMind — shared memory layer for AI agents.

    Store and recall facts across sessions, across tools, across time.
    """
    pass


@cli.command()
@click.argument("content")
@click.option("--tags", "-t", multiple=True, help="Tags for the memory")
@click.option("--scope", "-s", default="project", help="Memory scope")
@click.option("--agent", "-a", default="default", help="Agent identifier")
@click.option("--ttl", type=float, default=0, help="Time-to-live in seconds (0=never)")
@click.option("--host", default=None, help="Daemon host")
@click.option("--port", type=int, default=None, help="Daemon port")
def remember(content: str, tags: tuple[str, ...], scope: str, agent: str, ttl: float, host: str | None, port: int | None):
    """Store a fact in memory.

    Example:
        one_mind remember "Auth uses JWT with RS256" -t security -t auth -s project/myapp
    """
    mem = OneMind(host=host, port=port)
    memory = mem.remember(
        content,
        tags=list(tags),
        scope=scope,
        agent_id=agent,
        ttl_seconds=ttl,
    )
    console.print(f"[green]Remembered:[/green] {memory.content[:60]}...")
    console.print(f"  [dim]id: {memory.id}[/dim]")
    console.print(f"  [dim]scope: {scope}, tags: {list(tags)}[/dim]")


@cli.command()
@click.argument("query", required=False, default="")
@click.option("--scope", "-s", default=None, help="Filter by scope")
@click.option("--tags", "-t", multiple=True, help="Filter by tags")
@click.option("--limit", "-l", type=int, default=10, help="Max results")
@click.option("--host", default=None, help="Daemon host")
@click.option("--port", type=int, default=None, help="Daemon port")
def recall(query: str, scope: str | None, tags: tuple[str, ...], limit: int, host: str | None, port: int | None):
    """Search memories.

    Example:
        one_mind recall "authentication"
        one_mind recall -s project/myapp --tags security
    """
    mem = OneMind(host=host, port=port)
    results = mem.recall(
        query,
        scope=scope,
        tags=list(tags) if tags else None,
        limit=limit,
    )

    if not results:
        console.print("[dim]No memories found.[/dim]")
        return

    table = Table(title="Memories")
    table.add_column("Score", style="cyan", width=6)
    table.add_column("Content", style="green")
    table.add_column("Tags", style="yellow")
    table.add_column("Scope", style="blue")

    for m in results:
        table.add_row(
            f"{m.score:.1f}",
            m.content[:80] + ("..." if len(m.content) > 80 else ""),
            ", ".join(m.tags) if m.tags else "-",
            m.scope,
        )

    console.print(table)
    console.print(f"\n[dim]Found {len(results)} memories[/dim]")


@cli.command()
@click.argument("memory_id")
@click.option("--host", default=None, help="Daemon host")
@click.option("--port", type=int, default=None, help="Daemon port")
def forget(memory_id: str, host: str | None, port: int | None):
    """Delete a memory by id.

    Example:
        one_mind forget abc123def456
    """
    mem = OneMind(host=host, port=port)
    if mem.forget(memory_id):
        console.print(f"[green]Forgot:[/green] {memory_id}")
    else:
        console.print(f"[yellow]Memory not found:[/yellow] {memory_id}")


@cli.command()
@click.option("--host", default=None, help="Daemon host")
@click.option("--port", type=int, default=None, help="Daemon port")
def stats(host: str | None, port: int | None):
    """Show memory statistics."""
    mem = OneMind(host=host, port=port)
    data = mem.stats()
    console.print(f"[bold]Total memories:[/bold] {data['total']}")
    scopes = data.get("scopes", {})
    if scopes:
        table = Table(title="Scopes")
        table.add_column("Scope", style="blue")
        table.add_column("Count", style="cyan")
        for scope, count in scopes.items():
            table.add_row(scope, str(count))
        console.print(table)


@cli.command()
@click.option("--host", default=None, help="Daemon host")
@click.option("--port", type=int, default=None, help="Daemon port")
def list_all(host: str | None, port: int | None):
    """List all memories."""
    mem = OneMind(host=host, port=port)
    results = mem.recall(limit=100)
    for m in results:
        console.print(f"[cyan]{m.id}[/cyan] {m.content[:60]}")


@cli.command()
@click.option("--host", default=None, help="Daemon host")
@click.option("--port", type=int, default=None, help="Daemon port")
@click.option("--db", default=None, help="Database path")
def serve(host: str | None, port: int | None, db: str | None):
    """Start the memory daemon."""
    from .daemon import MemoryDaemon

    daemon = MemoryDaemon(
        host=host or "127.0.0.1",
        port=port or 7777,
        db_path=db or "~/.one_mind/default.db",
    )
    console.print(f"[green]OneMind daemon starting on {daemon.host}:{daemon.port}[/green]")
    console.print(f"[dim]Database: {daemon.db_path}[/dim]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    try:
        daemon.start(blocking=True)
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
        daemon.stop()


if __name__ == "__main__":
    cli()
