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
from rcg.detectors.semantic import (
    AnthropicJudge,
    MockJudge,
    OpenAICompatibleJudge,
    SemanticDetector,
    SemanticJudge,
)
from rcg.detectors.syntactic import SyntacticDetector
from rcg.extractors.anthropic_provider import AnthropicProvider
from rcg.extractors.extract import extract_all
from rcg.extractors.mock_provider import MockProvider
from rcg.parsers.discovery import discover
from rcg.providers.embedding import EmbeddingProvider, HashingEmbeddingProvider
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
            "else the offline mock), 'anthropic' (real API), 'deepseek', 'qwen', "
            "'openai' (any OpenAI-compatible endpoint via RCG_LLM_BASE_URL), "
            "'openrouter' (aggregator), 'google' (Gemini API / AI Studio), "
            "'bedrock' (Amazon Bedrock), 'azure' (Azure AI Foundry / Azure OpenAI; "
            "model = deployment name), 'vertex' (Google Vertex AI; OAuth access "
            "token), or 'mock' (offline demo)."
        ),
    ),
]

# OpenAI-compatible presets: base_url + default model + the preset-specific key
# env. The model is always overridable via RCG_LLM_MODEL; keys fall back to the
# generic RCG_LLM_API_KEY (and, for the generic 'openai' provider, OPENAI_API_KEY).
_OPENAI_PRESETS: dict[str, dict[str, str | None]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyun.com/compatible-mode/v1",
        "model": "qwen-max",
        "key_env": "DASHSCOPE_API_KEY",
    },
    "openai": {
        "base_url": None,  # SDK default (or RCG_LLM_BASE_URL); points at api.openai.com
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        # Overridable via RCG_LLM_MODEL; OpenRouter uses vendor/model ids
        # (e.g. anthropic/claude-sonnet-4, openai/gpt-4o-mini).
        "model": "anthropic/claude-sonnet-4",
        "key_env": "OPENROUTER_API_KEY",
    },
    "google": {
        # Google Gemini API (AI Studio), OpenAI-compatible surface.
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
        "key_env": "GEMINI_API_KEY",
    },
}


def _resolve_openai_key(preset_key_env: str) -> str | None:
    """Resolve an OpenAI-compatible key: preset env, then generic RCG_LLM_API_KEY.

    The ``google`` preset (key env ``GEMINI_API_KEY``) additionally falls back to
    ``GOOGLE_API_KEY`` before the generic ``RCG_LLM_API_KEY``.
    """
    if preset_key_env == "GEMINI_API_KEY":
        return (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("RCG_LLM_API_KEY")
        )
    return os.environ.get(preset_key_env) or os.environ.get("RCG_LLM_API_KEY")


# Bedrock is special-cased rather than added to _OPENAI_PRESETS because its
# base_url is *computed from a region* (the static preset shape only carries a
# fixed base_url). It is still just another OpenAI-compatible endpoint: the
# OpenAI-SDK path uses an Amazon Bedrock API key as the bearer token (not SigV4).
_BEDROCK_DEFAULT_MODEL = "openai.gpt-oss-120b-1:0"
_BEDROCK_KEY_ENV = "AWS_BEARER_TOKEN_BEDROCK"


def _bedrock_region() -> str:
    """Resolve the Bedrock region: RCG_LLM_REGION, then the standard AWS vars."""
    return (
        os.environ.get("RCG_LLM_REGION")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-east-1"
    )


def _bedrock_base_url() -> str:
    """Compute the Bedrock OpenAI-compatible base URL (RCG_LLM_BASE_URL wins).

    RCG_LLM_BASE_URL lets users point at the newer Mantle endpoint
    (https://bedrock-mantle.<region>.api.aws/v1) or a different region/host.
    """
    override = os.environ.get("RCG_LLM_BASE_URL")
    if override:
        return override
    return f"https://bedrock-runtime.{_bedrock_region()}.amazonaws.com/openai/v1"


def _resolve_bedrock_key() -> str | None:
    """Resolve the Bedrock bearer key: AWS_BEARER_TOKEN_BEDROCK, then RCG_LLM_API_KEY."""
    return os.environ.get(_BEDROCK_KEY_ENV) or os.environ.get("RCG_LLM_API_KEY")


# Azure AI Foundry / Azure OpenAI is special-cased (computed base_url, like
# bedrock): the endpoint is per-resource and the "model" is the *deployment name*.
# The modern v1 GA path lets the plain OpenAI client work via
# ``<endpoint>/openai/v1`` (no api-version query param required).
_AZURE_ENDPOINT_ENV = "AZURE_OPENAI_ENDPOINT"
_AZURE_KEY_ENV = "AZURE_OPENAI_API_KEY"


def _azure_base_url() -> str | None:
    """Compute the Azure OpenAI v1 base URL, or None if the endpoint is unset.

    ``RCG_LLM_BASE_URL`` wins; otherwise ``<AZURE_OPENAI_ENDPOINT>/openai/v1``
    (trailing slash on the endpoint is stripped before appending).
    """
    override = os.environ.get("RCG_LLM_BASE_URL")
    if override:
        return override
    endpoint = os.environ.get(_AZURE_ENDPOINT_ENV)
    if not endpoint:
        return None
    return f"{endpoint.rstrip('/')}/openai/v1"


# Google Vertex AI is special-cased: OpenAI-compatible endpoint whose URL is
# computed from region+project, and whose auth is a *short-lived* Google OAuth
# access token (gcloud auth print-access-token), not a static API key — so it
# must be supplied at runtime via env.
_VERTEX_TOKEN_ENV = "GOOGLE_VERTEX_ACCESS_TOKEN"


def _vertex_region() -> str:
    """Resolve the Vertex region: RCG_LLM_REGION, then VERTEX_LOCATION, default us-central1."""
    return (
        os.environ.get("RCG_LLM_REGION")
        or os.environ.get("VERTEX_LOCATION")
        or "us-central1"
    )


def _vertex_base_url(project: str) -> str:
    """Compute the Vertex OpenAI-compatible base URL (RCG_LLM_BASE_URL wins)."""
    override = os.environ.get("RCG_LLM_BASE_URL")
    if override:
        return override
    region = _vertex_region()
    return (
        f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}"
        f"/locations/{region}/endpoints/openapi"
    )


def _vertex_project() -> str | None:
    """Resolve the Vertex project: VERTEX_PROJECT, then GOOGLE_CLOUD_PROJECT."""
    return os.environ.get("VERTEX_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")


def _resolve_vertex_token() -> str | None:
    """Resolve the Vertex access token: GOOGLE_VERTEX_ACCESS_TOKEN, then RCG_LLM_API_KEY."""
    return os.environ.get(_VERTEX_TOKEN_ENV) or os.environ.get("RCG_LLM_API_KEY")

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
    if name == "bedrock":
        return _build_bedrock_provider()
    if name == "azure":
        return _build_azure_provider()
    if name == "vertex":
        return _build_vertex_provider()
    if name in _OPENAI_PRESETS:
        return _build_openai_provider(name)
    typer.echo(f"error: unknown provider {name!r}", err=True)
    raise typer.Exit(code=2)


def _build_bedrock_provider() -> LLMProvider:
    """Build an OpenAI-compatible provider pointed at Amazon Bedrock.

    Region-derived base_url (or RCG_LLM_BASE_URL override) + a Bedrock API key
    as the bearer token. Special-cased because the URL depends on a region.
    """
    from rcg.extractors.openai_provider import OpenAICompatibleProvider

    api_key = _resolve_bedrock_key()
    if not api_key:
        typer.echo(
            f"error: {_BEDROCK_KEY_ENV} is not set (also tried RCG_LLM_API_KEY). "
            "Use --provider mock for an offline demo.",
            err=True,
        )
        raise typer.Exit(code=2)
    model = os.environ.get("RCG_LLM_MODEL") or _BEDROCK_DEFAULT_MODEL
    return OpenAICompatibleProvider(
        model_id=model, base_url=_bedrock_base_url(), api_key=api_key
    )


def _build_azure_provider() -> LLMProvider:
    """Build an OpenAI-compatible provider pointed at Azure AI Foundry / Azure OpenAI.

    Per-resource endpoint → ``<endpoint>/openai/v1`` base URL, an Azure OpenAI API
    key, and the *deployment name* (from RCG_LLM_MODEL) as the model. Special-cased
    because both the URL and the required deployment name come from the environment.
    """
    from rcg.extractors.openai_provider import OpenAICompatibleProvider

    base_url = _azure_base_url()
    if not base_url:
        typer.echo(
            f"error: {_AZURE_ENDPOINT_ENV} is not set (e.g. "
            "https://myres.openai.azure.com). Use --provider mock for an offline demo.",
            err=True,
        )
        raise typer.Exit(code=2)
    api_key = os.environ.get(_AZURE_KEY_ENV) or os.environ.get("RCG_LLM_API_KEY")
    if not api_key:
        typer.echo(
            f"error: {_AZURE_KEY_ENV} is not set (also tried RCG_LLM_API_KEY). "
            "Use --provider mock for an offline demo.",
            err=True,
        )
        raise typer.Exit(code=2)
    model = os.environ.get("RCG_LLM_MODEL")
    if not model:
        typer.echo(
            "error: azure requires RCG_LLM_MODEL set to your Azure deployment name "
            "(there is no default). Use --provider mock for an offline demo.",
            err=True,
        )
        raise typer.Exit(code=2)
    return OpenAICompatibleProvider(model_id=model, base_url=base_url, api_key=api_key)


def _build_vertex_provider() -> LLMProvider:
    """Build an OpenAI-compatible provider pointed at Google Vertex AI.

    Region+project-derived base URL, a short-lived Google OAuth access token as the
    bearer, and a required model id (RCG_LLM_MODEL, e.g. google/gemini-2.5-flash).
    Special-cased because the URL and a runtime-only token come from the environment.
    """
    from rcg.extractors.openai_provider import OpenAICompatibleProvider

    project = _vertex_project()
    if not project:
        typer.echo(
            "error: VERTEX_PROJECT is not set (also tried GOOGLE_CLOUD_PROJECT). "
            "Use --provider mock for an offline demo.",
            err=True,
        )
        raise typer.Exit(code=2)
    token = _resolve_vertex_token()
    if not token:
        typer.echo(
            f"error: {_VERTEX_TOKEN_ENV} is not set (also tried RCG_LLM_API_KEY). "
            "It is a short-lived token from `gcloud auth print-access-token`. "
            "Use --provider mock for an offline demo.",
            err=True,
        )
        raise typer.Exit(code=2)
    model = os.environ.get("RCG_LLM_MODEL")
    if not model:
        typer.echo(
            "error: vertex requires RCG_LLM_MODEL set to a model id "
            "(e.g. google/gemini-2.5-flash); there is no default. "
            "Use --provider mock for an offline demo.",
            err=True,
        )
        raise typer.Exit(code=2)
    return OpenAICompatibleProvider(
        model_id=model, base_url=_vertex_base_url(project), api_key=token
    )


def _build_openai_provider(name: str) -> LLMProvider:
    """Build an OpenAI-compatible provider from a named preset."""
    from rcg.extractors.openai_provider import OpenAICompatibleProvider

    preset = _OPENAI_PRESETS[name]
    key_env = str(preset["key_env"])
    api_key = _resolve_openai_key(key_env)
    if not api_key:
        typer.echo(
            f"error: {key_env} is not set (also tried RCG_LLM_API_KEY). "
            "Use --provider mock for an offline demo.",
            err=True,
        )
        raise typer.Exit(code=2)
    base_url = os.environ.get("RCG_LLM_BASE_URL") or preset["base_url"]
    model = os.environ.get("RCG_LLM_MODEL") or str(preset["model"])
    return OpenAICompatibleProvider(model_id=model, base_url=base_url, api_key=api_key)


def _build_judge(provider_name: str) -> SemanticJudge:
    if provider_name in {"anthropic", "auto"} and os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicJudge()
    if provider_name == "bedrock":
        api_key = _resolve_bedrock_key()
        if api_key:
            model = os.environ.get("RCG_LLM_MODEL") or _BEDROCK_DEFAULT_MODEL
            return OpenAICompatibleJudge(
                model_id=model, base_url=_bedrock_base_url(), api_key=api_key
            )
        return MockJudge()
    if provider_name == "azure":
        az_base_url = _azure_base_url()
        az_key = os.environ.get(_AZURE_KEY_ENV) or os.environ.get("RCG_LLM_API_KEY")
        az_model = os.environ.get("RCG_LLM_MODEL")
        if az_base_url and az_key and az_model:
            return OpenAICompatibleJudge(
                model_id=az_model, base_url=az_base_url, api_key=az_key
            )
        return MockJudge()
    if provider_name == "vertex":
        vx_project = _vertex_project()
        vx_token = _resolve_vertex_token()
        vx_model = os.environ.get("RCG_LLM_MODEL")
        if vx_project and vx_token and vx_model:
            return OpenAICompatibleJudge(
                model_id=vx_model, base_url=_vertex_base_url(vx_project), api_key=vx_token
            )
        return MockJudge()
    if provider_name in _OPENAI_PRESETS:
        preset = _OPENAI_PRESETS[provider_name]
        api_key = _resolve_openai_key(str(preset["key_env"]))
        if api_key:
            base_url = os.environ.get("RCG_LLM_BASE_URL") or preset["base_url"]
            model = os.environ.get("RCG_LLM_MODEL") or str(preset["model"])
            return OpenAICompatibleJudge(model_id=model, base_url=base_url, api_key=api_key)
    return MockJudge()


def _build_benchmark_judge(kind: str) -> SemanticJudge:
    """Resolve the explicit --judge choice for the benchmark command."""
    if kind == "mock":
        return MockJudge()
    if kind == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            typer.echo(
                "error: ANTHROPIC_API_KEY is not set. Use --judge mock for offline runs.",
                err=True,
            )
            raise typer.Exit(code=2)
        return AnthropicJudge()
    if kind == "bedrock":
        api_key = _resolve_bedrock_key()
        if not api_key:
            typer.echo(
                f"error: {_BEDROCK_KEY_ENV} is not set (also tried RCG_LLM_API_KEY). "
                "Use --judge mock for offline runs.",
                err=True,
            )
            raise typer.Exit(code=2)
        model = os.environ.get("RCG_LLM_MODEL") or _BEDROCK_DEFAULT_MODEL
        return OpenAICompatibleJudge(
            model_id=model, base_url=_bedrock_base_url(), api_key=api_key
        )
    if kind == "azure":
        az_base_url = _azure_base_url()
        if not az_base_url:
            typer.echo(
                f"error: {_AZURE_ENDPOINT_ENV} is not set. Use --judge mock for offline runs.",
                err=True,
            )
            raise typer.Exit(code=2)
        az_key = os.environ.get(_AZURE_KEY_ENV) or os.environ.get("RCG_LLM_API_KEY")
        if not az_key:
            typer.echo(
                f"error: {_AZURE_KEY_ENV} is not set (also tried RCG_LLM_API_KEY). "
                "Use --judge mock for offline runs.",
                err=True,
            )
            raise typer.Exit(code=2)
        az_model = os.environ.get("RCG_LLM_MODEL")
        if not az_model:
            typer.echo(
                "error: azure requires RCG_LLM_MODEL set to your Azure deployment name. "
                "Use --judge mock for offline runs.",
                err=True,
            )
            raise typer.Exit(code=2)
        return OpenAICompatibleJudge(model_id=az_model, base_url=az_base_url, api_key=az_key)
    if kind == "vertex":
        vx_project = _vertex_project()
        if not vx_project:
            typer.echo(
                "error: VERTEX_PROJECT is not set (also tried GOOGLE_CLOUD_PROJECT). "
                "Use --judge mock for offline runs.",
                err=True,
            )
            raise typer.Exit(code=2)
        vx_token = _resolve_vertex_token()
        if not vx_token:
            typer.echo(
                f"error: {_VERTEX_TOKEN_ENV} is not set (also tried RCG_LLM_API_KEY). "
                "It is a short-lived token from `gcloud auth print-access-token`. "
                "Use --judge mock for offline runs.",
                err=True,
            )
            raise typer.Exit(code=2)
        vx_model = os.environ.get("RCG_LLM_MODEL")
        if not vx_model:
            typer.echo(
                "error: vertex requires RCG_LLM_MODEL set to a model id "
                "(e.g. google/gemini-2.5-flash). Use --judge mock for offline runs.",
                err=True,
            )
            raise typer.Exit(code=2)
        return OpenAICompatibleJudge(
            model_id=vx_model, base_url=_vertex_base_url(vx_project), api_key=vx_token
        )
    if kind in _OPENAI_PRESETS:
        preset = _OPENAI_PRESETS[kind]
        key_env = str(preset["key_env"])
        api_key = _resolve_openai_key(key_env)
        if not api_key:
            typer.echo(
                f"error: {key_env} is not set (also tried RCG_LLM_API_KEY). "
                "Use --judge mock for offline runs.",
                err=True,
            )
            raise typer.Exit(code=2)
        base_url = os.environ.get("RCG_LLM_BASE_URL") or preset["base_url"]
        model = os.environ.get("RCG_LLM_MODEL") or str(preset["model"])
        return OpenAICompatibleJudge(model_id=model, base_url=base_url, api_key=api_key)
    raise typer.BadParameter(f"unknown judge: {kind!r}")


def _build_embedder(kind: str) -> EmbeddingProvider:
    """Resolve the explicit --embedder choice for the benchmark command."""
    if kind == "hashing":
        return HashingEmbeddingProvider()
    if kind == "sentence-transformers":
        from rcg.providers.embedding import SentenceTransformerEmbeddingProvider

        return SentenceTransformerEmbeddingProvider()
    raise typer.BadParameter(f"unknown embedder: {kind!r}")


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
def explain(
    action: str = typer.Argument(..., help="Hypothetical action description."),
    path: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=True),
    scope: str = typer.Option("*", "--scope", help="Glob scope for the action."),
    provider: PROVIDER_OPT = "auto",
    strict: bool = typer.Option(
        False, "--strict", help="Exit 1 if firing rules conflict or are ambiguous."
    ),
) -> None:
    """Show which rules fire for a hypothetical action and whether they conflict."""
    from rcg.explain import explain as run_explain

    raws = discover(path)
    if not raws:
        typer.echo(f"No rule files discovered under {path}", err=True)
        raise typer.Exit(code=1)
    prov = _build_provider(provider)
    rules = extract_all(raws, prov)
    result = run_explain(rules, action, prov, scope=scope)

    typer.echo(f"Action: {result.action}")
    typer.echo(f"Action class: {result.action_class}")
    typer.echo(f"Scope: {result.scope}")
    typer.echo("")
    if result.firing:
        typer.echo(f"Firing rules ({len(result.firing)}):")
        for r in result.firing:
            typer.echo(
                f"  - [{r.directive.modality.value}] {r.directive.action} "
                f"({r.source.file})"
            )
    else:
        typer.echo("Firing rules: none")
    typer.echo("")

    findings = [*result.conflicts, *result.ambiguities]
    if findings:
        typer.echo(render_report(findings))
        typer.echo("")
    typer.echo(f"Verdict: {result.verdict}")

    if strict and findings:
        raise typer.Exit(1)
    raise typer.Exit(0)


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


@app.command()
def benchmark(
    dataset: Path | None = typer.Argument(
        None, help="JSONL labeled dataset (defaults to benchmarks/dataset.jsonl)."
    ),
    embedder: str = typer.Option("hashing", "--embedder", help="hashing|sentence-transformers"),
    judge: str = typer.Option(
        "mock",
        "--judge",
        help="mock|anthropic|deepseek|qwen|openai|openrouter|google|bedrock|azure|vertex",
    ),
    semantic: bool = typer.Option(
        True, "--semantic/--no-semantic", help="Run the semantic pass in the benchmark."
    ),
    sim_threshold: float = typer.Option(0.55, "--sim-threshold", help="Semantic similarity gate."),
    out: Path | None = typer.Option(None, "--out", help="Write the markdown table to this file."),
) -> None:
    """Run the precision/recall benchmark over a labeled dataset (exits 0)."""
    from rcg.benchmark import DEFAULT_DATASET, evaluate, load_dataset

    path = dataset if dataset is not None else DEFAULT_DATASET
    if not path.exists():
        typer.echo(
            f"error: dataset not found: {path}. Pass a DATASET path explicitly.", err=True
        )
        raise typer.Exit(code=2)

    pairs = load_dataset(path)
    report = evaluate(
        pairs,
        embedder=_build_embedder(embedder),
        judge=_build_benchmark_judge(judge),
        semantic=semantic,
        sim_threshold=sim_threshold,
    )
    markdown = report.to_markdown()
    typer.echo(markdown)
    if out is not None:
        out.write_text(markdown + "\n", encoding="utf-8")
        typer.echo(f"Wrote benchmark table to {out}", err=True)


if __name__ == "__main__":
    app()
