# LLM providers

RCG uses an LLM in two places — the **extraction** step (raw rule text → canonical
`Rule`) and the optional **semantic judge** (does this pair of rules conflict?).
Both sit behind small protocols, so the model backend is pluggable.

RCG's LLM layer covers (a) **cloud gateways** — Amazon Bedrock, Azure AI Foundry,
Google Vertex AI; (b) **direct vendors** — Anthropic, OpenAI; (c) **aggregators** —
OpenRouter; plus the **Gemini API** (Google AI Studio), DeepSeek, Qwen, and any
OpenAI-compatible endpoint (local vLLM/Ollama). All but Anthropic ride **one
OpenAI-compatible provider class**.

Beyond Anthropic, RCG ships **one OpenAI-compatible provider class**
(`src/rcg/extractors/openai_provider.py`) that drives any endpoint speaking the
OpenAI Chat Completions API with function/tool calling: DeepSeek, Qwen (DashScope
or a local server), OpenAI itself, OpenRouter, the Gemini API, Amazon Bedrock,
Azure AI Foundry, Google Vertex AI, and local servers such as vLLM or Ollama. The
endpoint is selected purely by base URL, model, and API key.

## Install

The OpenAI-compatible providers live in an optional extra:

```bash
pip install 'rule-coherence-graph[openai]'
```

Anthropic and the offline `mock` provider need no extra.

## Provider matrix

| `--provider` | Backend | Default base URL | Default model | Key env (with fallback) |
| --- | --- | --- | --- | --- |
| `anthropic` | Anthropic Messages API | (SDK default) | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `deepseek` | DeepSeek (OpenAI-compatible) | `https://api.deepseek.com` | `deepseek-chat` | `DEEPSEEK_API_KEY` → `RCG_LLM_API_KEY` |
| `qwen` | Qwen via DashScope | `https://dashscope.aliyun.com/compatible-mode/v1` | `qwen-max` | `DASHSCOPE_API_KEY` → `RCG_LLM_API_KEY` |
| `openai` | OpenAI / any compatible endpoint | SDK default or `RCG_LLM_BASE_URL` | `gpt-4o-mini` | `OPENAI_API_KEY` → `RCG_LLM_API_KEY` |
| `openrouter` | OpenRouter aggregator | `https://openrouter.ai/api/v1` | `anthropic/claude-sonnet-4` (overridable) | `OPENROUTER_API_KEY` → `RCG_LLM_API_KEY` |
| `google` | Google Gemini API (AI Studio) | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.5-flash` | `GEMINI_API_KEY` → `GOOGLE_API_KEY` → `RCG_LLM_API_KEY` |
| `bedrock` | Amazon Bedrock (OpenAI-compatible) | `https://bedrock-runtime.<region>.amazonaws.com/openai/v1` (region from `RCG_LLM_REGION`/`AWS_REGION`/`AWS_DEFAULT_REGION`, default `us-east-1`) | `openai.gpt-oss-120b-1:0` | `AWS_BEARER_TOKEN_BEDROCK` → `RCG_LLM_API_KEY` |
| `azure` | Azure AI Foundry / Azure OpenAI | `<AZURE_OPENAI_ENDPOINT>/openai/v1` (v1 GA path; no api-version) | **model = deployment name** (required, from `RCG_LLM_MODEL`; no default) | `AZURE_OPENAI_API_KEY` → `RCG_LLM_API_KEY` |
| `vertex` | Google Vertex AI (OpenAI-compatible) | `https://<region>-aiplatform.googleapis.com/v1/projects/<project>/locations/<region>/endpoints/openapi` (region from `RCG_LLM_REGION`/`VERTEX_LOCATION`, default `us-central1`; project from `VERTEX_PROJECT`/`GOOGLE_CLOUD_PROJECT`) | **required** (from `RCG_LLM_MODEL`, e.g. `google/gemini-2.5-flash`; no default) | `GOOGLE_VERTEX_ACCESS_TOKEN` → `RCG_LLM_API_KEY` (short-lived OAuth token) |
| `mock` | Deterministic heuristics (offline) | — | — | none |
| `auto` | `anthropic` if `ANTHROPIC_API_KEY` is set, else `mock` | — | — | — |

The model for any OpenAI-compatible preset can be overridden with `RCG_LLM_MODEL`.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `RCG_LLM_BASE_URL` | Override the base URL for the generic `openai` provider (point it at a local vLLM/Ollama server). For `bedrock`, also overrides the region-derived URL (use it to pick the Mantle endpoint or another region/host). |
| `RCG_LLM_MODEL` | Override the model id for any OpenAI-compatible provider/preset. |
| `RCG_LLM_API_KEY` | Generic API-key fallback for every OpenAI-compatible preset (including `bedrock`). |
| `RCG_LLM_REGION` | Region for the `bedrock` provider's base URL. Falls back to `AWS_REGION`, then `AWS_DEFAULT_REGION`, then `us-east-1`. |
| `OPENAI_API_KEY` | Standard key the OpenAI SDK reads; used by the generic `openai` provider. |
| `DEEPSEEK_API_KEY` | Key for the `deepseek` preset. |
| `DASHSCOPE_API_KEY` | Key for the `qwen` preset. |
| `AWS_BEARER_TOKEN_BEDROCK` | Amazon Bedrock API key used as the bearer token for the `bedrock` provider (not SigV4). |
| `OPENROUTER_API_KEY` | Key for the `openrouter` aggregator preset. |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Key for the `google` (Gemini API) preset; `GEMINI_API_KEY` is tried first, then `GOOGLE_API_KEY`. |
| `AZURE_OPENAI_ENDPOINT` | Per-resource Azure endpoint (e.g. `https://myres.openai.azure.com`); RCG appends `/openai/v1`. Required for `azure`. |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key for the `azure` provider. |
| `VERTEX_PROJECT` / `GOOGLE_CLOUD_PROJECT` | GCP project for the `vertex` provider's base URL (`VERTEX_PROJECT` first). Required for `vertex`. |
| `VERTEX_LOCATION` | Region fallback for `vertex` after `RCG_LLM_REGION`; default `us-central1`. |
| `GOOGLE_VERTEX_ACCESS_TOKEN` | Short-lived Google OAuth access token (`gcloud auth print-access-token`) used as the bearer for the `vertex` provider. |

Key resolution order for each preset: explicit constructor argument → the
preset-specific env var → generic `RCG_LLM_API_KEY` → (for the generic `openai`
provider only) `OPENAI_API_KEY`. If no key is found, the CLI prints which env var
to set and reminds you that `--provider mock` works offline.

## Examples

```bash
# DeepSeek
export DEEPSEEK_API_KEY=sk-...
rcg check ./rules --provider deepseek

# Qwen (DashScope)
export DASHSCOPE_API_KEY=sk-...
rcg check ./rules --provider qwen

# OpenAI
export OPENAI_API_KEY=sk-...
rcg check ./rules --provider openai

# A local OpenAI-compatible server (Ollama, vLLM, ...)
export RCG_LLM_BASE_URL=http://localhost:11434/v1
export RCG_LLM_API_KEY=ollama          # most local servers accept any token
export RCG_LLM_MODEL=qwen2.5:7b
rcg check ./rules --provider openai
```

### OpenRouter

[OpenRouter](https://openrouter.ai) aggregates many vendors behind one
OpenAI-compatible API. Models use a `vendor/model` id:

```bash
export OPENROUTER_API_KEY=sk-or-...
rcg check ./rules --provider openrouter        # default model anthropic/claude-sonnet-4

# Pick any OpenRouter model with RCG_LLM_MODEL
export RCG_LLM_MODEL=openai/gpt-4o-mini
rcg check ./rules --provider openrouter
```

### Google Gemini API (AI Studio)

The Gemini API exposes an OpenAI-compatible surface. The key is read from
`GEMINI_API_KEY`, then `GOOGLE_API_KEY`:

```bash
export GEMINI_API_KEY=...
rcg check ./rules --provider google            # default model gemini-2.5-flash
```

### Amazon Bedrock

Amazon Bedrock exposes an OpenAI-compatible Chat Completions endpoint, so RCG
drives it through the same provider class. The base URL is derived from a region
(`RCG_LLM_REGION` → `AWS_REGION` → `AWS_DEFAULT_REGION` → `us-east-1`):

```bash
export AWS_BEARER_TOKEN_BEDROCK=...        # your Bedrock API key
export RCG_LLM_REGION=us-west-2            # region where the model is enabled
export RCG_LLM_MODEL=openai.gpt-oss-120b-1:0
rcg check ./rules --provider bedrock
```

To use the newer "Mantle" endpoint (or any other host/region), set
`RCG_LLM_BASE_URL` explicitly — it always wins over the region-derived URL:

```bash
export AWS_BEARER_TOKEN_BEDROCK=...
export RCG_LLM_BASE_URL=https://bedrock-mantle.us-west-2.api.aws/v1
rcg check ./rules --provider bedrock
```

Caveats:

* **Model availability is region-gated.** The OpenAI-style `gpt-oss` models
  (`openai.gpt-oss-120b-1:0`, `openai.gpt-oss-20b-1:0`) launched in `us-west-2`.
  Pick a region and model id your account has enabled.
* **Auth via the OpenAI-SDK path uses an Amazon Bedrock API key as the bearer
  token, not SigV4.** Set it in `AWS_BEARER_TOKEN_BEDROCK` (or the generic
  `RCG_LLM_API_KEY`).

### Azure AI Foundry / Azure OpenAI

Azure uses the OpenAI SDK against a per-resource endpoint, and the "model" is the
**deployment name** you created in your Azure resource. RCG targets the modern v1
GA path (`<endpoint>/openai/v1`), so no `api-version` query parameter is needed:

```bash
export AZURE_OPENAI_ENDPOINT=https://<res>.openai.azure.com   # trailing slash optional
export AZURE_OPENAI_API_KEY=...
export RCG_LLM_MODEL=<deployment-name>        # NOT a model id — your deployment name
rcg check ./rules --provider azure
```

Caveat: `RCG_LLM_MODEL` is the **deployment name**, not a model id (e.g. your
deployment of `gpt-4o`), and it is required — there is no default. Set
`RCG_LLM_BASE_URL` to override the computed `<endpoint>/openai/v1` URL.

### Google Vertex AI

Vertex AI exposes an OpenAI-compatible endpoint whose URL is built from your
region and project. Auth is a **short-lived Google OAuth access token**, not a
static API key:

```bash
export VERTEX_PROJECT=...                      # or GOOGLE_CLOUD_PROJECT
export RCG_LLM_REGION=us-central1              # or VERTEX_LOCATION; default us-central1
export GOOGLE_VERTEX_ACCESS_TOKEN=$(gcloud auth print-access-token)
export RCG_LLM_MODEL=google/gemini-2.5-flash  # required; no default
rcg check ./rules --provider vertex
```

> **Caveat (important):** the access token from `gcloud auth print-access-token`
> is **short-lived (~1 hour)**. Regenerate it for long runs, or it will expire
> mid-run. For production, use a service-account flow (e.g. a workload-identity
> or service-account credential that mints fresh tokens) and feed the resulting
> token into `GOOGLE_VERTEX_ACCESS_TOKEN` (or `RCG_LLM_API_KEY`). Set
> `RCG_LLM_BASE_URL` to override the computed endpoint URL.

The same provider names work for the semantic judge — run `rcg check ./rules
--semantic --provider deepseek` and, when the preset's key is set, the judge uses
the OpenAI-compatible endpoint too (otherwise it falls back to the offline mock
judge). The benchmark accepts
`--judge deepseek|qwen|openai|openrouter|google|bedrock|azure|vertex` as well.

## Caveat: structured-output reliability

RCG relies on **forced function/tool calling** for structured extraction. Hosted
endpoints (DeepSeek, Qwen, OpenAI, Amazon Bedrock's `gpt-oss` models) support
this well. The provider also
**validates the returned arguments and retries once** with an explicit nudge if
the first response has no tool call or returns incomplete/unparseable JSON.

Reliability still varies by endpoint: very weak local models may fail to emit a
clean tool call even after the retry, in which case extraction raises a clear
error — prefer a stronger model for the extraction step.
