"""rcg command-line interface."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from rcg.baseline import load_baseline, split_baselined, write_baseline
from rcg.detectors.base import Finding
from rcg.detectors.precedence import PrecedenceDetector
from rcg.detectors.semantic import AnthropicJudge, MockJudge, SemanticDetector, SemanticJudge
from rcg.detectors.syntactic import SyntacticDetector
from rcg.extractors.anthropic_provider import AnthropicProvider
from rcg.extractors.extract import extract_all
from rcg.extractors.mock_provider import MockProvider
from rcg.parsers.discovery import discover
from rcg.providers.embedding import HashingEmbeddingProvider
from rcg.providers.llm import LLMProvider
from rcg.reports.markdown import render_report
from rcg.schema import Rule
from rcg.scoring import score_corpus

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


def _build_judge(provider_name: str) -> SemanticJudge:
    if provider_name == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicJudge()
    if provider_name == "auto" and os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicJudge()
    return MockJudge()


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


def _run_passes(
    rules: list[Rule],
    *,
    provider_name: str,
    semantic: bool,
    precedence: bool,
) -> list[Finding]:
    """Run the requested detectors and return all findings."""
    findings: list[Finding] = []
    for conflict in SyntacticDetector().detect(rules):
        findings.append(conflict)

    if semantic:
        embedder = HashingEmbeddingProvider()
        judge = _build_judge(provider_name)
        for sem in SemanticDetector(embedder, judge).detect(rules):
            findings.append(sem)

    if precedence:
        exclude = {frozenset({f.rule_a.id, f.rule_b.id}) for f in findings}
        for amb in PrecedenceDetector().detect(rules, exclude=exclude):
            findings.append(amb)

    return findings


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
    semantic: bool = typer.Option(
        False, "--semantic/--no-semantic", help="Run the semantic (judge) pass."
    ),
    precedence: bool = typer.Option(
        True, "--precedence/--no-precedence", help="Run the precedence pass."
    ),
    min_score: float | None = typer.Option(
        None, "--min-score", help="Fail if the coherence score is below this value."
    ),
    baseline: Path = typer.Option(
        Path("rcg-baseline.json"),
        "--baseline",
        help="Accepted-conflicts baseline file (applied only if it exists).",
    ),
    update_baseline: bool = typer.Option(
        False, "--update-baseline", help="Write the baseline from current findings and exit 0."
    ),
) -> None:
    """Ingest a corpus and run the conflict-detection passes."""
    rules = _ingest(
        path,
        provider_name=provider,
        write_graph=not no_graph,
        uri=neo4j_uri,
        user=neo4j_user,
        pw=neo4j_password,
    )

    findings = _run_passes(
        rules, provider_name=provider, semantic=semantic, precedence=precedence
    )

    if update_baseline:
        count = write_baseline(baseline, findings)
        typer.echo(f"Wrote baseline with {count} finding(s) to {baseline}.", err=True)
        raise typer.Exit(code=0)

    suppressed: list[Finding] = []
    kept = findings
    if baseline.exists():
        accepted = load_baseline(baseline)
        kept, suppressed = split_baselined(findings, accepted)

    score = score_corpus(len(rules), kept)

    if not no_graph and kept:
        from rcg.graph.loader import GraphLoader

        with GraphLoader.connect(neo4j_uri, neo4j_user, neo4j_password) as loader:
            loader.load_conflicts(kept)

    report = render_report(kept, score=score, suppressed=len(suppressed))
    if out:
        out.write_text(report, encoding="utf-8")
        typer.echo(f"Wrote report to {out}", err=True)
    else:
        typer.echo(report)

    if min_score is not None:
        if score.score < min_score:
            sys.exit(1)
    elif kept:
        sys.exit(1)


@app.command()
def score(
    path: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    provider: PROVIDER_OPT = "auto",
    no_graph: bool = typer.Option(False, "--no-graph", help="Skip Neo4j read/write."),
    neo4j_uri: NEO4J_URI = "bolt://localhost:7687",
    neo4j_user: NEO4J_USER = "neo4j",
    neo4j_password: NEO4J_PASS = "rcgdevpassword",
    semantic: bool = typer.Option(
        False, "--semantic/--no-semantic", help="Run the semantic (judge) pass."
    ),
    precedence: bool = typer.Option(
        True, "--precedence/--no-precedence", help="Run the precedence pass."
    ),
) -> None:
    """Print the corpus coherence score and breakdown (always exits 0)."""
    rules = _ingest(
        path,
        provider_name=provider,
        write_graph=not no_graph,
        uri=neo4j_uri,
        user=neo4j_user,
        pw=neo4j_password,
    )
    findings = _run_passes(
        rules, provider_name=provider, semantic=semantic, precedence=precedence
    )
    report = score_corpus(len(rules), findings)
    typer.echo(f"Coherence score: {report.score:.3f}")
    typer.echo(f"Rules: {report.n_rules}")
    typer.echo(f"Weighted penalty: {report.weighted:.3f}")
    for ftype in ("syntactic", "semantic", "precedence"):
        if ftype in report.by_type:
            typer.echo(f"  {ftype}: {report.by_type[ftype]}")


if __name__ == "__main__":
    app()
