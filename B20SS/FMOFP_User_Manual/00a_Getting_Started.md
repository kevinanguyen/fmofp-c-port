# Getting Started Guide

**Navigation:** [Table of Contents](00_Title_and_TOC.md) | [Legal Information →](00b_Legal_Information.md)

---

## Welcome

This guide takes you from a fresh clone to a flying aircraft: install the tools, build the C++ flight software,
run the test gate, and start the demo with its six cockpit windows. It takes about ten minutes once the tools are
installed.

## 1. Install the tools (once per machine)

**Python** 3.10 or newer from python.org (with the `py` launcher on Windows), then from the repository root:

```bash
py -m pip install -r B20SS/requirements.txt
```

This installs PyQt6, numpy, scipy, qasync and click.

**The C++ toolchain on Windows** is MSYS2. Install it (`winget install MSYS2.MSYS2`), open the *UCRT64* shell
(`C:\msys64\ucrt64.exe`) and run:

```bash
pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja mingw-w64-ucrt-x86_64-gtest mingw-w64-ucrt-x86_64-cppcheck mingw-w64-ucrt-x86_64-gcovr
```

Optional, for the lint and the debugger: `mingw-w64-ucrt-x86_64-clang-tools-extra mingw-w64-ucrt-x86_64-gdb`.
On Linux the same tools come from `apt` (chapter 13).

## 2. Build and verify

From the repository root, in Git Bash or any bash:

```bash
bash B20SS/verify.sh
```

`verify.sh` is the gate every change must pass. It checks the interface definition (the ICD), configures and
builds the C++ (debug build), runs the C++ unit tests and cppcheck, runs the whole Python test suite against the
binaries it built, and checks the bus load. It ends with `verify: OK (icd cpp py load)`; on a quiet machine it
takes about five minutes.

For the real-time demo, also build the optimised flight software (the demo uses it when it exists):

```bash
cd B20SS/ofp
cmake --preset windows-ucrt64-release
cmake --build --preset windows-ucrt64-release
```

Run these two in the UCRT64 shell (or with `C:\msys64\ucrt64\bin` first on `PATH`). On Linux the preset is
`linux-gcc-release`.

## 3. Fly the demo

From `B20SS`:

```bash
py -m fmofp_demo
```

The launcher starts the bus controller, the plant (the simulated world), every C++ partition and the six display
windows, prints one dashboard line a second, and plays a scripted flight: the mission route is loaded, the five
radars come on, the radio is tuned, a threat appears on the warning receiver and flares go out, a store is
released, the generator fails and recovers, the aircraft climbs and banks on the flight control computer's
surface commands. Ctrl-C stops everything. Logs go to `B20SS/logs/demo/`.

The six windows:

| Window | Shows |
|---|---|
| Radar | the weather and terrain pictures and the control panel for all five radars |
| PFD | attitude, airspeed, altitude, heading, flight mode, envelope warnings |
| MFD | navigation, systems, communications, mission and the five radar pictures |
| EICAS | engines, fuel, hydraulics, electrical, cabin, countermeasures, sensors, self tests, the crew alert list |
| TSD | the route, the fused tracks, the warning receiver's threats, the energy metrics |
| SMS | the eleven weapon stations, master arm and the load |

Useful options: `--headless` (no windows, for a test or a remote machine), `--seconds 60`, `--no-events` (no
scripted flight), `--theme modern` (the holographic PFD and MFD), `--mode night` (every display in night mode),
`--record` (write the flight's database tables), `--walk` (the old random-walk aircraft). Chapter 12 has them all.

## 4. Look at the bus while it flies

In a second terminal, from `B20SS`:

```bash
py -m fmofp_cli
```

At the `fmofp>` prompt try `terminals` (every terminal and its state), `status radar`, `msg FMS_FLIGHT_DATA`,
`do wx MAPPING 100` (the weather radar to mapping at 100 km), `do surface ELEVATOR 10` (the aircraft pitches up),
`mode night`, `help`. Chapter 12 explains the prompt.

## 5. Where to go next

- How the pieces fit: [chapter 1](01_System_Overview.md) and `B20SS/ofp/docs/ARCHITECTURE.md`.
- How to change and test a partition: [chapter 13](13_System_Maintenance.md) and `B20SS/ofp/docs/DEBUGGING.md`.
- Why the port does what it does: `B20SS/icd/README.md`, section 2.

## Common first-day problems

| Symptom | Cause and cure |
|---|---|
| `fmofp_demo: the C++ programs are not built` | run `verify.sh` (or the build commands) first |
| `the monitor port 51033 is in use` | another demo is running; stop it, or start this one with `--port-base 52000` |
| a test says `plant port in use?` with nothing running | Windows reserved that port range at boot; the tests step around it, the demo takes `--port-base` |
| PyQt6 fails to load on Python 3.14t | install and run the regular (not free-threaded) Python: `py -3.14` |
| many "overruns" on the dashboard | the machine is busy (a game, a big build); the bus is real-time. Chapter 13 explains how to measure |
