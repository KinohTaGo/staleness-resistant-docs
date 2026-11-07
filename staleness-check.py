#!/usr/bin/env python3
"""staleness-check.py -- machine-checkable staleness for dated claims in Markdown.

Instruction files (CLAUDE.md, runbooks, onboarding docs) accumulate empirical
claims -- test counts, coverage percentages, tool inventories. They rot, and a
reader cannot distinguish a current fact from a fossil.

This tool checks claims that have opted in via a tag. Untagged prose is never
parsed: guessing which sentences are factual assertions produces false
positives until the output stops being read.

Two tag forms
-------------
Short form (v0.1, still supported). Age is judged against --max-age:

    - Test suite: **253 passed**  <!-- measured:2026-07-28 id:pytest-count -->

Full form (v0.2). Each claim carries its own time-to-live, and may opt in to an
exact comparison of the re-measured output:

    <!-- staleness-check: id=ruff-status date=2026-11-01 ttl=14d value="0" -->

  id          pairs the claim with a ```staleness-cmd:<id>``` block
  date        the date the claim was MEASURED (not when the sentence was edited)
  ttl         <N>d -- how long this particular claim is trusted
  value       optional; the expected stdout of the command, compared exactly
              (outer whitespace stripped) when --run is given
  timeout     optional; <N>s, per-claim command timeout
  defer_exec  optional; 1 = while the claim is younger than its ttl, do not run
              its command even under --run (for expensive re-measurements)

A whole tag must fit on one line. A value must not contain the text "-->".

Re-measurement command (a fenced block whose info string names the id; it may
be indented and may live in any scanned file):

    ```staleness-cmd:pytest-count
    .venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -1
    ```

What is reported, per claim
---------------------------
  STALE           older than its ttl (full form) or --max-age (short form)
  UNCHECKABLE     no command re-measures it, or two different command blocks
                  share its id. Nobody can settle it without reconstructing the
                  original measurement -- the more serious finding.
  MALFORMED       the tag itself is broken (missing field, bad date, bad ttl,
                  a date in the future) or a command fence is never closed.
                  A broken tag is reported, never skipped.
  VALUE-MISMATCH  --run, value= given, and the command printed something else
  VALUE-UNKNOWN   --run, but the command could not finish (timeout, exec error)
  VALUE-DEFERRED  --run, but defer_exec=1 kept the command from running

Without value=, --run prints the command's current output under the claim and
leaves the judgement to a human. value= is for claims whose command prints one
stable value (an exit code, a count). Do not put value= on a number that is
legitimately different on different machines: an exact check on it will always
be red on one of them, and "fixing" it there breaks it on the other.

Exit codes
----------
  0  claims found; nothing reached the --fail-on level
  1  claims found; at least one finding at or above --fail-on
  2  could not measure: usage error, a target missing or unreadable
  3  off: the scan worked but found no tagged claims at all. Deliberately not
     0 -- "nothing opted in" must not read as "everything is fresh".

--fail-on uncheckable (default) fails on UNCHECKABLE, MALFORMED and
VALUE-MISMATCH; --fail-on stale also fails on STALE; never only fails on 2/3.

Security: --run executes shell text found in the Markdown it reads. Run it only
on files you would run as scripts. Commands run via /bin/sh in --cwd (default:
the current directory), each in its own process group; on timeout the whole
group is killed, so a backgrounded grandchild does not outlive the check (a
process that calls setsid itself still can).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import pathlib
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__version__ = "0.2.0"

SHORT_RE = re.compile(
    r"<!--\s*measured:(?P<date>[^\s>]+)\s+id:(?P<id>[A-Za-z0-9._-]+)\s*-->"
)
FULL_RE = re.compile(r"<!--\s*staleness-check:\s*(?P<body>.*?)-->")
FIELD_RE = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')
FENCE_START = re.compile(r"^\s*```staleness-cmd:(?P<id>[A-Za-z0-9._-]+)\s*$")
FENCE_END = re.compile(r"^\s*```\s*$")
TTL_RE = re.compile(r"(\d+)d")
TIMEOUT_RE = re.compile(r"(\d+)s")
REQUIRED = ("id", "date", "ttl")


@dataclass
class Claim:
    path: pathlib.Path
    line: int
    id: str
    text: str
    measured: Optional[_dt.date] = None
    ttl: Optional[int] = None  # None = use --max-age (short form)
    value: Optional[str] = None
    timeout: Optional[int] = None
    defer: bool = False
    malformed: Optional[str] = None


@dataclass
class Command:
    id: str
    body: str
    path: pathlib.Path
    line: int


def _fields(raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in FIELD_RE.finditer(raw):
        key, val = m.group(1), m.group(2)
        if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
            val = val[1:-1].replace('\\"', '"')
        out[key] = val
    return out


def _date(raw: str) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(raw)
    except ValueError:
        return None


def _claim_text(line: str, rx: re.Pattern, lines: List[str], i: int) -> str:
    # The claim is this line minus the tag; if that is empty the tag sits on
    # its own line and the claim is the line above.
    text = rx.sub("", line).strip()
    if not text and i > 0:
        text = lines[i - 1].strip()
    return text


def parse(path: pathlib.Path) -> Tuple[List[Claim], List[Command]]:
    """Return the claims and command blocks in one file. Raises OSError."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    claims: List[Claim] = []
    commands: List[Command] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        for m in SHORT_RE.finditer(line):
            c = Claim(path, i + 1, m.group("id"), _claim_text(line, SHORT_RE, lines, i))
            c.measured = _date(m.group("date"))
            if c.measured is None:
                c.malformed = f"date {m.group('date')!r} is not YYYY-MM-DD"
            claims.append(c)

        for m in FULL_RE.finditer(line):
            f = _fields(m.group("body"))
            c = Claim(path, i + 1, f.get("id", "?"), _claim_text(line, FULL_RE, lines, i))
            missing = [k for k in REQUIRED if k not in f]
            if missing:
                c.malformed = f"missing field(s): {', '.join(missing)}"
            else:
                c.measured = _date(f["date"])
                ttl = TTL_RE.fullmatch(f["ttl"])
                if c.measured is None:
                    c.malformed = f"date {f['date']!r} is not YYYY-MM-DD"
                elif not ttl:
                    c.malformed = f"ttl {f['ttl']!r} is not <N>d"
                else:
                    c.ttl = int(ttl.group(1))
                if "timeout" in f:
                    t = TIMEOUT_RE.fullmatch(f["timeout"])
                    if t:
                        c.timeout = int(t.group(1))
                    elif c.malformed is None:
                        c.malformed = f"timeout {f['timeout']!r} is not <N>s"
            c.value = f.get("value")
            c.defer = f.get("defer_exec") == "1"
            claims.append(c)

        fence = FENCE_START.match(line)
        if fence:
            body, j = [], i + 1
            while j < len(lines) and not FENCE_END.match(lines[j]):
                body.append(lines[j])
                j += 1
            if j >= len(lines):
                # Never guess where an unclosed command ends.
                bad = Claim(path, i + 1, fence.group("id"), "")
                bad.malformed = "staleness-cmd fence is never closed"
                claims.append(bad)
                break
            commands.append(Command(fence.group("id"), "\n".join(body).strip(), path, i + 1))
            i = j

        i += 1

    return claims, commands


def iter_markdown(targets: List[str]):
    """Yield (path, None) for files to scan, or (target, error) for misses."""
    for t in targets:
        p = pathlib.Path(t)
        if p.is_dir():
            for f in sorted(p.rglob("*.md")):
                yield f, None
        elif p.is_file():
            yield p, None
        else:
            yield p, "no such file or directory"


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
        else:  # pragma: no cover - non-POSIX
            proc.kill()
    except ProcessLookupError:
        pass


def run_command(cmd: str, timeout: int, cwd: Optional[str]):
    """Return (stdout, stderr, returncode, None) or (None, None, None, reason)."""
    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except OSError as exc:
        return None, None, None, f"could not start: {exc}"
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass  # something outside the group still holds the pipes
        return None, None, None, f"timed out after {timeout}s (process group killed)"
    return out, err, proc.returncode, None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Flag dated claims in Markdown that are stale, uncheckable or wrong.",
    )
    ap.add_argument("targets", nargs="+", help="Markdown files or directories")
    ap.add_argument(
        "--max-age", type=int, default=30, metavar="DAYS",
        help="short-form claims measured more than DAYS ago are stale (default: 30)",
    )
    ap.add_argument(
        "--run", action="store_true",
        help="execute re-measurement commands: compare value= claims, print the rest",
    )
    ap.add_argument(
        "--no-exec-deferred", action="store_true",
        help="with --run, never execute defer_exec=1 commands, even for stale claims",
    )
    ap.add_argument(
        "--fail-on", choices=("never", "uncheckable", "stale"), default="uncheckable",
        help="exit 1 when findings reach this level (default: uncheckable)",
    )
    ap.add_argument(
        "--timeout", type=int, default=300, metavar="SECONDS",
        help="default per-command timeout for --run (default: 300)",
    )
    ap.add_argument("--cwd", metavar="DIR", help="run commands in DIR (default: .)")
    ap.add_argument("--today", metavar="YYYY-MM-DD", help="treat this as today (for tests)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)

    today = _dt.date.today()
    if args.today:
        today = _date(args.today)
        if today is None:
            ap.error(f"--today {args.today!r} is not YYYY-MM-DD")
    if args.cwd and not os.path.isdir(args.cwd):
        ap.error(f"--cwd {args.cwd!r} is not a directory")

    claims: List[Claim] = []
    blocks: Dict[str, List[Command]] = {}
    files = 0
    cannot_measure = 0
    for path, err in iter_markdown(args.targets):
        if err:
            print(f"{path}: {err} -- NOT scanned", file=sys.stderr)
            cannot_measure += 1
            continue
        try:
            found, cmds = parse(path)
        except OSError as exc:
            print(f"{path}: cannot read: {exc} -- NOT scanned", file=sys.stderr)
            cannot_measure += 1
            continue
        files += 1
        claims.extend(found)
        for c in cmds:
            blocks.setdefault(c.id, []).append(c)

    n = {k: 0 for k in ("stale", "uncheckable", "malformed", "mismatch",
                        "value_ok", "unknown", "deferred", "not_run")}

    for c in sorted(claims, key=lambda c: (str(c.path), c.line)):
        kinds: List[str] = []
        notes: List[str] = []
        output: Optional[str] = None

        if c.malformed is None and c.measured is not None and c.measured > today:
            c.malformed = f"date {c.measured} is in the future (today {today})"
        if c.malformed:
            n["malformed"] += 1
            print(f"{c.path}:{c.line}  id={c.id:<22} {c.malformed:<34} MALFORMED")
            continue

        age = (today - c.measured).days
        limit = c.ttl if c.ttl is not None else args.max_age
        stale = age > limit
        detail = f"measured {c.measured}  ({age} days ago" + (
            f", ttl {c.ttl}d)" if c.ttl is not None else ")")
        if stale:
            kinds.append("STALE")
            n["stale"] += 1

        bodies = {b.body for b in blocks.get(c.id, [])}
        cmd = next(iter(bodies)) if len(bodies) == 1 else None
        if not bodies:
            kinds.append("UNCHECKABLE")
            n["uncheckable"] += 1
            notes.append("no staleness-cmd block")
        elif cmd is None:
            kinds.append("UNCHECKABLE")
            n["uncheckable"] += 1
            where = ", ".join(f"{b.path}:{b.line}" for b in blocks[c.id])
            notes.append(f"{len(bodies)} different staleness-cmd blocks share this id ({where})")

        if cmd is not None and c.value is not None and not args.run:
            n["not_run"] += 1
        if cmd is not None and args.run:
            if c.defer and (args.no_exec_deferred or not stale):
                kinds.append("VALUE-DEFERRED")
                n["deferred"] += 1
                why = "--no-exec-deferred" if args.no_exec_deferred else "younger than its ttl"
                notes.append(f"defer_exec=1, command not run ({why})")
            else:
                out, err, rc, fail = run_command(cmd, c.timeout or args.timeout, args.cwd)
                if fail:
                    kinds.append("VALUE-UNKNOWN")
                    n["unknown"] += 1
                    notes.append(fail)
                elif c.value is not None:
                    actual = out.strip()
                    if actual == c.value.strip():
                        n["value_ok"] += 1
                        notes.append(f"value matches {c.value!r}")
                    else:
                        kinds.append("VALUE-MISMATCH")
                        n["mismatch"] += 1
                        notes.append(f"recorded {c.value!r}, now {actual[:200]!r}")
                else:
                    output = ((out + err).strip() or "(no output)") + (
                        f"\n(exit {rc})" if rc else "")

        print(f"{c.path}:{c.line}  id={c.id:<22} {detail:<34} {' '.join(kinds) or 'ok'}")
        if c.text:
            print(f"    claim: {c.text}")
        for note in notes:
            print(f"    - {note}")
        if output is not None:
            print(f"    $ {cmd}")
            for ln in output.splitlines():
                print(f"    | {ln}")
            print("    ^ compare against the claim above; this tool does not judge.")

    claimed = {c.id for c in claims}
    for cid in sorted(set(blocks) - claimed):
        print(f"(warning) staleness-cmd:{cid} has no claim referring to it")

    if cannot_measure:
        print(f"\ncannot measure: {cannot_measure} target(s) not scanned", file=sys.stderr)
        return 2
    if files == 0:
        print("no Markdown files found", file=sys.stderr)
        return 2
    if not claims:
        print(f"\noff: 0 tagged claims in {files} file(s) -- nothing has opted in, "
              "which is not the same as nothing being stale")
        return 3

    print(
        f"\n{len(claims)} claim(s) in {files} file(s): "
        f"{n['stale']} stale, {n['uncheckable']} uncheckable "
        f"(threshold: {args.max_age} days); "
        f"{n['malformed']} malformed, {n['mismatch']} value-mismatch; "
        f"value-check: ok={n['value_ok']} unknown={n['unknown']} "
        f"deferred={n['deferred']} not-run={n['not_run']}"
        + ("" if args.run else " (pass --run to execute commands)")
    )

    serious = n["uncheckable"] + n["malformed"] + n["mismatch"]
    if args.fail_on == "stale" and (serious or n["stale"]):
        return 1
    if args.fail_on == "uncheckable" and serious:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
