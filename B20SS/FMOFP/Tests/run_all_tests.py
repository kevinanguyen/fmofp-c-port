"""Aggregating test runner — runs every standalone-safe test suite with one
real exit code.

Why this exists (August 2026 production-readiness follow-up): the repo had 23
test files but CI executed only 7 of them as individually-maintained workflow
steps, and PLANNING.md had already flagged that several test entry points
discard run_tests()'s result (false-positive risk). This runner is the single
source of truth for "the test suite": it subprocess-isolates each suite,
enforces a per-suite watchdog timeout (a hang is a failure, not a stall —
see ci_test_boot_smoke.py for why that matters here), aggregates results,
and exits nonzero if ANY suite fails, times out, or crashes.

Run from B20SS/:  python FMOFP/Tests/run_all_tests.py

Suites deliberately NOT run here, with reasons:
  - Everything that tested the Python messaging is gone with it (November 2026, the C++ port's unit 29):
    the live-system suites (test_*_live.py and Tests/live_system.py, which booted the application through
    core/system_manager.py), the bus and listener suites (test_bus_adapter, test_listener_*,
    test_send_path_bounds, test_fcs_wire_format), the routing and handler suites (test_request_expiry,
    test_handler_lock_discipline, test_radar_*, test_blocker_*, test_bridge_and_coordinator,
    test_precipitation_data_transfer, test_loop_prevention_categories, test_single_definition,
    test_boundary_exception_handling), and the old CLI's (test_thread_and_cli_resilience,
    test_health_and_readiness). The flight software is C++ on a simulated bus now and is tested from
    B20SS/fmofp_bus/tests (run by B20SS/verify.sh), which also runs the Python logic kept here beside the
    C++ as its reference.

  - test_weather_radar_holographic_display: interactive GUI test — enters
    QApplication.exec() and never exits; visual inspection only.
  - performance_profile: a profiler, not a pass/fail test.
  - setup_env: an import helper, not a test.
"""
import os
import re
import subprocess
import sys
import time

# (module path run with -m?, name, timeout seconds)
SUITES = [
    (True,  "FMOFP.Tests.ci_test_boot_smoke", 300),
    (True,  "FMOFP.Tests.test_displays_headless", 300),
    (False, "FMOFP/Tests/ci_test_weather_radar.py", 300),
    (False, "FMOFP/Tests/ci_test_scenario_engine.py", 300),
    (True,  "FMOFP.Tests.test_power_fuel_thrust", 300),
    (True,  "FMOFP.Tests.test_hydr_airframe_ecs_fdm_fitness_swcm", 300),
    (True,  "FMOFP.Tests.test_toctou_start_race_regression", 600),
    (True,  "FMOFP.Tests.test_install_script", 300),
    (True,  "FMOFP.Tests.test_scenario_failure_injection", 300),
    (True,  "FMOFP.Tests.test_db_connection_pool", 300),
    (True,  "FMOFP.Tests.test_radar_shutdown_health", 300),
    (True,  "FMOFP.Tests.test_data_root", 300),
    (True,  "FMOFP.Tests.test_line_endings", 300),
    # H17: SystemDatabase.ensure_column_exists had the log prefix "[DBM] "
    # pasted inside its ALTER statement, checked for an existing column with a
    # substring match against the CREATE TABLE text, and swallowed the resulting
    # OperationalError. It added nothing, ever, and said it had.
    (True,  "FMOFP.Tests.test_db_ensure_column", 300),
    # The interpreters CI covers and the interpreters a shipped offline
    # install supports were not the same set: PyQt6_sip is not abi3, so the
    # bundled wheel is locked to CPython 3.10 and --offline has no PyPI
    # fallback. CI never caught it because it only runs on ubuntu-latest,
    # where WHEEL_DIRS is empty and that path is never exercised.
    (True,  "FMOFP.Tests.test_offline_install_matrix", 180),
    # FuelManagementSystem's worker loop called three methods outside its
    # try, so ONE transient error killed fuel management permanently and
    # silently -- reproduced with a single injected RuntimeError -- while
    # get_status() went on reporting running=True over the dead thread. An
    # AST sweep found it was the only one of the nine safety-critical
    # subsystems with unguarded calls in its loop; the sweep is kept here as
    # a regression guard, together with the consecutive-failure reporting
    # that stops the guard from turning a dead subsystem into a HEALTHY one.
    (True,  "FMOFP.Tests.test_worker_loop_resilience", 180),
    # H21: <level> in startupConfiguration.xml reached the console only. The
    # file handler was setLevel(logging.DEBUG), hardcoded, so the one knob
    # for how much to log governed the terminal and not the 250MB file --
    # measured at <level>error</level>: console 6 of 15 records, file 9 of
    # 15, including all five levels from the root logger, which is the logger
    # every SysLogger call delegates to. The file was named ERROR_*.log.
    (True,  "FMOFP.Tests.test_logging_levels", 180),
    # A failing suite has to be diagnosable from the CI log. The 60-line
    # tail excerpt could clip the suite's own verdict entirely: on
    # 2026-10-24 test_weather_radar_live failed, printed 36,130 lines, and
    # the excerpt was sixty lines of shutdown logging with no failing check
    # in it. verdict_lines() lifts the suite's markers out by pattern
    # wherever they sit in the stream.
    (True,  "FMOFP.Tests.test_runner_reporting", 120),
]


def _force_utf8_output():
    """This runner prints glyphs too, and its own stdout may be a pipe.

    Redirecting run_all_tests.py's output to a file or through a pager on
    Windows would hit the same cp1252 failure the suites hit. Best effort: a
    closed or exotic stream just keeps its current encoding.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def run_suite(as_module: bool, name: str, timeout_s: int):
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Every suite prints box-drawing and check glyphs. A child's stdout here is
    # a PIPE, so Python picks the locale encoding for it -- cp1252 on Windows --
    # and the first such print() raises UnicodeEncodeError before the suite has
    # tested anything. Nine of the 28 suites died that way, and the handler then
    # raised again trying to print the failure marker. PYTHONIOENCODING takes
    # precedence over PYTHONUTF8, so both are set; setdefault leaves an explicit
    # choice by the caller alone.
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    cwd = os.getcwd()
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (cwd, env.get("PYTHONPATH", "")) if p
    )
    cmd = [sys.executable, "-m", name] if as_module else [sys.executable, name]
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, timeout=timeout_s, capture_output=True,
            encoding="utf-8", errors="replace",
            env=env, cwd=cwd,
        )
        elapsed = time.monotonic() - start
        return proc.returncode, elapsed, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        out = exc.stdout or b""
        err = exc.stderr or b""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        if isinstance(err, bytes):
            err = err.decode(errors="replace")
        return "TIMEOUT", elapsed, out, err


# How many trailing lines of each stream to show for a failing suite. 20 was
# too few to reach the suite's own verdict past Qt's startup warnings.
TAIL_LINES = 60

# How many verdict lines to lift out of the stream, wherever they sit in it.
VERDICT_LINES = 40


def verdict_lines(text, limit=VERDICT_LINES):
    """The suite's own failure lines and score, wherever they are in `text`.

    WHY A TAIL IS NOT ENOUGH. A suite prints its FAIL lines and its "N/M
    passed" score, and then its fixtures shut a real application down,
    which logs. test_weather_radar_live emitted 36,130 lines, and the
    shutdown logging after the summary was longer than the 60-line tail --
    so the CI excerpt for a genuine failure was sixty lines of
    "AEWC radar aewc_radar stopped" and not one word about what failed.
    Measured on the CI log of 2026-10-24: "[harness] FAILED: body returned
    1" with no failing check anywhere in the excerpt, and the suite does not
    reproduce locally, so the information was simply gone.

    Lifting these lines out by pattern makes a failing suite diagnosable
    from the CI log no matter how much it logs afterwards. The tail is still
    printed, for context around the end.
    """
    wanted = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        # The suites' own markers. "FAIL" is matched at the start of the
        # stripped line so that a log record merely containing the word --
        # and there are plenty -- does not qualify.
        if (stripped.startswith("FAIL")
                or stripped.startswith("✗")
                or stripped.startswith("[harness]")
                or stripped.startswith("Failures:")
                or _SCORE_RE.match(stripped)):
            wanted.append(line)
    if len(wanted) > limit:
        dropped = len(wanted) - limit
        # Keep the LAST ones: the score and the Failures: block come last.
        wanted = [f"... {dropped} earlier verdict line(s) omitted"] + wanted[-limit:]
    return wanted


_SCORE_RE = re.compile(r"^\d+/\d+ passed$")


def main() -> int:
    _force_utf8_output()
    print(f"Running {len(SUITES)} test suites "
          "(subprocess-isolated, per-suite watchdog)\n" + "=" * 60)
    failures = []
    for as_module, name, timeout_s in SUITES:
        rc, elapsed, out, err = run_suite(as_module, name, timeout_s)
        label = name.rsplit("/", 1)[-1]
        if label.endswith(".py"):
            label = label[:-3]
        else:
            label = label.rsplit(".", 1)[-1]
        if rc == 0:
            print(f"  ✓  {label:<45s} {elapsed:6.1f}s")
        else:
            status = "TIMED OUT" if rc == "TIMEOUT" else f"exit {rc}"
            print(f"  ✗  {label:<45s} {elapsed:6.1f}s  ({status})")
            failures.append((name, rc))
            # Show BOTH streams. This used to be `(err or out)`, which threw
            # stdout away whenever stderr had any content at all -- and stderr
            # is never empty here, because Qt's offscreen plugin warns and the
            # shutdown path logs tracebacks. The result was that a failing
            # suite reported 20 lines of Qt noise while the suite's own "FAIL"
            # lines and verdict, which are on stdout, were discarded. That made
            # a CI failure of test_weather_radar_live undiagnosable from the
            # log (Sept 2026).
            print("     ┌─ last output " + "─" * 40)
            shown = False

            # The suite's own verdict first, pulled from anywhere in the
            # stream, because the tail below can miss it entirely.
            verdict = verdict_lines(out) or verdict_lines(err)
            if verdict:
                print("     │ ── the suite's own verdict lines ──────────")
                for line in verdict:
                    print("     │ " + line)
                shown = True

            # A suite can end up emitting every record to both streams (for
            # example by adding a console handler when SysLogger has already
            # attached one), leaving stderr byte-identical to stdout. Printing
            # both then doubles the failure report -- 60 lines becomes 120 of
            # the same thing. Show stderr only when it actually differs.
            # Measured per suite: test_precipitation_data_transfer had 301 of
            # 623 lines repeated before its own handler was fixed, against
            # 0.2% for test_weather_radar_live, so this is a per-suite hazard
            # rather than a property of the logging setup.
            streams = [("stdout", out)]
            if (err or "").strip() and (err or "").strip() != (out or "").strip():
                streams.append(("stderr", err))
            elif (err or "").strip():
                streams.append(("stderr", "(identical to stdout -- not repeated)"))
            for stream_name, text in streams:
                if not (text or "").strip():
                    continue
                shown = True
                lines = text.splitlines()
                clipped = len(lines) - TAIL_LINES
                print(f"     │ ── {stream_name} "
                      + (f"(last {TAIL_LINES} of {len(lines)} lines) "
                         if clipped > 0 else "")
                      + "─" * 10)
                for line in lines[-TAIL_LINES:]:
                    print("     │ " + line)
            if not shown:
                print("     │ (the suite produced no output)")
            print("     └" + "─" * 54)
    print("=" * 60)
    if failures:
        print(f"FAILED: {len(failures)}/{len(SUITES)} suites: "
              + ", ".join(n for n, _ in failures))
        return 1
    print(f"All {len(SUITES)} suites passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
