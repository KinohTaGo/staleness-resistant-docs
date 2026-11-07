# Example

Run `./staleness-check.py EXAMPLE.md`, then `./staleness-check.py --run EXAMPLE.md`.
The commands below only `echo`, so this file is safe to run.

## Short form — age is judged against `--max-age`

- Test suite: **253 passed**, coverage **96.20%**
  <!-- measured:2026-07-28 id:pytest-count -->

- Shell suite: **906 tests**, 0 skipped
  <!-- measured:2026-07-30 id:bats-count -->

- Deployment is session-boundary driven
  <!-- measured:2026-05-01 id:no-such-command -->

## Full form — each claim carries its own ttl

- Lint is clean (`ruff check .` exits 0)
  <!-- staleness-check: id=lint-status date=2026-11-01 ttl=14d value="0" -->

Expensive to re-measure, so it is only re-run once the claim is older than its ttl:

- The full test suite passes
  <!-- staleness-check: id=full-suite date=2026-11-01 ttl=7d value="passed" defer_exec=1 timeout=600s -->

A per-machine number gets a date and a ttl, but deliberately no `value=`:

- Plugins on this machine: **46 registered / 24 enabled**
  <!-- staleness-check: id=plugin-count date=2026-07-30 ttl=7d -->

```staleness-cmd:pytest-count
echo "253 passed in 12.3s"
```

```staleness-cmd:bats-count
echo "1..906"
```

```staleness-cmd:lint-status
echo 0
```

```staleness-cmd:full-suite
echo passed
```

```staleness-cmd:plugin-count
echo "46 24 22"
```
