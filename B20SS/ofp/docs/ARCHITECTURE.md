# FMOFP on the bus: the architecture in one page

Read this first. It says what runs, how the pieces talk, and where to look when
something is wrong. The rules are in other files and this page points at them:
`B20SS/ofp/CLAUDE.md` (the C++ rules), `B20SS/icd/README.md` (the bus), the
repository's root `CLAUDE.md` (the port's state and history).

## What this is

FMOFP simulates the avionics of a fictional aircraft, the B20SS. It began as one
Python program. The flight software, everything that *decides* something about the
aircraft, is now C++17 under `B20SS/ofp/`. The displays, the simulated world and the
tests are still Python. The original Python program is kept unchanged under
`B20SS/FMOFP/` ("frozen"): the C++ is measured against it.

## The one rule

**Programs talk only over the bus.** There is no shared memory, no shared file and
no other socket between two subsystems. The bus is a simulated MIL-STD-1553B: 16-bit
words carried in UDP datagrams on 127.0.0.1. If a subsystem needs a value, that value
is in a bus message, and the message is defined in the ICD.

## What runs

```
                    +---------------------------+
                    |  bus controller fmofp_bc  |   starts every transfer; the master clock
                    +-------------+-------------+
                                  |  the bus (UDP 127.0.0.1, port_base + address)
   +--------------+---------------+----------------+------------------+
   |              |                                |                  |
+--+----------+ +-+-----------------------------+ ++---------------+ ++-----------------+
| plant RT 27 | | 16 C++ partitions             | | 6 displays     | | clients          |
| (Python)    | | FCS 5, nav 7, FMS 12, radar 9,| | (Python, PyQt6)| | (Python)         |
| the world:  | | engine 3, mission 6, comms 2, | | radar 15,      | | scenario engine, |
| flight state| | defensive 22, sensors 10,     | | PFD 11, MFD 13,| | debug CLI: they  |
| weather,    | | power 8, surfaces 21, ECS 4,  | | EICAS 14,      | | send commands    |
| terrain,    | | hydraulics 19, airframe 20,   | | TSD 16, SMS 17 | | through the      |
| traffic ... | | recorder 23, avionics 1       | |                | | controller       |
+-------------+ +-------------------------------+ +----------------+ +------------------+
```

- **A partition** is one subsystem in one process: one terminal on the bus with a fixed
  address (its *RT* number). All of its code is under `ofp/partitions/<name>/`.
- **The plant** is the aircraft and the world it flies in: everything a real sensor
  would *measure*. It is test equipment, not flight software.
- **A display** is the original Python display class, unchanged, fed from the bus by
  the code in `B20SS/fmofp_display/`.
- **The bus controller** is the only program that starts a transfer. Terminals only
  answer.

`py -m fmofp_demo` (from `B20SS/`) starts all of it and prints one line a second of
what is crossing the bus.

## Time

The controller cuts time into **minor frames of 20 ms**, fifty to the second. Each
frame it:

1. broadcasts a *sync* (mode code 17) carrying the frame number;
2. runs that frame's scheduled transfers: it polls each message that is due and
   copies it on to whoever consumes it;
3. sends any queued commands;
4. sleeps until the next frame's deadline.

A partition does one frame of work when the sync arrives, never on its own clock.
That is why the whole system can be run in real time, as fast as it will go
(`--free-run`, which the tests use), or one frame at a time, and behave the same.

A message has a rate: 50, 25, 10, 5 or 1 Hz, or *aperiodic* (a command, sent once).
The schedule may fill at most half of each frame, 10000 microseconds;
`fmofp_bc --schedule --rt ...` prints the estimate, and the controller refuses a
schedule that does not fit. A frame whose work runs past the next deadline is an
**overrun**. `fmofp_bc --report` says, when it stops, which terminal was slowest in
each overrun frame.

## The ICD

`B20SS/icd/fmofp_icd.xml` defines every message: its terminal and subaddress, its
rate, and every field down to the bit. **Nothing else may define a message.** From
it the build generates:

- C++ structs with `encode()` and `decode()`: `fmofp/icd/messages.hpp`, in the build
  directory;
- the same in Python: `B20SS/fmofp_bus/icd/`;
- `B20SS/icd/ICD_TABLES.md`, the tables to read.

To change what goes on the bus you change the XML, run
`py icd/tools/icd_tool.py check`, and regenerate. You never write a layout by hand
and never edit a generated file.

Three ways a message reaches its consumer:

| How | When | In the XML |
|---|---|---|
| **Relay** | one consumer | `<relay from="A" to="B">`: the controller polls A and writes the same words into B |
| **Broadcast** | two or more consumers | a relay to address 31; each listener accepts that subaddress |
| **Block** | more than 32 words (a radar picture) | a descriptor and 32-word segments, with a checksum; `bus/block.hpp` |

Two conventions you will meet in every message:

- **Validity.** A measured value carries a two-bit *SSM*. `NORMAL` means believe it.
  `NO_COMPUTED_DATA` means unknown or stale. Zero means failure, so a message that was
  never filled reads as failed, not as a plausible number.
- **Commands.** A command carries `cmd_seq`. The terminal acts when the number is new
  and reports the last one it took. Zero means "no command".

## Inside a partition

Every partition has the same four files (`partitions/comms/` is the smallest to read):

| File | What it is |
|---|---|
| `include/fmofp/<name>/<name>.hpp`, `src/<name>.cpp` | The logic: a class with `init()`, `step()` and `status()`. ICD messages in, ICD messages out. No sockets, no printing, no clock. |
| `src/main.cpp` | The process: open the terminal, and on every sync take what arrived, call `step()`, load what the logic produced. |
| `tools/<name>_tool.cpp` | The same logic on stdin and stdout, so a Python test can drive it. Test support, not flight code. |
| `ofp/tests/<name>_test.cpp` | GoogleTest unit tests of the logic. |

Because the logic class touches nothing but messages, you can run it in a unit test,
in the stdin tool or under a debugger with no bus at all. Start there when a
subsystem misbehaves.

The C++ is restricted on purpose (`ofp/CLAUDE.md`): no heap after start-up, no
exceptions, every function that can fail returns a `Status` you must look at, every
warning is an error.

## World and logic

When a Python subsystem was moved to C++, each thing it did went one of two ways:

- what a real aircraft would **measure** (it was a random draw or a made-up reading
  in the Python) went to the plant, `B20SS/fmofp_plant/`;
- what the real computer would **decide** (rules, thresholds, state machines,
  filters) went to the C++ partition.

The logic was translated step for step, *including its mistakes*, unless a mistake
made the function unusable. Each such mistake is written down in section 2 of
`B20SS/icd/README.md` with the test that proves the Python behaved that way. Those
rows are where the training tickets come from: the C++ does exactly what the Python
did, and some of what the Python did is wrong.

## How it is tested

| Kind | Where | What it shows |
|---|---|---|
| Unit tests | `ofp/tests/*_test.cpp` (GoogleTest) | A module does what its code says |
| Oracle tests | `fmofp_bus/tests/test_*_oracle.py` | The C++ gives the same answers as the frozen Python on the same inputs, through the stdin tool |
| End-to-end tests | `fmofp_bus/tests/test_*_e2e.py` | The real processes, under the real controller, exchange the right messages |
| Display tests | `test_display_*.py` | The bus data becomes what the displays draw |
| Timing test | `test_timing.py` | Every partition answers well inside the frame; the schedule fits the budget |

`bash B20SS/verify.sh` runs all of it and must pass before anything is pushed. An
oracle test that fails means the C++ and the Python disagree: find out which one
changed before you touch either.

## Where things are

| Path | Contents |
|---|---|
| `B20SS/icd/` | The ICD: the XML, its README (conventions, decisions, backlog), the generated tables, the tool |
| `B20SS/ofp/bus/`, `osal/` | The bus in C++ (words, terminals, blocks) and the thin layer over the clock and UDP |
| `B20SS/ofp/bc/` | The bus controller: schedule, frame loop, the bus health report, the command port |
| `B20SS/ofp/partitions/` | One directory per partition |
| `B20SS/ofp/tests/` | The C++ unit tests |
| `B20SS/fmofp_bus/` | The bus in Python, and every Python test of the port (`tests/`) |
| `B20SS/fmofp_plant/` | The plant |
| `B20SS/fmofp_display/` | The display terminals and their feeds |
| `B20SS/fmofp_demo/`, `fmofp_scenario/`, `fmofp_cli/` | The launcher, the scenario engine, the debug prompt |
| `B20SS/FMOFP/` | The frozen Python application. Read it; do not edit it |

## When something is wrong

1. **Is it on the bus?** `py -m fmofp_cli` with the aircraft running: `terminals`
   shows who answers, `msg ID` the latest copy of a message, `status RT` a terminal.
2. **Is the value marked valid?** Look at its SSM before believing the number.
3. **Which side produced it?** A measurement comes from the plant; a decision from a
   partition. The ICD README's version paragraphs say which message carries what.
4. **Reproduce it without the bus.** Feed the partition's stdin tool the inputs, or
   write a unit test that calls `step()`.
5. **Compare with the Python.** The oracle test for the subsystem shows how the
   frozen module is driven; the ICD README section 2 lists what is known to be odd.
