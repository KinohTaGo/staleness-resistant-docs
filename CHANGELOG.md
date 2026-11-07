# Changelog

## 0.2.0 — 2026-11-08

Brings the published checker up to the version used day to day in the repository the
pattern came from, and fixes one bug that version still had.

Added
- Full tag form: `<!-- staleness-check: id=… date=… ttl=<N>d [value="…"] [timeout=<N>s] [defer_exec=1] -->`.
  Each claim carries its own time-to-live instead of one global `--max-age`.
- Opt-in exact check: with `--run`, a claim that has `value="…"` is compared with its
  command's stdout and reported as `VALUE-MISMATCH` when they differ. Claims without
  `value=` are still only printed for a human to judge.
- `defer_exec=1` and `--no-exec-deferred`, for re-measurements too expensive to run on
  every pass.
- `MALFORMED`: a broken tag (missing field, bad date or ttl, a date in the future) or an
  unclosed command fence is reported instead of skipped.
- `--timeout`, `--cwd`, `--version`.
- Tests (`tests/`, standard library only) and a CI workflow.

Changed
- Exit code `3` (**off**) when no tagged claims are found. 0.1.0 returned `0`, which read
  as "everything is fresh".
- Exit code `2` when any explicit target is missing or unreadable. 0.1.0 printed a
  warning and carried on.
- `STALE` and `UNCHECKABLE` are judged independently, so a claim can be both. 0.1.0
  reported an old claim with no command only as `UNCHECKABLE`.
- Two command blocks with the same id and different bodies make the claim
  `UNCHECKABLE`. 0.1.0 silently used the first one.
- Command fences may be indented (claims often live in nested list items).
- Requires Python 3.9+ (tested on 3.9 and 3.13).

Fixed
- A timed-out command is now killed together with its whole process group. 0.1.0 killed
  only the `/bin/sh` it started, so a backgrounded child kept running after the check.

The 0.1.0 short form `<!-- measured:YYYY-MM-DD id:… -->` and all 0.1.0 options keep working.

## 0.1.0 — 2026-08-02

First public release (it carried no version number at the time).
