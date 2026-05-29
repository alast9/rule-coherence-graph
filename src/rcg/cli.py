"""rcg command-line interface."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from rcg.detectors.syntactic import SyntacticDetector
from rcg.extractors.anthropic_provider import AnthropicProvider
from rcg.extractors.extract import extract_all
from rcg.extractors.mock_provider import MockProvider
from rcg.parsers.discovery import discover
from rcg.providers.llm import LLMProvider
from rcg.reports.markdown import render
from rcg.schema import Rule

app = typer.Typer(add_completion=False, help="Rule Coherence Graph (RCG).")

PROVIDER_OPT = Annotated[
    str,
    typer.Option(
        "--provider",
        envvar="RCG_PROVIDER",
        help=(
            "Extraction provider: 'auto' (anthropic if ANTHROPIC_API_KEY is set, "
            "else the offline mock), 'anthropic' (real API), or 'mock' (offline demo)."
        ),
    ),
]

NEO4J_URI = Annotated[
    str, typer.Option(envvar="RCG_NEO4J_URI", help="Bolt URI. Ignored with --no-graph.")
]
NEO4J_USER = Annotated[str, typer.Option(envvar="RCG_NEO4J_USER")]
NEO4J_PASS = Annotated[str, typer.Option(envvar="RCG_NEO4J_PASSWORD")]


def _build_provider(name: str) -> LLMProvider:
    if name == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return AnthropicProvider()
        typer.echo(
            "warning: ANTHROPIC_API_KEY not set; using the offline heuristic mock "
            "extractor (approximate results, not for production). Pass "
            "--provider anthropic to force the API, or --provider mock to silence this.",
            err=True,
        )
        return MockProvider()
    if name == "mock":
        return MockProvider()
    if name == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            typer.echo(
                "error: ANTHROPIC_API_KEY is not set. Use --provider mock for offline demo.",
                err=True,
            )
            raise typer.Exit(code=2)
        return AnthropicProvider()
    typer.echo(f"error: unknown provider {name!r}", err=True)
    raise typer.Exit(code=2)


def _ingest(
    path: Path, provider_name: str, write_graph: bool, uri: str, user: str, pw: str
) -> list[Rule]:
    raws = discover(path)
    if not raws:
        typer.echo(f"No rule files discovered under {path}", err=True)
        raise typer.Exit(code=1)

    provider = _build_provider(provider_name)
    rules = extract_all(raws, provider)

    if write_graph:
        from rcg.graph.loader import GraphLoader  # lazy import: neo4j optional at runtime

        with GraphLoader.connect(uri, user, pw) as loader:
            loader.load_rules(rules)

    typer.echo(f"Ingested {len(rules)} rule(s) from {path}.", err=True)
    return rules


@app.command()
def ingest(
    path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    provider: PROVIDER_OPT = "auto",
    neo4j_uri: NEO4J_URI = "bolt://localhost:7687",
    neo4j_user: NEO4J_USER = "neo4j",
    neo4j_password: NEO4J_PASS = "rcgdevpassword",
    no_graph: bool = typer.Option(False, "--no-graph", help="Skip the Neo4j write."),
) -> None:
    """Parse and load a rule corpus."""
    _ingest(
        path,
        provider_name=provider,
        write_graph=not no_graph,
        uri=neo4j_uri,
        user=neo4j_user,
        pw=neo4j_password,
    )


@app.command()
def check(
    path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    provider: PROVIDER_OPT = "auto",
    neo4j_uri: NEO4J_URI = "bolt://localhost:7687",
    neo4j_user: NEO4J_USER = "neo4j",
    neo4j_password: NEO4J_PASS = "rcgdevpassword",
    no_graph: bool = typer.Option(False, "--no-graph", help="Skip Neo4j read/write."),
    out: Path | None = typer.Option(None, "--out", help="Write report to file instead of stdout."),
) -> None:
    """Ingest a corpus and run the syntactic conflict pass."""
    rules = _ingest(
        path,
        provider_name=provider,
        write_graph=not no_graph,
        uri=neo4j_uri,
        user=neo4j_user,
        pw=neo4j_password,
    )

    conflicts = SyntacticDetector().detect(rules)

    if not no_graph and conflicts:
        from rcg.graph.loader import GraphLoader

        with GraphLoader.connect(neo4j_uri, neo4j_user, neo4j_password) as loader:
            loader.load_conflicts(conflicts)

    report = render(conflicts)
    if out:
        out.write_text(report, encoding="utf-8")
        typer.echo(f"Wrote report to {out}", err=True)
    else:
        typer.echo(report)

    if conflicts:
        sys.exit(1)


if __name__ == "__main__":
    app()
