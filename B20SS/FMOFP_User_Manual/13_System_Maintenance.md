# 13. Building, Testing and Troubleshooting

**Navigation:** [← Operating Procedures](12_Operational_Procedures.md) | [Table of Contents](00_Title_and_TOC.md) | [Appendices →](14_Appendices.md)

---

This chapter is for whoever builds, changes or repairs the software. The intern's first pages are
`B20SS/ofp/docs/ARCHITECTURE.md` (how the pieces fit) and `B20SS/ofp/docs/DEBUGGING.md` (a partition under gdb). The
C++ rules are `B20SS/ofp/CLAUDE.md`.

## 13.1 What to install

| What | Windows | Linux |
|---|---|---|
| Python 3.10 or newer | python.org, with the `py` launcher | the distribution's `python3` |
| Python packages | `py -m pip install -r B20SS/requirements.txt` (PyQt6, numpy, scipy, qasync, click) | `python3-numpy python3-scipy python3-pyqt6` |
| C++ toolchain | MSYS2 (`winget install MSYS2.MSYS2`), then in its UCRT64 shell: `pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja mingw-w64-ucrt-x86_64-gtest mingw-w64-ucrt-x86_64-cppcheck mingw-w64-ucrt-x86_64-gcovr` | `g++ cmake ninja-build libgtest-dev cppcheck gcovr` |
| Optional: lint and debugger | `mingw-w64-ucrt-x86_64-clang-tools-extra mingw-w64-ucrt-x86_64-gdb` | `clang-tidy gdb` |

Use `py`, never `python`, on Windows. MSYS2's `C:\msys64\ucrt64\bin` must not come before python.org's Python on
the PATH.

## 13.2 Building

From `B20SS/ofp/`, in a UCRT64 shell on Windows or any shell on Linux:

| Preset | Build | Use |
|---|---|---|
| `windows-ucrt64` / `linux-gcc` | Debug, `-O0` | the gate, the debugger |
| `windows-ucrt64-release` / `linux-gcc-release` | `-O2 -g` | the demo flies it when it exists |
| `linux-asan` | address and undefined-behaviour sanitizers | CI |
| `coverage` | instrumented | the coverage floors |

```bash
cmake --preset windows-ucrt64 && cmake --build --preset windows-ucrt64
cmake --preset windows-ucrt64-release && cmake --build --preset windows-ucrt64-release
```

The programs land in `ofp/build/<preset>/` (`bc/fmofp_bc`, `partitions/fmofp_<name>` and the stdin tools
`fmofp_<name>_tool`). **After any change under `ofp/`, build the release preset again too**: the demo flies it, and
a stale controller beside new Python clients answers their commands MALFORMED.

## 13.3 The gate

```bash
bash B20SS/verify.sh            # icd, cpp, py, load: every step
bash B20SS/verify.sh icd py     # some steps, in order
PRESET=windows-ucrt64-release bash B20SS/verify.sh cpp py load
```

| Step | Checks |
|---|---|
| `icd` | the ICD is valid and the generated files match it |
| `cpp` | configure, build (warnings are errors), the unit tests (ctest), cppcheck |
| `py` | the whole Python suite (`fmofp_bus/tests`, about 390 tests) against the built programs |
| `load` | the schedule's worst minor frame against the 10 ms budget |

The gate takes about five minutes on a quiet machine. Nothing is pushed to `port/cpp` unless it is green.

Also: `cmake --build --preset coverage` (every module held to 80 % of its lines), `cmake --build
build/<preset> --target lint` (clang-tidy over the flight code, if installed), and the legacy suites
`py FMOFP/Tests/run_all_tests.py`.

## 13.4 Running tests by hand

The Python tests find the programs through `FMOFP_*` environment variables (`fmofp_bus/tests/_support.py` lists
them). The easiest way is the prompt, which sets them:

```bash
py -m fmofp_cli -c "test list"
py -m fmofp_cli -c "test radar"
py -m fmofp_cli -c "test test_cas_oracle"
```

A unit test under gdb, the stdin tools and a partition on the bus under gdb are in `ofp/docs/DEBUGGING.md`.

## 13.5 Troubleshooting

| Symptom | Cause and remedy |
|---|---|
| `plant port in use?` with nothing on the port | Windows reserved that UDP range at boot (`netsh int ipv4 show excludedportrange protocol=udp`): use `--port-base` |
| a client says it sees no bus, or exits 2 | no controller on that port base, or a controller built before the command port: rebuild the release preset |
| overruns in the demo's dashboard | the machine is busy (a game, a build, a browser): measure on a quiet machine; `logs/demo/bc.log` says which terminal held each overrun frame up, and `overruns_late_start` counts frames the machine started late |
| a command is acknowledged and nothing happens | the acknowledgement means queued; read the terminal's status: a rejected command sets `cmd_rejected`, and a number equal to the last accepted one is ignored |
| a display window is slow | it repaints on its own timer; the bus does not wait for it. `py -m fmofp_display NAME --verbose` logs everything |
| a test hangs and leaves processes | stop the `fmofp_*` and `python` processes before running again, or the next run finds its ports taken |
| `verify.sh icd` reports generated files changed with an empty `git diff` | line endings on a CRLF checkout: `git restore` them |
| a real-time unit test fails once right after a full rebuild | the machine was busy: run `ctest` again before reading the code |

## 13.6 Logs and data

| Where | What |
|---|---|
| `B20SS/logs/demo/` | each program's log for the demo, and `bc.log` (the controller's statistics) |
| `B20SS/logs/recorder/` | the recorder's databases |
| `B20SS/FMOFP/logs/` | the display code's own log files |

None of these is committed.
