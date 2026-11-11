"""Line coverage of the flight code, module by module, against a floor (unit 30).

    python3 coverage_check.py SUMMARY.json [--floor PERCENT] [--floor-for MODULE=PERCENT ...]

SUMMARY.json is gcovr's --json-summary of the unit tests' run (the `coverage` target makes it and calls this).
A module is a directory of flight code: bus, osal, bc and each partitions/<name>. The process mains and the
stdin tools are not in the summary (the target leaves them out: the end-to-end and oracle tests exercise them,
from Python, which gcov does not see). Prints one line per module and exits 1 if any is under its floor, so a
partition cannot land with its logic untested behind a good overall number.
"""

import argparse
import json
import sys

# Under this many instrumented lines a percentage says little: reported, not judged.
SMALL_MODULE_LINES = 20


def module_of(filename):
    """bus/src/word.cpp -> bus; partitions/nav/src/x.cpp -> partitions/nav; anything else -> its first directory."""
    parts = filename.replace("\\", "/").split("/")
    if parts[0] == "partitions" and len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0]


def modules(summary):
    """module -> [covered lines, instrumented lines], from gcovr's per-file summary."""
    totals = {}
    for entry in summary.get("files", []):
        covered, total = totals.setdefault(module_of(entry["filename"]), [0, 0])
        totals[module_of(entry["filename"])] = [covered + entry["line_covered"], total + entry["line_total"]]
    return totals


def check(summary, floor, floors):
    """(report lines, names of the modules under their floor)."""
    lines, failed = [], []
    for name, (covered, total) in sorted(modules(summary).items()):
        percent = 100.0 * covered / total if total else 100.0
        wanted = floors.get(name, floor)
        if total < SMALL_MODULE_LINES:
            verdict = "small, not judged"
        elif percent + 1e-9 < wanted:
            verdict = f"UNDER its floor of {wanted:g} %"
            failed.append(name)
        else:
            verdict = f"floor {wanted:g} %"
        lines.append(f"  {name:<24} {percent:5.1f} %  {covered:>5} of {total:<5} lines  {verdict}")
    return lines, failed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("summary")
    parser.add_argument("--floor", type=float, default=80.0, help="the floor of every module without its own")
    parser.add_argument("--floor-for", action="append", default=[], metavar="MODULE=PERCENT")
    args = parser.parse_args(argv)
    floors = {}
    for item in args.floor_for:
        name, _, percent = item.partition("=")
        floors[name] = float(percent)
    with open(args.summary, encoding="utf-8") as f:
        summary = json.load(f)
    lines, failed = check(summary, args.floor, floors)
    if not lines:
        print("coverage: the summary names no file (did the tests run?)")
        return 1
    print("coverage of the flight code by module (lines the unit tests ran):")
    print("\n".join(lines))
    if failed:
        print(f"coverage: FAILED: {', '.join(failed)} under the floor: add unit tests in ofp/tests for what is "
              "not run, or state a lower floor for the module with its reason in ofp/CMakeLists.txt")
        return 1
    print("coverage: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
