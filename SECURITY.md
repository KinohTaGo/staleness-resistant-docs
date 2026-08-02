# Security Policy

## Reporting a vulnerability

Please report security issues through
[GitHub's private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository, rather than opening a public issue.

Include what you can: affected version or commit, reproduction steps, and the impact you
observed. A partial report is more useful than none.

## Scope

These are small, dependency-free tools intended to be run locally or in CI against a
repository you control. The most likely security-relevant defects are:

- **Silent under-reporting** — a check that reports "clean" without having examined what
  it claims to have examined. This is treated as a security defect here, not a bug,
  because a checker that fails open is worse than no checker.
- Command execution paths (`staleness-check.py --run` executes commands embedded in the
  Markdown it reads — by design, and only for files you supply).

## Supported versions

The latest release on `main`.
