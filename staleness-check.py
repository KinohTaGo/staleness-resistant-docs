#!/usr/bin/env python3
"""staleness-check.py -- machine-checkable staleness for dated claims in Markdown.

Instruction files (CLAUDE.md, runbooks, onboarding docs) accumulate empirical
claims -- test counts, coverage percentages, tool inventories. They rot, and a
reader cannot distinguish a current fact from a fossil.

This tool checks two things about claims that have opted in via a tag:

  1. Age. A claim carries the date it was MEASURED, not the date the sentence
     was last edited.
  2. Checkability. A claim carries the id of a command that re-measures it. A
     claim with no such command is the more serious finding: nobody can settle
     it without reconstructing the original measurement.

Deliberately NOT done: deciding whether a claim is still TRUE by diffing command
output against the recorded text. Output formats drift and suites grow, so an
automatic verdict would be wrong often enough to train people to ignore it. With
--run this prints current output beside the claim and leaves the judgement to a
human.

Also deliberately NOT done: parsing prose to find untagged claims. Guessing which
sentences are factual assertions produces false positives until the output stops
being read. Opt-in by tag means that when this tool speaks, it is worth reading.

Markup
------
Claim (an HTML comment on or just after the line making the claim):

    - Test suite: **253 passed**, coverage **96.20%**
      <!-- measured:2026-07-28 id:pytest-count -->

Re-measurement command (a fenced block whose info string names the id):

    ```staleness-cmd:pytest-count
    .venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -1
    ```

Exit codes
----------
0  nothing exceeded the configured --fail-on level
1  findings at or above --fail-on
2  usage error
"""

from __future__ import annotations

import argparse
import datetime as _dt
import pathlib
import re
import subprocess
import sys

CLAIM_RE = re.compile(
    r"<!--\s*measured:(?P<date>\d{4}-\d{2}-\d{2})\s+id:(?P<id>[A-Za-z0-9._-]+)\s*-->"
)
FENCE_RE = re.compile(r"^```staleness-cmd:(?P<id>[A-Za-z0-9._-]+)\s*$")
FENCE_END = re.compile(r"^```\s*$")


class Claim:
    __slots__ = ("path", "line", "id", "measured", "text")

    def __init__(self, path, line, cid, measured, text):
        self.path, self.line, self.id, self.measured, self.text = (
            path, line, cid, measured, text,
        )


def parse(path: pathlib.Path):
    """Return (claims, commands) found in one file."""
    claims: list[Claim] = []
    commands: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        print(f"{path}: cannot read: {exc}", file=sys.stderr)
        return claims, commands

    i = 0
    while i < len(lines):
        line = lines[i]

        m = CLAIM_RE.search(line)
        if m:
            # The claim text is this line minus the comment; if that is empty the
            # comment sits on its own line and the claim is the line above.
            text = CLAIM_RE.sub("", line).strip()
            if not text and i > 0:
                text = lines[i - 1].strip()
            try:
                measured = _dt.date.fromisoformat(m.group("date"))
            except ValueError:
                print(f"{path}:{i+1}: invalid date {m.group('date')!r}", file=sys.stderr)
                i += 1
                continue
            claims.append(Claim(path, i + 1, m.group("id"), measured, text))

        f = FENCE_RE.match(line)
        if f:
            body, j = [], i + 1
            while j < len(lines) and not FENCE_END.match(lines[j]):
                body.append(lines[j])
                j += 1
            commands[f.group("id")] = "\n".join(body).strip()
            i = j

        i += 1

    return claims, commands


def iter_markdown(targets: list[str]):
    for t in targets:
        p = pathlib.Path(t)
        if p.is_dir():
            yield from sorted(p.rglob("*.md"))
        elif p.is_file():
            yield p
        else:
            print(f"{t}: no such file or directory", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Flag dated claims in Markdown that are stale or uncheckable.",
    )
    ap.add_argument("targets", nargs="+", help="Markdown files or directories")
    ap.add_argument(
        "--max-age", type=int, default=30, metavar="DAYS",
        help="claims measured more than DAYS ago are stale (default: 30)",
    )
    ap.add_argument(
        "--run", action="store_true",
        help="execute each re-measurement command and print current output",
    )
    ap.add_argument(
        "--fail-on", choices=("never", "uncheckable", "stale"), default="uncheckable",
        help="exit 1 when findings reach this level (default: uncheckable)",
    )
    ap.add_argument(
        "--today", metavar="YYYY-MM-DD",
        help="treat this as today's date (for testing)",
    )
    args = ap.parse_args()

    today = _dt.date.fromisoformat(args.today) if args.today else _dt.date.today()

    all_claims: list[Claim] = []
    all_commands: dict[str, str] = {}
    files = 0
    for path in iter_markdown(args.targets):
        files += 1
        claims, commands = parse(path)
        all_claims.extend(claims)
        for cid, body in commands.items():
            all_commands.setdefault(cid, body)

    if files == 0:
        print("no Markdown files found", file=sys.stderr)
        return 2

    stale = uncheckable = 0
    for c in sorted(all_claims, key=lambda c: (str(c.path), c.line)):
        age = (today - c.measured).days
        has_cmd = c.id in all_commands

        if not has_cmd:
            status, uncheckable = "UNCHECKABLE", uncheckable + 1
            detail = "no staleness-cmd block"
        elif age > args.max_age:
            status, stale = "STALE", stale + 1
            detail = f"measured {c.measured}  ({age} days ago)"
        else:
            status = "ok"
            detail = f"measured {c.measured}  ({age} days ago)"

        print(f"{c.path}:{c.line}  id={c.id:<22} {detail:<34} {status}")
        if c.text:
            print(f"    claim: {c.text}")

        if args.run and has_cmd:
            cmd = all_commands[c.id]
            print(f"    $ {cmd}")
            try:
                proc = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=300,
                )
                out = (proc.stdout + proc.stderr).strip() or "(no output)"
            except subprocess.TimeoutExpired:
                out = "(timed out after 300s)"
            for ln in out.splitlines():
                print(f"    | {ln}")
            print("    ^ compare against the claim above; this tool does not judge.")

    orphans = sorted(set(all_commands) - {c.id for c in all_claims})
    for cid in orphans:
        print(f"(warning) staleness-cmd:{cid} has no claim referring to it")

    print(
        f"\n{len(all_claims)} claim(s) in {files} file(s): "
        f"{stale} stale, {uncheckable} uncheckable (threshold: {args.max_age} days)"
    )

    if args.fail_on == "stale" and (stale or uncheckable):
        return 1
    if args.fail_on == "uncheckable" and uncheckable:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
