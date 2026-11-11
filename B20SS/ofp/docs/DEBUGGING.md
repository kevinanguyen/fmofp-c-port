# Debugging one partition under gdb

How to build, run and step through one subsystem of the flight software. Read `ARCHITECTURE.md` first for what a
partition is. Every command below was run as written on Windows (MSYS2 UCRT64, gdb 18.1, g++ 16.2) with the
communications partition, the smallest one; on Linux the commands are the same without `.exe` and with the
`linux-gcc` preset (not run there when this was written).

## 1. Set up

In the **UCRT64** shell (`C:\msys64\ucrt64.exe`), once:

```bash
pacman -S --needed mingw-w64-ucrt-x86_64-gdb
```

Build the debug preset, from `B20SS/ofp/`:

```bash
cmake --preset windows-ucrt64
cmake --build --preset windows-ucrt64
cd build/windows-ucrt64
```

Debug the plain preset, never the `-release` one: it is built `-O0 -g`, so every line can be stopped on and every
variable read. The optimised build (`windows-ucrt64-release`) has symbols too, but lines are reordered and
variables read `<optimized out>`; use it only for a fault that does not show at `-O0`.

There are three ways to get a partition's code under gdb. Start with the first that reaches your problem.

| Way | What runs | Use it when |
|---|---|---|
| A unit test | `tests/ofp_tests.exe`, one test | the fault is in the logic and a test shows it (or you can write one) |
| The stdin tool | `partitions/fmofp_<name>_tool.exe` with a command file | a Python oracle test fails: replay its commands |
| On the bus | `partitions/fmofp_<name>.exe` with `fmofp_bc` polling it | the fault needs the real messages and frames |

## 2. A unit test under gdb

The quickest: one process, no bus, the same inputs every time.

```bash
gdb tests/ofp_tests.exe
```

```text
(gdb) break fmofp::comms::CommsComputer::step
(gdb) run --gtest_filter=CommsComputerTest.StartsAsCommsServiceDidAndFollowsTheField
```

gdb stops at the first line of `step` and shows the arguments:

```text
Thread 1 hit Breakpoint 1, fmofp::comms::CommsComputer::step (this=0x5ff550, rf=0x5ff510, frame=1)
    at .../partitions/comms/src/comms_computer.cpp:93
93	    if (rf != nullptr) {
```

From there:

| Command | What it does |
|---|---|
| `bt` | who called this (`bt 2` for the two innermost frames): here the test body, at its line |
| `next` / `step` | run one line / the same, but go into a function the line calls |
| `finish` | run to the end of this function and show what it returns |
| `continue` | run to the next breakpoint |
| `info args`, `info locals` | the arguments, the local variables |
| `print status_.state` | a member: prints `fmofp::icd::TerminalState::INITIALIZING`, the ICD's enum by name |
| `print *this` | the whole object |
| `print rf->payload` | what a pointer argument points at (a decoded bus message) |
| `break comms_computer.cpp:95` | stop at a line instead of a function |
| `watch -l status_.state` | stop when that member changes, wherever it is changed |
| `delete` | remove every breakpoint (`delete 1` for one; `info breakpoints` lists them) |
| `kill`, `quit` | stop the program, leave gdb |

The watchpoint is the tool for "who set this?". With the breakpoint above hit, `watch -l status_.state` then
`continue` stops on the line that moves the terminal out of INITIALIZING:

```text
Thread 1 hit Hardware watchpoint 2: -location status_.state
Old value = fmofp::icd::TerminalState::INITIALIZING
New value = fmofp::icd::TerminalState::NORMAL
... in fmofp::comms::CommsComputer::step (this=0x5ff550, rf=0x5ff510, frame=1) at .../comms_computer.cpp:111
111	        status_.state = TerminalState::NORMAL;
```

Write `-l`: without it the watch is tied to the function you set it in and gdb drops it when that function
returns.

The test suite's name is the first argument of `TEST(` in `tests/<name>_test.cpp` (`CommsComputerTest`, not the
class name); `--gtest_filter=CommsComputerTest.*` runs all of one suite, `--gtest_list_tests` lists them.
A function's exact name: `info functions CommsComputer::` in gdb.

## 3. The stdin tool under gdb

Most partitions have a tool that takes one command a line and prints the logic's answer; the Python oracle
tests drive it beside the frozen Python (`fmofp_bus/tests/test_<name>_oracle.py`). The commands are listed in
the comment at the top of `partitions/<name>/tools/<name>_tool.cpp`. When an oracle test fails, put the commands
that lead to the difference in a file and replay them:

```bash
printf 'reset\nelectrical 90 60 28 28 400 0.9\ndata\nstatus\n' > power_cmds.txt
gdb partitions/fmofp_power_tool.exe
```

```text
(gdb) break fmofp::power::PowerManagement::update
(gdb) run < power_cmds.txt
```

The tool answers `ok` to `reset`, then gdb stops inside the `electrical` command:

```text
Thread 1 hit Breakpoint 1, fmofp::power::PowerManagement::update (this=0x5ffb30, electrical=...)
    at .../partitions/power/src/power_management.cpp:244
(gdb) print electrical
$1 = (const fmofp::icd::PlantElectrical &) @0x5ff930: {..., epoch = 1 '\001', generator_override = false, ...
(gdb) finish
(gdb) continue
```

`print electrical` shows the message as the tool built it from your line (the `static k...` members first: the
message's address and size from the ICD, the same for every instance). After `continue` the tool prints the
answers to `data` and `status` and exits.

## 4. A partition on the bus under gdb

A partition does nothing until the bus controller synchronises it: it steps once per minor frame, on the
controller's sync. So two programs: the partition under gdb, and `fmofp_bc` polling it from a second shell.

Shell 1, the partition (any free `--port-base` up to 65000; both programs must be given the same):

```bash
gdb partitions/fmofp_comms.exe
```

```text
(gdb) break fmofp::comms::CommsComputer::step
(gdb) run --port-base 52300 --quiet
```

Nothing happens yet: the partition is waiting for the bus. Shell 2, from the same directory, the controller
for terminal 2 alone (the terminal numbers are in the ICD's table and in `ARCHITECTURE.md`):

```bash
bc/fmofp_bc.exe --rt 2 --port-base 52300 --frames 200 --timeout-ms 1000 --no-command-port
```

Shell 1 stops on the first frame; `continue` stops on the next:

```text
Thread 1 hit Breakpoint 1, fmofp::comms::CommsComputer::step (this=0x5fec20, rf=0x0, frame=1)
(gdb) continue
Thread 1 hit Breakpoint 1, fmofp::comms::CommsComputer::step (this=0x5fec20, rf=0x0, frame=2)
```

Fifty stops a second is too many. Stop on the frame you want with a condition:

```text
(gdb) delete
(gdb) break fmofp::comms::CommsComputer::step if frame == 50
(gdb) continue
Thread 1 hit Breakpoint 2, fmofp::comms::CommsComputer::step (this=0x5fec20, rf=0x0, frame=50)
(gdb) print status_.state
$4 = fmofp::icd::TerminalState::INITIALIZING
```

Read that last answer: the terminal is still INITIALIZING at frame 50 because `rf` is null, and it is null
because nobody is sending the RF environment: that is the plant's message (RT 27) and the plant is not running.
A partition alone on the bus sees no inputs. To give it some, start the plant in a third shell before the
controller and add its terminal (`--rt 27`), from `B20SS/`:

```bash
py -m fmofp_plant --port-base 52300
```

(Other partitions listen to other partitions too: `ARCHITECTURE.md` and the ICD's relay table say who feeds
whom. `B20SS/ofp/README.md`, "Running the partitions", has every process's command line.)

What to expect while you are stopped:

- **The bus does not wait for you.** The controller keeps its 20 ms frames; a terminal stopped in gdb does not
  answer, so the controller counts `no_response` and overruns for it (the run above ended with
  `frames=200 overruns=150 ... no_response=9`). That is the debugger, not a fault. `--timeout-ms 1000` (the
  most the controller accepts) makes it wait up to a second for each answer, which keeps the frame numbers
  close together across a short stop.
- **Frame numbers jump after a long stop.** The partition takes its frame number from the controller's sync;
  the frames that passed while you looked at a variable are gone. A condition `if frame == 50` set while
  stopped at frame 40 may never be met: use `if frame >= 50`.
- **Staleness is real.** A partition counts frames since each input; after a stop it may find its inputs stale
  and go DEGRADED, as it would on the aircraft.
- **When the controller's frames run out** (`--frames 200`) the partition just waits again. Start the
  controller once more for another run (the frame count restarts at 0), or use `--frames 0` to run until
  Ctrl-C.
- **Commands**: to send the partition a command at a known frame, give the controller a script
  (`--script FILE`, lines of `frame rt sa words`; `README.md` shows one), or drop `--no-command-port` and use
  the debug prompt from `B20SS/`: `py -m fmofp_cli --port-base 52300 -c "send COM_CMD ..."`.

To watch the same run from outside while gdb holds the inside: `py -m fmofp_cli --port-base 52300` from
`B20SS/` (`terminals`, `status 2`, `msg COM_STATUS`).

## 5. When it does not work

| What you see | Why |
|---|---|
| The partition exits at once under gdb with an odd exit code, the breakpoint never hit | It could not open its port: another process has it (a run you left behind: `Get-CimInstance Win32_Process` in PowerShell, names `fmofp_*`), or Windows has reserved that range today (`netsh int ipv4 show excludedportrange protocol=udp`). Take another `--port-base`. |
| `fmofp_bc` prints its usage line and stops | An argument it refuses: `--timeout-ms` above 1000, `--port-base` above 65000, no `--rt`. |
| `Function "..." not defined` | The name is wrong (not a guess: `info functions ClassName::`), or the function is in another executable. |
| The program runs but never stops in `step` on the bus | The controller is not running, has another `--port-base`, or was not given this terminal's `--rt`. |
| `<optimized out>` | You are in the `-release` build. |
| The executable does not start from PowerShell or Explorer (a missing DLL) | Run it from the UCRT64 shell, whose `bin` has the compiler's DLLs. |
| `current stack frame does not contain a variable named 'this'` | You are not in a member function any more (the test body, `main`): `up` / `down` move between frames, `bt` shows them. |

## 6. Before you call it fixed

A fault found under gdb is fixed when a test fails without the fix and passes with it. From `B20SS/ofp/`:
`ctest --preset windows-ucrt64`, `cmake --build build/windows-ucrt64 --target cppcheck` and `--target lint`;
then the whole gate, `bash B20SS/verify.sh` from the repository root.
