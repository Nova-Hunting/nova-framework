import os
import subprocess
import sys

LLM_ENV_VARS = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_LLM_MODEL",
    "ANTHROPIC_MODEL",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_LLM_MODEL",
    "AZURE_OPENAI_MODEL",
    "GROQ_API_KEY",
    "GROQ_LLM_MODEL",
    "GROQ_MODEL",
    "NOVA_LLM_MODEL",
    "NOVA_LLM_PROVIDER",
    "OLLAMA_HOST",
    "OLLAMA_LLM_MODEL",
    "OLLAMA_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_LLM_MODEL",
    "OPENAI_MODEL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_LLM_MODEL",
    "OPENROUTER_MODEL",
}


def _env_without_llm_config():
    env = os.environ.copy()
    for env_name in LLM_ENV_VARS:
        env.pop(env_name, None)
    return env


def _write_llm_rule(tmp_path):
    rule_file = tmp_path / "llm_rule.nov"
    rule_file.write_text(
        """
rule CliConfigLLMRule
{
    keywords:
        $inject = "ignore previous instructions"

    llm:
        $llm_check = "Detect unsafe content" (0.7)

    condition:
        keywords.$inject or llm.$llm_check
}
""",
        encoding="utf-8",
    )
    return rule_file


def test_novarun_help_lists_openrouter():
    result = subprocess.run(
        [sys.executable, "-m", "nova.novarun", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "openrouter" in result.stdout


def test_novarun_keyword_rule_matches_without_llm(tmp_path):
    rule_file = tmp_path / "keyword_rule.nov"
    rule_file.write_text(
        """
rule CliKeywordRule
{
    meta:
        description = "CLI keyword smoke test"

    keywords:
        $inject = "ignore previous instructions"

    condition:
        keywords.$inject
}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nova.novarun",
            "--rule",
            str(rule_file),
            "--prompt",
            "please ignore previous instructions",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "MATCHED" in result.stdout


def test_novarun_keyword_rule_non_match_returns_one(tmp_path):
    rule_file = tmp_path / "keyword_rule.nov"
    rule_file.write_text(
        """
rule CliKeywordRule
{
    meta:
        description = "CLI keyword smoke test"

    keywords:
        $inject = "ignore previous instructions"

    condition:
        keywords.$inject
}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nova.novarun",
            "--rule",
            str(rule_file),
            "--llm",
            "openrouter",
            "--prompt",
            "normal product question",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "NOT MATCHED" in result.stdout


def test_novarun_single_rule_file_allows_leading_comments(tmp_path):
    rule_file = tmp_path / "keyword_rule_with_header.nov"
    rule_file.write_text(
        """
// Rule pack header
# Compatibility note

rule CliHeaderRule
{
    keywords:
        $inject = "ignore previous instructions"

    condition:
        keywords.$inject
}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nova.novarun",
            "--rule",
            str(rule_file),
            "--prompt",
            "please ignore previous instructions",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "CliHeaderRule" in result.stdout


def test_novarun_single_rule_file_ignores_rule_words_in_metadata(tmp_path):
    rule_file = tmp_path / "keyword_rule_with_rule_word.nov"
    rule_file.write_text(
        """
rule CliMetadataRuleWord
{
    meta:
        description = "This rule mentions rule in metadata"

    keywords:
        $inject = "ignore previous instructions"

    condition:
        keywords.$inject
}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nova.novarun",
            "--rule",
            str(rule_file),
            "--prompt",
            "please ignore previous instructions",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "CliMetadataRuleWord" in result.stdout


def test_novarun_multi_rule_file_matches_valid_rules(tmp_path):
    rule_file = tmp_path / "multi_keyword_rules.nov"
    rule_file.write_text(
        """
rule CliFirstRule
{
    keywords:
        $alpha = "alpha"

    condition:
        keywords.$alpha
}

rule CliSecondRule
{
    keywords:
        $beta = "beta"

    condition:
        keywords.$beta
}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nova.novarun",
            "--rule",
            str(rule_file),
            "--prompt",
            "beta",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Found 2" in result.stdout
    assert "CliSecondRule" in result.stdout


def test_novarun_multi_rule_file_fails_closed_on_malformed_rule(tmp_path):
    rule_file = tmp_path / "broken_multi_rules.nov"
    rule_file.write_text(
        """
rule CliValidRule
{
    keywords:
        $alpha = "alpha"

    condition:
        keywords.$alpha
}

rule CliBrokenRule
{
    keywords:
        $bad = [

    condition:
        keywords.$bad
}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nova.novarun",
            "--rule",
            str(rule_file),
            "--prompt",
            "alpha",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Error parsing rule file" in result.stdout
    assert "Invalid keyword pattern" in result.stdout
    assert "MATCHED" not in result.stdout


def test_novarun_multi_rule_file_rejects_duplicate_rule_names(tmp_path):
    rule_file = tmp_path / "duplicate_multi_rules.nov"
    rule_file.write_text(
        """
rule CliDuplicateRule
{
    keywords:
        $alpha = "alpha"

    condition:
        keywords.$alpha
}

rule CliDuplicateRule
{
    keywords:
        $beta = "beta"

    condition:
        keywords.$beta
}
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nova.novarun",
            "--rule",
            str(rule_file),
            "--prompt",
            "alpha",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Duplicate rule name" in result.stdout
    assert "MATCHED" not in result.stdout


def test_novarun_config_supplies_llm_provider_model_and_key(tmp_path):
    rule_file = _write_llm_rule(tmp_path)
    config_file = tmp_path / "nova.ini"
    config_file.write_text(
        """
[llm]
provider = openrouter
model = meta-llama/llama-3.1-8b-instruct

[api_keys]
openrouter = test-openrouter-key
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nova.novarun",
            "--config",
            str(config_file),
            "--rule",
            str(rule_file),
            "--prompt",
            "please ignore previous instructions",
            "--verbose",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_env_without_llm_config(),
    )

    assert result.returncode == 0
    assert "MATCHED" in result.stdout
    assert "openrouter" in result.stdout
    assert "meta-llama/llama-3.1-8b-instruct" in result.stdout


def test_novarun_model_environment_overrides_config_file_model(tmp_path):
    rule_file = _write_llm_rule(tmp_path)
    config_file = tmp_path / "nova.ini"
    config_file.write_text(
        """
[llm]
provider = openrouter
model = meta-llama/llama-3.1-8b-instruct

[api_keys]
openrouter = test-openrouter-key
""",
        encoding="utf-8",
    )

    env = _env_without_llm_config()
    env["OPENROUTER_MODEL"] = "google/gemini-2.5-pro"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nova.novarun",
            "--config",
            str(config_file),
            "--rule",
            str(rule_file),
            "--prompt",
            "please ignore previous instructions",
            "--verbose",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert "MATCHED" in result.stdout
    assert "google/gemini-2.5-pro" in result.stdout
    assert "meta-llama/llama-3.1-8b-instruct" not in result.stdout


def test_novarun_cli_llm_overrides_config_provider(tmp_path):
    rule_file = _write_llm_rule(tmp_path)
    config_file = tmp_path / "nova.ini"
    config_file.write_text(
        """
[llm]
provider = openai

[api_keys]
openrouter = test-openrouter-key
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nova.novarun",
            "--config",
            str(config_file),
            "--llm",
            "openrouter",
            "--rule",
            str(rule_file),
            "--prompt",
            "please ignore previous instructions",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_env_without_llm_config(),
    )

    assert result.returncode == 0
    assert "MATCHED" in result.stdout


def test_novarun_missing_explicit_config_fails_clearly(tmp_path):
    rule_file = _write_llm_rule(tmp_path)
    missing_config = tmp_path / "missing.ini"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nova.novarun",
            "--config",
            str(missing_config),
            "--rule",
            str(rule_file),
            "--prompt",
            "please ignore previous instructions",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_env_without_llm_config(),
    )

    assert result.returncode == 1
    assert "Error applying config file" in result.stdout
    assert str(missing_config) in result.stdout


def test_novarun_malformed_explicit_config_fails_clearly(tmp_path):
    rule_file = _write_llm_rule(tmp_path)
    config_file = tmp_path / "nova.json"
    config_file.write_text("{", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nova.novarun",
            "--config",
            str(config_file),
            "--rule",
            str(rule_file),
            "--prompt",
            "please ignore previous instructions",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_env_without_llm_config(),
    )

    assert result.returncode == 1
    assert "Error applying config file" in result.stdout
    assert str(config_file) in result.stdout


def test_novarun_prints_fail_closed_evaluation_warnings(capsys):
    from nova.novarun import print_result

    print_result(
        {
            "matched": False,
            "rule_name": "CliWarningRule",
            "meta": {},
            "matching_keywords": {},
            "matching_semantics": {},
            "matching_llm": {},
            "debug": {
                "evaluation_warnings": [
                    "Rule 'CliWarningRule' failed closed because llm.$safe evaluation errored: provider unavailable"
                ],
            },
        },
        "warning_rule.nov",
        "unsafe prompt",
        verbose=False,
    )

    captured = capsys.readouterr()

    assert "NOT MATCHED" in captured.out
    assert "Evaluation Warnings" in captured.out
    assert "provider unavailable" in captured.out
