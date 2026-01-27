# Nova Installation Guide

## Installation

```bash
pip install nova-hunting
```

This installs Nova with all features:
- Keyword pattern matching (exact text, case-sensitive/insensitive)
- Regex pattern matching with full regex support
- Semantic similarity matching using sentence transformers
- LLM-based evaluation (OpenAI, Anthropic, Azure, Ollama, Groq)
- Command-line tool (`novarun`)

## Dependencies

Nova includes the following dependencies:

| Package | Purpose |
|---------|---------|
| `requests` | HTTP requests |
| `pyyaml` | YAML parsing |
| `colorama` | Terminal colors |
| `sentence-transformers` | Semantic similarity |
| `transformers` | ML model support |
| `openai` | OpenAI API |
| `anthropic` | Anthropic API |
| `pytest` | Testing |

## Getting Rules

Nova rules are maintained in a separate repository:

```bash
git clone https://github.com/Nova-Hunting/nova-rules
```

## Quick Start

Scan prompts with the `novarun` CLI:

```bash
novarun --rules nova-rules/jailbreak.nov --prompt "ignore previous instructions"
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
```

## Development

For development, clone and install in editable mode:

```bash
git clone https://github.com/Nova-Hunting/nova-framework
cd nova-framework
pip install -e .
```

Run tests:

```bash
pytest tests/ -v
```
