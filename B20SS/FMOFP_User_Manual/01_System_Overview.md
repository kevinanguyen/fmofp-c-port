# 1. System Overview & Architecture

**Navigation:** [← Legal Information](00b_Legal_Information.md) | [Table of Contents](00_Title_and_TOC.md) | [Weather Radar →](02_Weather_Radar_System.md)

---

## 1.1 What FMOFP is

FMOFP simulates the avionics of a combat aircraft as a set of independent programs joined by one data bus, the way
a real aircraft's computers are joined by MIL-STD-1553B. Each program is one box of the aircraft: a flight control
computer, a navigation computer, a radar computer, an engine computer, a display. No program reads another's
memory or files; everything one knows about another arrives as 16-bit words on the bus, at the rate the bus
schedule gives it.

The interns' work is the flight software, which is C++ written to avionics rules. The displays, the simulated world
and the tools around them are Python, because they are not flight software.

## 1.2 The pieces

```
                         +------------------------------+
                         |  bus controller  (fmofp_bc)  |  the master clock: 50 frames a second
                         +------------------------------+
                                       |  simulated MIL-STD-1553B over UDP on 127.0.0.1
   +-------------------------------------------------------------------------------------+
   |            |              |              |               |              |           |
 C++ partitions (flight software)    Python displays       plant (RT 27)    clients of the controller
 FCS, nav, FMS, radar, engine,       radar, PFD, MFD,      the simulated    the prompt, the scenario
 mission, comms, defensive,          EICAS, TSD, SMS       world            engine, the recorder,
 sensors, power, surfaces, ECS,                                             the demo's dashboard
 hydraulics, airframe, FDM,
 avionics, crew alerting, stores
```

| Piece | What it is | Where |
|---|---|---|
| Bus controller | The one bus master: polls every terminal on a fixed schedule, relays messages from producers to consumers, sends the synchronise mode code that starts each 20 ms frame. Also takes commands from client programs on its command port and copies the bus traffic to monitors | `B20SS/ofp/bc`, `fmofp_bc` |
| Partitions | The flight software, one process per subsystem, C++17 | `B20SS/ofp/partitions/<name>` |
| Plant | Everything the aircraft would *measure*: its own flight state, GPS ranges, weather, terrain, other aircraft, the ground, radio fields, emitters, engine readings, electrical readings, cabin, hydraulic pressures, airframe gauges | `B20SS/fmofp_plant`, `py -m fmofp_plant` |
| Displays | The original FMOFP display classes, unchanged, each in its own program and fed from the bus | `B20SS/fmofp_display`, `py -m fmofp_display` |
| Demo | Starts all of the above, prints a dashboard, plays a scripted flight | `B20SS/fmofp_demo`, `py -m fmofp_demo` |
| Prompt | A debug command line on the bus | `B20SS/fmofp_cli`, `py -m fmofp_cli` |
| Scenario engine | Plays the frozen training and failure scenarios as bus commands | `B20SS/fmofp_scenario` |
| Recorder | Writes the services' database tables from the bus traffic | `B20SS/fmofp_recorder` |
| ICD | The interface control document: every message, field and relay; generates the C++ and Python message code | `B20SS/icd` |

## 1.3 The rule that shapes everything: world in the plant, logic in C++

When the port moved a Python subsystem to C++, it split it in two. Whatever the real aircraft would *measure* went to
the plant: the Python's random walks, invented readings, generated detections. Whatever the real aircraft's computer
would *decide* went to C++: rules, thresholds, state machines, filters, bookkeeping. So the C++ radar computer
renders a weather volume and tracks targets, but the storm cells and the aircraft it sees are the plant's; the
engine computer runs the autothrottle and the fuel policy, but N1 and EGT come from the plant's engine model.

The C++ logic is translated step for step from the frozen Python, quirks included, and the tests hold it to the
Python (oracle tests). Where a quirk made a function unusable the port departed from it; every departure is a row
in `B20SS/icd/README.md`, section 2.

## 1.4 The bus in one page

- **Words and transactions.** Every message is a list of 16-bit words. The controller sends a command word to a
  terminal (receive or transmit, subaddress, word count); the terminal answers with a status word and, for a
  transmit, its data. A relay is a transmit from one terminal followed by a receive into another, in the same slot.
- **Addresses.** Each terminal has a remote terminal address (RT 1 to 30; 31 is broadcast). Chapter 14 lists them.
  Each message has a subaddress within its terminal.
- **The frame.** The controller runs 20 ms minor frames, 50 to a major frame (one second). Messages are scheduled at
  50, 25, 10, 5 or 1 Hz, or sent once (aperiodic: commands). The controller refuses a schedule whose busiest frame
  would exceed 10 ms; today's worst frame is estimated at 8.8 ms.
- **Validity.** Every measured value carries a two-bit sign/status matrix (SSM): NORMAL, NO_COMPUTED_DATA (unknown or
  stale), FUNCTIONAL_TEST, FAILURE_WARNING (zero, the fail-safe value). Displays cross out what is not NORMAL.
- **Commands** carry a sequence number (`cmd_seq`); a terminal acts on a command only when its number differs from
  the last one it accepted, and reports the last number and whether it was rejected.
- **Transport.** Each terminal is a UDP socket on 127.0.0.1 at `port_base + RT` (port base 51000 by default); the
  controller is at `+32`, its monitor stream at `+33`, its command port at `+34`.

Chapter 11 explains the bus and its tools in full.

## 1.5 What runs in the demo

| RT | Terminal | Language | Chapter |
|---|---|---|---|
| 1 | Avionics: LRU health, built-in tests, fitness, software configuration | C++ | 10 |
| 2 | Communications | C++ | 10 |
| 3 | Engine management and fuel | C++ | 10 |
| 4 | Environmental control | C++ | 10 |
| 5 | Flight control computer (GCAS, envelope, surface commands) | C++ | 10 |
| 6 | Mission computer | C++ | 10 |
| 7 | Navigation (GPS solution, fusion) | C++ | 10 |
| 8 | Power management | C++ | 10 |
| 9 | Radar computer: weather, terrain-following, targeting, AEWC, SAR, track fusion | C++ | 2-6 |
| 10 | Sensor management | C++ | 10 |
| 11 | PFD | Python | 7 |
| 12 | Flight management system | C++ | 10 |
| 13 | MFD | Python | 8 |
| 14 | EICAS | Python | 8 |
| 15 | Radar display (control panel and pictures) | Python | 2-6 |
| 16 | TSD | Python | 8 |
| 17 | SMS | Python | 8 |
| 19 | Hydraulics | C++ | 10 |
| 20 | Airframe | C++ | 10 |
| 21 | Flight surfaces | C++ | 10 |
| 22 | Defensive systems | C++ | 10 |
| 23 | Flight data monitoring (recorder) | C++ | 10 |
| 26 | Crew alerting | C++ | 8 |
| 27 | Plant | Python | 10 |
| 28 | Stores management | C++ | 8 |

## 1.6 How a frame goes

1. The controller sends the synchronise mode code to every terminal: frame *n* begins.
2. Each terminal steps once: it reads what arrived since the last frame, runs its logic and loads its outputs.
3. The controller polls the frame's scheduled messages: relays from producers to consumers, broadcasts to all
   listeners, and any command a client queued.
4. Every transaction is copied to the monitor stream, which the dashboard, the prompt and the recorder read.

A terminal that answers late makes the frame overrun; the controller counts overruns and, with `--report`, says which
terminal was slowest.

## 1.7 System requirements

- Windows 10 or later with MSYS2 UCRT64, or Linux (CI uses Ubuntu).
- Python 3.10 or newer with PyQt6 6.8.1, numpy, scipy, qasync and click.
- A quiet machine for the real-time demo: the bus runs in real time, and a busy machine (a game, a large build) shows
  as overruns, not as wrong answers.
