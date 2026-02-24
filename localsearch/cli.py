"""CLI interface for LocalSearch."""

import logging
import sys

import click
from rich.console import Console
from rich.table import Table

from localsearch.config import load_config

console = Console()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.option("--config", "-c", default=None, help="Path to config.yaml")
@click.pass_context
def cli(ctx, config):
    """LocalSearch - Fully local RAG file search."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


@cli.command()
@click.option("--path", "-p", multiple=True, help="Specific path(s) to scan (overrides config)")
@click.pass_context
def ingest(ctx, path):
    """Scan files and build the search index."""
    cfg = load_config(ctx.obj["config_path"])
    _setup_logging(cfg.log_level)

    from localsearch.pipeline import Pipeline

    pipeline = Pipeline(cfg)
    paths = list(path) if path else None

    console.print("[bold]Starting ingestion pipeline...[/bold]")
    stats = pipeline.ingest(paths)

    console.print()
    table = Table(title="Ingestion Complete")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")
    table.add_row("Files scanned", str(stats["scanned"]))
    table.add_row("Files processed", str(stats["processed"]))
    table.add_row("Chunks created", str(stats["chunks_created"]))
    table.add_row("Errors", str(stats["errors"]))
    table.add_row("Deleted files cleaned", str(stats["deleted"]))
    table.add_row("Elapsed time", f"{stats['elapsed_seconds']}s")
    console.print(table)


@cli.command()
@click.argument("query")
@click.option("--top-k", "-k", default=None, type=int, help="Number of results")
@click.option("--file-type", "-t", default=None, help="Filter by file type (text/pdf/docx/audio/video/image)")
@click.pass_context
def search(ctx, query, top_k, file_type):
    """Semantic search across indexed files."""
    cfg = load_config(ctx.obj["config_path"])
    _setup_logging(cfg.log_level)

    from localsearch.query.search import SearchEngine

    engine = SearchEngine(cfg)
    results = engine.search(query, top_k=top_k, file_type=file_type)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    console.print(f"[bold]Found {len(results)} results:[/bold]\n")
    for i, result in enumerate(results, 1):
        console.print(f"[bold cyan]{i}.[/bold cyan] [green]{result.file_path}[/green]")
        console.print(f"   Score: {result.score:.4f}  |  Type: {result.file_type}  |  Chunk: {result.chunk_index}")
        # Show preview
        preview = result.text[:300].replace("\n", " ")
        console.print(f"   {preview}")
        console.print()


@cli.command()
@click.argument("question")
@click.option("--top-k", "-k", default=None, type=int, help="Number of context chunks")
@click.option("--file-type", "-t", default=None, help="Filter by file type")
@click.pass_context
def ask(ctx, question, top_k, file_type):
    """Ask a question and get an AI-generated answer with sources."""
    cfg = load_config(ctx.obj["config_path"])
    _setup_logging(cfg.log_level)

    from localsearch.query.rag import RAGEngine

    engine = RAGEngine(cfg)

    console.print("[bold]Searching and generating answer...[/bold]\n")
    result = engine.ask(question, top_k=top_k, file_type=file_type)

    console.print("[bold green]Answer:[/bold green]")
    console.print(result["answer"])
    console.print()

    if result["sources"]:
        console.print("[bold cyan]Sources:[/bold cyan]")
        for src in result["sources"]:
            console.print(f"  - {src}")


@cli.command()
@click.pass_context
def status(ctx):
    """Show indexing statistics."""
    cfg = load_config(ctx.obj["config_path"])
    _setup_logging(cfg.log_level)

    from localsearch.pipeline import Pipeline

    pipeline = Pipeline(cfg)
    stats = pipeline.get_stats()

    table = Table(title="LocalSearch Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")
    table.add_row("Total files tracked", str(stats["total_files"]))
    table.add_row("Indexed", str(stats["indexed"]))
    table.add_row("Pending", str(stats["pending"]))
    table.add_row("Errors", str(stats["errors"]))
    table.add_row("Total chunks", str(stats["total_chunks"]))
    table.add_row("Vectors in Qdrant", str(stats["vector_count"]))
    console.print(table)


@cli.command()
@click.confirmation_option(prompt="This will delete all indexed data. Are you sure?")
@click.pass_context
def reset(ctx):
    """Clear all indexed data and reset the database."""
    cfg = load_config(ctx.obj["config_path"])
    _setup_logging(cfg.log_level)

    from localsearch.pipeline import Pipeline

    pipeline = Pipeline(cfg)
    pipeline.reset()
    console.print("[bold green]All indexed data has been cleared.[/bold green]")


if __name__ == "__main__":
    cli()
