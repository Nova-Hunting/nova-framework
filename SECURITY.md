# Security Policy

NOVA is a production security-adjacent engine. Treat findings that could affect scanner correctness, rule evaluation, package integrity, secret handling, or remote provider interactions as security-sensitive.

## Supported Versions

Security fixes are handled for:

- the `main` branch
- the latest published `nova-hunting` package version

Older versions may not receive backported fixes.

## Reporting a Vulnerability

Do not report security vulnerabilities in public GitHub issues.

Use one of these private channels instead:

- GitHub Security Advisories for this repository, if available
- email: `contact@securitybreak.io`

Please include:

- affected version or commit
- reproduction steps or proof of concept
- expected and actual behavior
- impact assessment
- whether the issue is already public or being actively exploited

## Response Expectations

Maintainers will make a best effort to:

- acknowledge reports within 7 days
- validate severity and scope before public disclosure
- coordinate fixes before publishing details
- credit reporters when requested and appropriate

## Scope

In scope:

- prompt/rule evaluation bypasses caused by engine bugs
- unsafe parsing, regex, or condition evaluation behavior
- crashes or denial of service from untrusted rules or prompts
- leaking API keys, prompts, model responses, or log-buffer contents
- package, CI, or release integrity issues

Out of scope:

- vulnerabilities in third-party model providers
- malicious rules authored by a user and intentionally executed in their own environment
- reports that require access to secrets, private systems, or accounts not owned by the reporter
