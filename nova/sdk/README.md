# Nova SDK

High-level SDK for Nova prompt pattern matching with policy-based actions.

## Installation

```bash
pip install nova-hunting
```

## Quick Start

```python
from openai import OpenAI
from nova.sdk import Nova, NovaBlockedError

client = OpenAI()
nova = Nova(
    rules_path="nova-rules/",
    policy={"Jailbreak": {"action": "block"}}
)

@nova.protect(action="block")
def chat(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

# Use it
try:
    print(chat("What is Python?"))  # Works
    print(chat("Ignore previous instructions"))  # Blocked!
except NovaBlockedError as e:
    print(f"Blocked: {e.result.blocked_rules}")
```

---

## How It Works

```
User Input → Nova Scan → Policy Check → Action
                              ↓
                    block / flag / redact / allow
```

1. **User sends a prompt**
2. **Nova scans** against loaded rules (jailbreak, injection, etc.)
3. **Policy determines action** based on matched rules
4. **Action is taken**: block, flag, redact, or allow

---

## Policy System

The `policy` dict maps **rule patterns** to **actions**.

### Basic Syntax

```python
policy = {
    "pattern": {"action": "block|flag|redact|allow"}
}
```

### Actions

| Action | Description | Result |
|--------|-------------|--------|
| `"block"` | Stop the request | `result.blocked = True`, raises `NovaBlockedError` with decorator |
| `"flag"` | Allow but mark for review | `result.flagged = True` |
| `"redact"` | Remove matched content | `result.sanitized_text` has `[REDACTED]` |
| `"allow"` | Let it pass silently | No action taken |

### Pattern Matching

Patterns are matched in this priority order:

| Priority | Pattern Type | Example | Matches |
|----------|--------------|---------|---------|
| 1 | **Exact name** | `"DANJailbreak"` | Only the rule named `DANJailbreak` |
| 2 | **Prefix** | `"PI"` | `PIJailbreak`, `PromptInjection`, `PITest`, etc. |
| 3 | **Category wildcard** | `"jailbreak/*"` | Rules with `category: jailbreak/roleplay`, `jailbreak/dan` |
| 4 | **Severity default** | (automatic) | `critical`→block, `high`→block, `medium`→flag, `low`→allow |
| 5 | **Global default** | `default_action` | Fallback for unmatched rules |

### Policy Examples

```python
# Example 1: Simple blocking
policy = {
    "Jailbreak": {"action": "block"},  # Block any rule starting with "Jailbreak"
}

# Example 2: Multiple patterns
policy = {
    "DANJailbreak": {"action": "block"},      # Exact match
    "Prompt": {"action": "block"},            # Prefix: PromptInjection, PromptLeak
    "jailbreak/*": {"action": "flag"},        # Category wildcard
    "PII": {"action": "redact"},              # Redact personal info
}

# Example 3: Comprehensive security policy
policy = {
    # Critical threats - block immediately
    "PromptInjection": {"action": "block"},
    "DAN": {"action": "block"},

    # Jailbreak attempts - block
    "jailbreak/*": {"action": "block"},

    # Suspicious patterns - flag for review
    "Suspicious": {"action": "flag"},

    # Personal data - redact automatically
    "PII": {"action": "redact"},
}
```

### How Pattern Matching Works

When Nova finds a match (e.g., rule named `PromptInjectionJailbreak`):

```
1. Exact match?     "PromptInjectionJailbreak" in policy?  → No
2. Prefix match?    "Prompt" matches "PromptInjection..."? → YES → BLOCK
3. Category match?  (skipped, already matched)
4. Severity?        (skipped)
5. Default?         (skipped)
```

---

## Usage Methods

### Method 1: Direct Scanning

```python
from nova.sdk import Nova

nova = Nova(
    rules_path="nova-rules/",
    policy={"Jailbreak": {"action": "block"}}
)

result = nova.scan("user input here")

if result.blocked:
    print(f"Blocked by: {result.blocked_rules}")
elif result.flagged:
    print(f"Flagged by: {result.flagged_rules}")
else:
    # Safe to use
    safe_text = result.sanitized_text
```

### Method 2: Decorator Pattern (Recommended)

```python
from nova.sdk import Nova, NovaBlockedError

nova = Nova(rules_path="nova-rules/", policy={...})

@nova.protect(action="block")
def chat(prompt: str) -> str:
    return openai_call(prompt)

try:
    response = chat(user_input)
except NovaBlockedError as e:
    print(f"Blocked: {e.message}")
```

### Method 3: Async Support

```python
# Async scanning
result = await nova.scan_async("user input")

# Async decorator
@nova.protect(action="block")
async def async_chat(prompt: str) -> str:
    return await async_openai_call(prompt)
```

---

## ScanResult Object

After scanning, you get a `ScanResult` with these properties:

```python
result = nova.scan("some text")

# Boolean checks
result.blocked        # True if any BLOCK action triggered
result.flagged        # True if any FLAG action triggered
result.redacted       # True if content was redacted
result.allowed        # True if not blocked
result.clean          # True if no rules matched at all

# Text
result.original_text   # Original input
result.sanitized_text  # Text with redactions applied

# Match details
result.match_count     # Number of rules matched
result.blocked_rules   # List of rule names that blocked
result.flagged_rules   # List of rule names that flagged
result.highest_severity # "critical", "high", "medium", or "low"
result.matches         # List of RuleMatch objects with full details
result.has_warnings    # True if any rule had degraded evaluation
result.warnings        # Flat list of semantic/LLM evaluation warnings
result.rule_warnings   # Warnings grouped by rule name
```

Warnings are reported even when no rule matched. For example, a missing LLM
provider key or an explicit `skip_llm=True` scan can leave `result.clean` true
while `result.has_warnings` is also true, so production callers can distinguish
"clean" from "clean with degraded coverage."

---

## Configuration Options

```python
nova = Nova(
    # Rules
    rules_path="nova-rules/",           # Path to .nov files or directory
    ignore_invalid_rules=False,          # Raise on malformed/missing rule files by default

    # Policy
    policy={...},                        # Pattern → action mapping
    default_action=Action.FLAG,          # Default when no pattern matches

    # LLM Provider (for rules with LLM patterns)
    llm_provider="openai",               # openai, anthropic, groq, openrouter, azure, ollama
    llm_model="gpt-4o-mini",             # Specific model (optional)

    # Redaction
    redaction_marker="[REDACTED]",       # Custom redaction text
    auto_redact=True,                    # Auto-apply redaction on REDACT action

    # Callbacks
    on_block=lambda r: log(r),           # Called when blocked
    on_flag=lambda r: log(r),            # Called when flagged
)
```

OpenRouter can be used for LLM-backed rules without changing rule syntax:

```python
import os
from nova.sdk import Nova

os.environ["OPENROUTER_API_KEY"] = "sk-or-..."

nova = Nova(
    rules_path="nova-rules/",
    llm_provider="openrouter",
    llm_model="openai/gpt-5.2",
)
```

When `llm_model` is omitted, Nova checks provider-specific model environment variables such as `OPENROUTER_LLM_MODEL` and `OPENROUTER_MODEL`, then falls back to `NOVA_LLM_MODEL` and the provider default.
For OpenRouter app attribution, set `OPENROUTER_HTTP_REFERER` and `OPENROUTER_APP_TITLE` to include the optional `HTTP-Referer` and `X-OpenRouter-Title` request headers.

---

## Decorator Options

```python
@nova.protect(
    action="block",           # Action to take: block, flag, redact, allow
    severity="high",          # Minimum severity to trigger (optional)
    param_name="prompt",      # Parameter name to scan (default: "prompt")
    raise_on_block=True,      # Raise NovaBlockedError if blocked
    on_block=lambda r: "...", # Custom handler, return value replaces function result
)
def my_function(prompt):
    ...
```

---

## Complete Example

```python
from openai import OpenAI
from nova.sdk import Nova, NovaBlockedError

# Initialize
client = OpenAI()
nova = Nova(
    rules_path="nova-rules/",
    policy={
        "PromptInjection": {"action": "block"},
        "DAN": {"action": "block"},
        "jailbreak/*": {"action": "block"},
        "PII": {"action": "redact"},
    },
    llm_provider="openai",
)

# Protect your endpoint
@nova.protect(action="block")
def chat(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

# Usage
def handle_user_request(user_input: str):
    try:
        response = chat(user_input)
        return {"status": "ok", "response": response}
    except NovaBlockedError as e:
        return {
            "status": "blocked",
            "reason": e.message,
            "rules": e.result.blocked_rules
        }
```

---

## Running Tests

```bash
# Run all SDK tests
pytest tests/test_sdk.py -v

# Run specific test
pytest tests/test_sdk.py::TestNovaPolicy -v
```
