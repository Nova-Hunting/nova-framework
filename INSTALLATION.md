# Nova Installation Guide

## Installation

```bash
pip install nova-hunting
```

This installs Nova with the core engine:
- Keyword pattern matching (exact text, case-sensitive/insensitive)
- Regex pattern matching with full regex support
- LLM-based evaluation (OpenAI, Anthropic, Azure, Ollama, Groq, OpenRouter)
- Command-line tool (`novarun`)

Semantic similarity uses a heavier ML dependency stack. Install it explicitly when you need `semantics:` rules:

```bash
pip install "nova-hunting[semantic]"
```

## Dependencies

Nova includes the following dependencies:

| Package | Purpose |
|---------|---------|
| `requests` | Provider HTTP requests |
| `colorama` | Terminal colors |
| `sentence-transformers` | Semantic similarity (`semantic` extra) |
| `transformers` | ML model support (`semantic` extra) |
| `pyyaml` | Test and CI workflow validation (`test` extra) |

OpenAI, Anthropic, Azure, Groq, Ollama, and OpenRouter evaluation is implemented through HTTP clients in Nova itself; the standard package does not install provider SDKs.

Testing and documentation dependencies are optional extras:

```bash
pip install "nova-hunting[test]"
pip install "nova-hunting[docs]"
pip install "nova-hunting[semantic]"
pip install "nova-hunting[security]"
pip install "nova-hunting[dev]"
```

## Getting Rules

Nova rules are maintained in a separate repository:

```bash
git clone https://github.com/Nova-Hunting/nova-rules
```

## Quick Start

Scan prompts with the `novarun` CLI:

```bash
novarun --rule nova-rules/jailbreak.nov --prompt "ignore previous instructions"
```

## Rule Types

Nova supports three types of pattern matching in rules:

### Keywords
Exact text or regex patterns:
```yaml
keywords:
    $malware = "malware"
    $regex_pattern = /hack(ing|er)/i
```

### Semantics
Semantic similarity matching with configurable thresholds:
```yaml
semantics:
    $threat = "threatening behavior" (0.7)
```

### LLM
LLM-based evaluation using natural language:
```yaml
llm:
    $analysis = "Analyze if this is malicious" (0.8)
```

## Environment Variables

For LLM evaluation, set your API keys:

```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export AZURE_OPENAI_API_KEY="..."
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com"
export GROQ_API_KEY="gsk_..."
export OPENROUTER_API_KEY="sk-or-..."
```

For local Ollama, set `OLLAMA_HOST` if it is not available at `http://localhost:11434`.

Provider-specific model overrides are supported with `OPENAI_LLM_MODEL`, `ANTHROPIC_LLM_MODEL`, `AZURE_OPENAI_LLM_MODEL`, `GROQ_LLM_MODEL`, `OLLAMA_LLM_MODEL`, and `OPENROUTER_LLM_MODEL`. Provider aliases such as `OPENAI_MODEL`, `ANTHROPIC_MODEL`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_MODEL`, `GROQ_MODEL`, `OLLAMA_MODEL`, and `OPENROUTER_MODEL` are also accepted, with `NOVA_LLM_MODEL` as a shared fallback.

OpenRouter app attribution headers are optional. Set `OPENROUTER_HTTP_REFERER` and `OPENROUTER_APP_TITLE` to send `HTTP-Referer` and `X-OpenRouter-Title` with OpenRouter requests.

The CLI also accepts a config file for provider defaults and credentials:

```ini
[llm]
provider = openrouter
model = openai/gpt-5.2

[api_keys]
openrouter = sk-or-...
```

```bash
novarun --config nova.ini --rule rules/jailbreak.nov --prompt "ignore previous instructions"
```

Explicit `--llm` and `--model` flags override file values. Environment variables such as `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, and `NOVA_LLM_MODEL` override file credentials and model settings. When `--config` is provided, Nova fails fast if the file is missing or malformed.

## Development

For development, clone and install in editable mode:

```bash
git clone https://github.com/Nova-Hunting/nova-framework
cd nova-framework
pip install -e ".[dev]"
```

Run tests:

```bash
python -m ruff check nova tests scripts
python -m compileall -q nova tests scripts
python -m pytest -q
python scripts/audit_dependencies.py
python scripts/check_secrets.py
python -m build
python -m twine check dist/*
python scripts/verify_artifacts.py
python scripts/smoke_wheel.py
```

## Troubleshooting

**`semantics:` rules report degraded coverage or fail closed.**
The semantic ML stack is an optional extra. Install it with `pip install "nova-hunting[semantic]"` (requires Python 3.10+). The first semantic scan downloads the embedding model, which needs network access.

**`ValueError: OPENAI_API_KEY not set ...` (or the equivalent for another provider).**
Rules with `llm:` patterns need credentials for the provider selected with `--llm`. Export the matching key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`) or pass a config file with `--config`. Nova intentionally does not fall back to another provider.

**`Could not connect to Ollama at http://localhost:11434`.**
Start the Ollama service (`ollama serve`) or point `OLLAMA_HOST` at the correct host and port.

**`novarun --config` fails with "missing or malformed".**
When `--config` is passed explicitly, Nova fails fast rather than silently using defaults. Check the INI syntax against the example above and confirm the file path.

**A rule fails to parse with `NovaParserError`.**
The parser fails closed on unknown sections, duplicate or malformed variable names, and conditions referencing undefined variables. The error message includes the rule number and source file. Validate new rules with a keyword-only scan first: `novarun --rule myrule.nov --prompt "test"`.

**The CLI feels slow on keyword-only rules.**
Keyword-only scans do not need ML or LLM dependencies and skip them entirely. If startup is slow, check that you are not importing the `semantic` stack elsewhere; `novarun --help` and keyword scans avoid importing `transformers`/`torch`.

For architecture details, see [ARCHITECTURE.md](ARCHITECTURE.md).
