"""Tests for staleness-check.py. Standard library only:

    python3 -m unittest discover -s tests -v
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "staleness-check.py"
FENCE = "```"


def md(body: str) -> str:
    return textwrap.dedent(body).replace("~~~", FENCE)


class CheckerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, body: str) -> pathlib.Path:
        p = self.dir / name
        p.write_text(md(body), encoding="utf-8")
        return p

    def run_check(self, *args, today="2026-08-01"):
        cmd = [sys.executable, str(SCRIPT), "--today", today, "--cwd", str(self.dir), *args]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    # --- short form (v0.1 compatibility) ---------------------------------

    def test_short_form_ok_stale_uncheckable(self):
        p = self.write("a.md", """\
            - fresh <!-- measured:2026-07-30 id:fresh -->
            - old <!-- measured:2026-05-01 id:old -->
            - orphan <!-- measured:2026-07-30 id:orphan -->

            ~~~staleness-cmd:fresh
            echo 1
            ~~~

            ~~~staleness-cmd:old
            echo 2
            ~~~
            """)
        r = self.run_check(str(p))
        self.assertEqual(r.returncode, 1, r.stdout)  # default fails on uncheckable
        self.assertRegex(r.stdout, r"id=fresh .* ok")
        self.assertRegex(r.stdout, r"id=old .* STALE")
        self.assertRegex(r.stdout, r"id=orphan .* UNCHECKABLE")
        self.assertIn("3 claim(s) in 1 file(s): 1 stale, 1 uncheckable", r.stdout)

    def test_fail_on_levels(self):
        p = self.write("a.md", """\
            - old <!-- measured:2026-05-01 id:old -->

            ~~~staleness-cmd:old
            echo 2
            ~~~
            """)
        self.assertEqual(self.run_check("--fail-on", "uncheckable", str(p)).returncode, 0)
        self.assertEqual(self.run_check("--fail-on", "stale", str(p)).returncode, 1)
        self.assertEqual(self.run_check("--fail-on", "never", str(p)).returncode, 0)

    def test_run_prints_output_without_judging(self):
        p = self.write("a.md", """\
            - count <!-- measured:2026-07-30 id:c -->

            ~~~staleness-cmd:c
            echo current-output
            ~~~
            """)
        r = self.run_check("--run", str(p))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("| current-output", r.stdout)
        self.assertIn("this tool does not judge", r.stdout)

    def test_directory_target_and_cross_file_pairing(self):
        self.write("claims.md", "- x <!-- measured:2026-07-30 id:x -->\n")
        self.write("cmds.md", "~~~staleness-cmd:x\necho x\n~~~\n")
        r = self.run_check(str(self.dir))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("1 claim(s) in 2 file(s)", r.stdout)

    # --- full form ---------------------------------------------------------

    def test_full_form_uses_its_own_ttl(self):
        p = self.write("a.md", """\
            - a <!-- staleness-check: id=a date=2026-07-25 ttl=3d -->
            - b <!-- staleness-check: id=b date=2026-07-25 ttl=30d -->

            ~~~staleness-cmd:a
            echo a
            ~~~

            ~~~staleness-cmd:b
            echo b
            ~~~
            """)
        r = self.run_check("--max-age", "1", str(p))
        self.assertRegex(r.stdout, r"id=a .* STALE")
        self.assertRegex(r.stdout, r"id=b .* ok")

    def test_value_match_and_mismatch(self):
        p = self.write("a.md", """\
            - good <!-- staleness-check: id=good date=2026-07-30 ttl=30d value="42" -->
            - bad <!-- staleness-check: id=bad date=2026-07-30 ttl=30d value="42" -->

            ~~~staleness-cmd:good
            echo 42
            ~~~

            ~~~staleness-cmd:bad
            echo 43
            ~~~
            """)
        r = self.run_check("--run", str(p))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertRegex(r.stdout, r"id=good .* ok")
        self.assertRegex(r.stdout, r"id=bad .* VALUE-MISMATCH")
        self.assertIn("recorded '42', now '43'", r.stdout)
        self.assertIn("value-check: ok=1", r.stdout)

    def test_value_not_checked_without_run(self):
        marker = self.dir / "ran"
        p = self.write("a.md", f"""\
            - v <!-- staleness-check: id=v date=2026-07-30 ttl=30d value="1" -->

            ~~~staleness-cmd:v
            touch {marker}; echo 2
            ~~~
            """)
        r = self.run_check(str(p))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse(marker.exists(), "command must not run without --run")
        self.assertIn("not-run=1", r.stdout)

    def test_defer_exec(self):
        marker = self.dir / "ran"
        p = self.write("a.md", f"""\
            - v <!-- staleness-check: id=v date=2026-07-30 ttl=5d value="1" defer_exec=1 -->

            ~~~staleness-cmd:v
            touch {marker}; echo 1
            ~~~
            """)
        fresh = self.run_check("--run", str(p), today="2026-08-01")
        self.assertIn("VALUE-DEFERRED", fresh.stdout)
        self.assertFalse(marker.exists(), "fresh defer_exec claim must not run")

        never = self.run_check("--run", "--no-exec-deferred", str(p), today="2026-09-30")
        self.assertIn("VALUE-DEFERRED", never.stdout)
        self.assertFalse(marker.exists(), "--no-exec-deferred must not run it even when stale")

        stale = self.run_check("--run", str(p), today="2026-09-30")
        self.assertNotIn("VALUE-DEFERRED", stale.stdout)
        self.assertTrue(marker.exists(), "a stale defer_exec claim runs again")

    def test_timeout_reports_unknown_and_kills_the_group(self):
        pidfile = self.dir / "pid"
        p = self.write("a.md", f"""\
            - slow <!-- staleness-check: id=slow date=2026-07-30 ttl=30d value="x" timeout=1s -->

            ~~~staleness-cmd:slow
            ( sleep 60 & echo $! > {pidfile}; wait )
            ~~~
            """)
        r = self.run_check("--run", str(p))
        self.assertIn("VALUE-UNKNOWN", r.stdout)
        self.assertIn("timed out after 1s", r.stdout)
        pid = int(pidfile.read_text().strip())
        deadline = time.time() + 5
        alive = True
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                alive = False
                break
            time.sleep(0.1)
        if alive:  # do not leave it behind if the test fails
            os.kill(pid, 9)
        self.assertFalse(alive, "backgrounded grandchild outlived the timeout")

    # --- broken input is reported, never skipped ---------------------------

    def test_malformed_tags(self):
        p = self.write("a.md", """\
            - a <!-- staleness-check: id=a date=2026-07-30 -->
            - b <!-- staleness-check: id=b date=yesterday ttl=3d -->
            - c <!-- staleness-check: id=c date=2026-07-30 ttl=3 -->
            - d <!-- measured:2026-13-01 id:d -->
            - e <!-- measured:2026-12-01 id:e -->
            """)
        r = self.run_check("--fail-on", "never", str(p))
        self.assertEqual(r.stdout.count("MALFORMED"), 5, r.stdout)
        self.assertIn("missing field(s): ttl", r.stdout)
        self.assertIn("in the future", r.stdout)
        self.assertEqual(self.run_check(str(p)).returncode, 1)

    def test_unclosed_fence_is_malformed(self):
        p = self.write("a.md", """\
            - x <!-- measured:2026-07-30 id:x -->

            ~~~staleness-cmd:x
            echo never closed
            """)
        r = self.run_check(str(p))
        self.assertIn("never closed", r.stdout)
        self.assertEqual(r.returncode, 1)

    def test_conflicting_command_blocks_are_uncheckable(self):
        p = self.write("a.md", """\
            - x <!-- measured:2026-07-30 id:x -->

            ~~~staleness-cmd:x
            echo one
            ~~~

            ~~~staleness-cmd:x
            echo two
            ~~~
            """)
        r = self.run_check(str(p))
        self.assertRegex(r.stdout, r"id=x .* UNCHECKABLE")
        self.assertIn("2 different staleness-cmd blocks", r.stdout)

    # --- "could not check" never reads as "clean" ---------------------------

    def test_no_claims_is_off_not_clean(self):
        p = self.write("a.md", "# nothing tagged here\n")
        r = self.run_check(str(p))
        self.assertEqual(r.returncode, 3)
        self.assertIn("off: 0 tagged claims", r.stdout)

    def test_missing_target_cannot_measure(self):
        p = self.write("a.md", "- x <!-- measured:2026-07-30 id:x -->\n")
        r = self.run_check(str(p), str(self.dir / "missing.md"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("NOT scanned", r.stderr)

    def test_example_file(self):
        example = SCRIPT.parent / "EXAMPLE.md"
        r = self.run_check("--fail-on", "never", str(example), today="2026-11-08")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("claim(s) in 1 file(s)", r.stdout)


if __name__ == "__main__":
    unittest.main()
