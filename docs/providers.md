# LLM providers

RCG uses an LLM in two places — the **extraction** step (raw rule text → canonical
`Rule`) and the optional **semantic judge** (does this pair of rules conflict?).
Both sit behind small protocols, so the model backend is pluggable.

Beyond Anthropic, RCG ships **one OpenAI-compatible provider class**
(`src/rcg/extractors/openai_provider.py`) that drives any endpoint speaking the
OpenAI Chat Completions API with function/tool calling: DeepSeek, Qwen (DashScope
or a local server), OpenAI itself, Amazon Bedrock, and local servers such as vLLM
or Ollama. The endpoint is selected purely by base URL, model, and API key.

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
| `bedrock` | Amazon Bedrock (OpenAI-compatible) | `https://bedrock-runtime.<region>.amazonaws.com/openai/v1` (region from `RCG_LLM_REGION`/`AWS_REGION`/`AWS_DEFAULT_REGION`, default `us-east-1`) | `openai.gpt-oss-120b-1:0` | `AWS_BEARER_TOKEN_BEDROCK` → `RCG_LLM_API_KEY` |
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

The same provider names work for the semantic judge — run `rcg check ./rules
--semantic --provider deepseek` and, when the preset's key is set, the judge uses
the OpenAI-compatible endpoint too (otherwise it falls back to the offline mock
judge). The benchmark accepts `--judge deepseek|qwen|openai|bedrock` as well.

## Caveat: structured-output reliability

RCG relies on **forced function/tool calling** for structured extraction. Hosted
endpoints (DeepSeek, Qwen, OpenAI, Amazon Bedrock's `gpt-oss` models) support
this well. The provider also
**validates the returned arguments and retries once** with an explicit nudge if
the first response has no tool call or returns incomplete/unparseable JSON.

Reliability still varies by endpoint: very weak local models may fail to emit a
clean tool call even after the retry, in which case extraction raises a clear
error — prefer a stronger model for the extraction step.
