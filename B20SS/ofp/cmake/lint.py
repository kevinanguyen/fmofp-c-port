"""The flight code's lint (unit 30): clang-tidy with ofp/.clang-tidy over every flight source the build compiles.

    python3 lint.py BUILD_DIR [--clang-tidy PATH] [--jobs N] [--list]

BUILD_DIR holds compile_commands.json (any preset's build directory). Flight code is what is compiled from
bus/, osal/, bc/ and partitions/<name>/src/, less each process's main.cpp: the mains, the stdin tools, the stub
terminal and the tests print, parse arguments and use the heap, and the rules are not theirs. The compile
database decides the platform's files (udp_win32.cpp or udp_posix.cpp). Prints each finding and exits 1 if
there is any; the `lint` target calls this.
"""

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys

FLIGHT = re.compile(r"/ofp/(bus|osal|bc|partitions/[a-z_]+)/src/[^/]+\.cpp$")
NOT_FLIGHT = re.compile(r"/(main\.cpp$|rt_stub/|utilities_tool/|tools/)")
FINDING = re.compile(r": (warning|error): ")


def flight_sources(build_dir):
    """The flight sources in the compile database, sorted."""
    with open(os.path.join(build_dir, "compile_commands.json"), encoding="utf-8") as f:
        database = json.load(f)
    files = set()
    for entry in database:
        path = os.path.normpath(os.path.join(entry.get("directory", ""), entry["file"])).replace("\\", "/")
        if FLIGHT.search(path) and not NOT_FLIGHT.search(path):
            files.add(path)
    return sorted(files)


def lint_one(clang_tidy, build_dir, path):
    """(path, the lines clang-tidy printed, its exit code)."""
    # GCC's compile line carries warning flags clang does not know (-Wduplicated-cond, -Wlogical-op).
    result = subprocess.run([clang_tidy, "-p", build_dir, "--quiet", "--extra-arg=-Wno-unknown-warning-option", path],
                            capture_output=True, text=True, check=False)
    lines = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    return path, lines, result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("build_dir")
    parser.add_argument("--clang-tidy", default="clang-tidy")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    parser.add_argument("--list", action="store_true", help="print the files that would be linted and stop")
    args = parser.parse_args(argv)
    files = flight_sources(args.build_dir)
    if not files:
        print(f"lint: no flight source in {args.build_dir}/compile_commands.json (configure the build first)")
        return 1
    if args.list:
        print("\n".join(files))
        return 0
    findings = 0
    broken = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for path, lines, code in pool.map(lambda p: lint_one(args.clang_tidy, args.build_dir, p), files):
            found = sum(1 for line in lines if FINDING.search(line))
            findings += found
            if found:
                print("\n".join(lines))
            elif code != 0:
                broken.append(path)
                print("\n".join(lines))
    if broken:
        print(f"lint: FAILED: clang-tidy could not check {len(broken)} file(s): {', '.join(broken)}")
        return 1
    if findings:
        print(f"lint: FAILED: {findings} finding(s) in the flight code. Fix the code; to keep a line as it is, say "
              "why on it: // NOLINT(check-name): reason (ofp/.clang-tidy lists the checks and the rule each stands for)")
        return 1
    print(f"lint: OK ({len(files)} flight sources, no finding)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
