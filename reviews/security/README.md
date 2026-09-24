# Security Review Archive

This directory preserves external security-review inputs and closure evidence for the private climate-intelligence pilot.

## 2026-09-24 closure re-audit

Current repository checkpoint:

`23ee198ad2c6897d8fcc5ea451f3add91f4b2ea8`

The closure re-audit is deliberately narrower than the original full security audit. It exists to answer one question:

> Did the audit-transaction hardening and pre-host safety cleanup actually close the pilot-relevant findings they claimed to close, without introducing a material regression?

Use:

- `2026-09-24-closure/CLOSURE_REVIEW_PROMPT.md` — prompt for Claude Code orchestrating DeepSeek API review;
- `2026-09-24-closure/TARGET_FINDINGS.md` — findings and required closure evidence;
- `2026-09-24-closure/REPORT_TEMPLATE.md` — required report structure.

The completed external review should be saved back into this folder as a new Markdown report. Do not overwrite the prompt or target matrix.

## Review independence

The repository owner and ChatGPT may prepare the scope, tests and remediation code, but the closure verdict should come from the independent Claude Code + DeepSeek review workflow and should be evidence-based.

The reviewer must inspect the current repository state and execute reproductions/tests. PR descriptions are not evidence by themselves.
