# staleness-resistant-docs

> 日本語版: [README.ja.md](README.ja.md)

A documentation pattern for long-lived project instruction files — `CLAUDE.md`,
`CONTRIBUTING.md`, onboarding docs, runbooks — where factual claims about the project
rot faster than anyone notices.

The pattern is small: **a factual claim carries the date it was measured and the command
to re-measure it.** A checker then tells you which claims are old, and re-runs them on
demand.

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

```
CLAUDE.md:132  id=pytest-count      measured 2026-07-28  (34 days ago)   STALE
CLAUDE.md:147  id=plugin-count      measured 2026-07-30  (32 days ago)   STALE
CLAUDE.md:203  id=bats-count        measured 2026-08-28  (3 days ago)    ok
CLAUDE.md:88   id=orphan-claim      no staleness-cmd block               UNCHECKABLE

2 stale, 1 uncheckable (threshold: 30 days)
```

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

### Opt-in by tag, never prose parsing

The checker only looks at explicitly tagged claims. It does not try to read prose and
guess which sentences are factual assertions — that approach produces false positives
until people stop reading the output, at which point the tool is worse than nothing.

The cost is that untagged claims are invisible. That is the right trade: the tool's value
is that **when it says something, it is worth reading.**

## Install

```sh
cp staleness-check.py /usr/local/bin/
```

Python 3.8+, no dependencies.

Suggested CI usage — fail on uncheckable claims, warn on stale ones:

```yaml
- run: ./staleness-check.py --fail-on uncheckable CLAUDE.md docs/
```

## What this does not solve

It does not stop anyone from writing a claim with no tag, and it cannot tell you a tagged
claim is wrong — only that it is old or unverifiable. It reduces the cost of checking,
which in practice is what determines whether checking happens.

## License

MIT
