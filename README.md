# staleness-resistant-docs

> 日本語版: [README.ja.md](README.ja.md)

A documentation pattern for long-lived project instruction files — `CLAUDE.md`,
`CONTRIBUTING.md`, onboarding docs, runbooks — where factual claims about the project
rot faster than anyone notices.

The pattern is small: **a factual claim carries the date it was measured and the command
to re-measure it.** A checker then tells you which claims are old, and re-runs them on
demand.

## What is in this repository

| File | What it is |
|---|---|
| [`staleness-check.py`](staleness-check.py) | The checker. One file, Python 3.9+, standard library only |
| [`EXAMPLE.md`](EXAMPLE.md) | Tagged claims to run it against (the commands only `echo`) |
| [`tests/`](tests/) | Standard-library tests: `python3 -m unittest discover -s tests` |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed between versions, and why |
| this README | The pattern, the cases that motivated it, and what running it taught |

Use it by tagging the claims in your own `CLAUDE.md` or runbook and running the checker
in CI or before you trust the file.

## The problem

Instruction files accumulate empirical claims:

> Tests: `pytest tests/` — 189 passing, coverage 59.06% (below the 80% threshold)

That sentence was true once. Some weeks later the suite has 253 tests, coverage is 96%,
and the threshold is met — but the sentence is unchanged, and nothing in it says when it
was true. A reader cannot tell a current fact from a fossil.

This is worse for AI coding agents than for humans, because an agent will act on the
sentence. A human skims and thinks "that looks old." An agent reads `CLAUDE.md` as
authoritative and goes to work on a problem that was fixed three commits ago.

### Three cases where this actually cost something

Taken from the repository this pattern was developed in:

| Stale claim | Reality | Cost |
|---|---|---|
| "coverage 59.06%, below `fail_under=80`" | Fixed two days earlier; coverage was 96.20% | An investigation was opened into a problem that no longer existed |
| "plugins: 23 registered / 23 enabled" | 46 registered / 24 enabled / 22 disabled | The *total* never moved, only the split — so the line looked plausible and was believed |
| "bats: 251 tests, 21 skipped, up to 5 known failures" | Count had grown 251 → 889 over several weeks | Invited "that's a known skip, ignore it" reasoning about numbers that no longer described the suite |

The second one is the instructive one. **A recent-looking date is not evidence that a
number is still right.** The plugin total was unchanged, so nothing looked suspicious.

## The pattern

### 1. Every empirical claim gets a measurement date and an id

```markdown
- Test suite: **253 passed**, coverage **96.20%**
  <!-- measured:2026-07-28 id:pytest-count -->
```

Not "last updated" — *measured*. Editing the sentence does not make it true again.

### 2. Every measurement date gets a re-measurement command

````markdown
```staleness-cmd:pytest-count
.venv/bin/python3 -m pytest tests/ -q 2>&1 | tail -1
```
````

This is the load-bearing part. A date alone tells you a claim *might* be stale. A command
lets anyone — including an agent — settle it in one step instead of guessing.

#### The full form: a ttl per claim, and an optional expected value

Some numbers drift daily and some never move, so one `--max-age` for every claim is too
coarse. Since v0.2 a claim can carry its own time-to-live, and — when its command prints
a single stable result — the value it expects:

```markdown
- Lint is clean
  <!-- staleness-check: id=lint-status date=2026-11-01 ttl=14d value="0" -->
```

| Field | Meaning |
|---|---|
| `id`, `date`, `ttl` | required. `ttl` is `<N>d`: how long this claim is trusted |
| `value` | optional. Expected stdout of the command, compared exactly under `--run` |
| `timeout` | optional. `<N>s`, per-claim command timeout (default 300s) |
| `defer_exec` | optional. `1` = do not run this command under `--run` while the claim is younger than its ttl (for expensive re-measurements) |

The short form above keeps working unchanged.

### 3. When a claim goes stale, record what it cost

Do not silently correct it. Leave a note:

```markdown
- Test suite: **253 passed**, coverage **96.20%**
  <!-- measured:2026-07-28 id:pytest-count -->
  > This line said "59.06%, below threshold" for two days after the fix landed,
  > and caused one wasted investigation. Coverage numbers move; re-run before
  > acting on this.
```

The correction is more useful than the corrected value. The value will go stale again;
the warning about *how* it goes stale will not.

### 4. Say what a number does not cover

A number's scope is part of the number:

```markdown
- coverage **96.20%** <!-- measured:2026-07-28 id:coverage -->
  > Scope: `apis/`, `auth/`, `config/`, `utils/` only. `claude-env/` is not
  > measured at all, and most current work happens there. Do not cite this
  > figure as evidence about `claude-env/`.
```

This one caught a real problem: a healthy-looking 96% next to a directory with 46 failing
tests that the suite never ran.

## The checker

```sh
./staleness-check.py CLAUDE.md docs/
```

Output from a three-claim file, run as if on 2026-08-31:

```
CLAUDE.md:2  id=orphan-claim           measured 2026-05-01  (122 days ago) STALE UNCHECKABLE
    claim: - Deployment is session-boundary driven
    - no staleness-cmd block
CLAUDE.md:4  id=pytest-count           measured 2026-07-28  (34 days ago) STALE
    claim: - Test suite: **253 passed**, coverage **96.20%**
CLAUDE.md:6  id=lint-status            measured 2026-08-28  (3 days ago, ttl 14d) ok
    claim: - Lint is clean

3 claim(s) in 1 file(s): 2 stale, 1 uncheckable (threshold: 30 days); 0 malformed, 0 value-mismatch; value-check: ok=0 unknown=0 deferred=0 not-run=1 (pass --run to execute commands)
```

| Reported | Meaning |
|---|---|
| `STALE` | older than its `ttl` (full form) or `--max-age` (short form) |
| `UNCHECKABLE` | no command re-measures it, or two different command blocks share its id |
| `MALFORMED` | the tag itself is broken (missing field, bad date, a date in the future) or a command fence is never closed — reported, never skipped |
| `VALUE-MISMATCH` | `--run`, `value=` given, and the command printed something else |
| `VALUE-UNKNOWN` | `--run`, but the command did not finish (timeout, could not start) |
| `VALUE-DEFERRED` | `--run`, but `defer_exec=1` kept the command from running |

Exit codes: `0` nothing reached the `--fail-on` level · `1` findings at or above it ·
`2` could not measure (a target missing or unreadable) · `3` **off**: no tagged claims
were found at all. `3` is deliberately not `0` — "nothing opted in" must not read as
"everything is fresh".

Re-run the commands and show current output next to the recorded claim:

```sh
./staleness-check.py --run CLAUDE.md
```

### It reports, it does not judge

The checker deliberately **does not** decide whether a claim is still true by
diffing command output. Output formats change, tests get added, and an automatic
"MISMATCH" on every run trains people to ignore it.

What it does:

- flags claims older than a threshold (age is objective)
- flags claims with **no** re-measurement command (the important failure — a claim nobody
  can check)
- runs the commands and puts current output next to the claim, for a human to judge

Deciding whether "253 passed" and "1131 passed" represent the same healthy state is not a
string comparison.

> **Correction (v0.2).** The paragraph above is still the default, but it was too strong.
> Some claims do have a command that prints one stable value — an exit code, a count that
> should not move — and for those an exact comparison is cheap and right. v0.2 therefore
> lets a single claim opt in with `value="…"`. A claim without `value=` is still only
> printed for a human to judge.

### Opt-in by tag, never prose parsing

The checker only looks at explicitly tagged claims. It does not try to read prose and
guess which sentences are factual assertions — that approach produces false positives
until people stop reading the output, at which point the tool is worse than nothing.

The cost is that untagged claims are invisible. That is the right trade: the tool's value
is that **when it says something, it is worth reading.**

## What running it taught

Four things that went wrong while this checker was used on a real repository, and what
the current version does about each:

1. **An exact value on a per-machine number never settles.** A plugin count was tagged
   with `value=`. Two machines legitimately had different counts, so the check was always
   red on one of them, and each "fix" made on one machine broke the other. *Now:* the
   docs say to give such claims a date and a ttl but no `value=` (see `EXAMPLE.md`).
2. **A command that can only print the failure shape goes silent on success.** A
   re-measurement used `grep -oE '[0-9]+ failed, [0-9]+ passed'`. When every test passed
   there was nothing to match, and "it got better" came back as the same empty output as
   "the command broke". *Now:* write commands that print the good state too (take the
   summary line itself).
3. **An expensive re-measurement on every push adds up, and the opt-out came back.**
   Re-running a full test suite cost most of a push hook's runtime. `defer_exec=1` skipped
   it while the claim was fresh — and the cost returned as soon as the claim went stale,
   on every push. *Now:* `--no-exec-deferred` lets a hook never run those commands; run
   them by hand instead.
4. **A timeout that kills only the shell leaves its children running.** The earlier
   version timed out the `/bin/sh` it started, and a backgrounded grandchild kept running.
   *Now:* each command gets its own process group and the whole group is killed on
   timeout. There is a test for it.

## Install

```sh
cp staleness-check.py /usr/local/bin/
```

Python 3.9+, no dependencies. Tests: `python3 -m unittest discover -s tests`.

Suggested CI usage — fail on uncheckable claims, warn on stale ones:

```yaml
- run: ./staleness-check.py --fail-on uncheckable CLAUDE.md docs/
```

## What this does not solve

It does not stop anyone from writing a claim with no tag, and it can only tell you a tagged
claim is wrong when that claim opted in to an exact `value=` — otherwise only that it is
old or unverifiable. It reduces the cost of checking,
which in practice is what determines whether checking happens.

## License

MIT
