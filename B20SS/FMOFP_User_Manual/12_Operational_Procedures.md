# 12. Operating Procedures

**Navigation:** [← The Bus](11_Communication_Messaging.md) | [Table of Contents](00_Title_and_TOC.md) | [Maintenance →](13_System_Maintenance.md)

---

All commands are run from `B20SS`. Build first (chapter 13 or [Getting Started](00a_Getting_Started.md)).

## 12.1 Flying the demo

```bash
py -m fmofp_demo
```

starts the bus controller, the plant, every partition and the six display windows, prints one dashboard line a second
and plays the scripted flight. Ctrl-C stops everything. `py FMOFP/Main.py` does the same.

| Option | Effect |
|---|---|
| `--seconds S` | stop after S seconds |
| `--headless` | no windows (the display terminals still run, offscreen) |
| `--no-displays` | no display terminals at all |
| `--no-events` | no scripted flight |
| `--hold heading=0,speed=450` | plant quantities held (the default; `--hold ""` frees them) |
| `--walk` | the plant's random walk instead of the flight dynamics |
| `--seed N` | a repeatable sky, traffic and ground |
| `--theme classic|modern|night` | the displays' theme (modern: the holographic PFD and MFD) |
| `--mode day|night|nvg` | every display's lighting mode at 0.5 s |
| `--record [DIR]` | run the recorder beside the flight (`logs/recorder/` by default) |
| `--port-base N` | another set of ports (to run beside another bus) |
| `--build DIR` | the C++ build to fly (default: the optimised one when built) |
| `--log-dir DIR` | where the programs' logs go (default `logs/demo/`) |

**The dashboard** shows, a line a second: altitude, airspeed, heading, the FMS's mode and weapons state, GCAS, the
engines and fuel, each radar's mode, the mission phase, route progress and briefing, comms, defensive systems,
sensors, power, surfaces, hydraulics, cabin, gear, the recorder, avionics, the crew alert counts, the stores, the
navigation fix, and how many terminals answered. The scripted events print as they are sent (`>> t=36 s: ...`).

## 12.2 The debug prompt

```bash
py -m fmofp_cli
```

asks the bus controller for its own copy of the monitor stream, so it runs beside the demo, a scenario and other
prompts. `-c COMMAND` (repeatable) runs commands and exits:

```bash
py -m fmofp_cli -c terminals -c "status radar"
```

| Command | Does |
|---|---|
| `frame` | the controller's frame count and the seconds it has run |
| `terminals` | every terminal: state, health, faults, ICD version, last command number, when it last answered |
| `status RT|name` | a terminal's TERM_STATUS and the latest of each message it transmits |
| `msgs` | the message ids seen |
| `msg ID [RT]` | the latest message with that id, field by field |
| `send ID field=value ...` | any command message: enums by name or number, booleans 1/0; the controller numbers it |
| `do` | lists the named shortcuts (upstream's canned messages) |
| `do NAME ...` | `wx`, `tfr`, `sar`, `tgt`, `tgt-lock`, `aewc`, `aewc-sector`, `attitude`, `nav`, `autopilot`, `maneuver`, `surface`, `flight-mode`; `objective`, `roe`, `intel`, `clear-objectives`, `clear-roe`, `clear-intel`; readings `precipitation`, `vil`, `echo-top`, `elevation`, `imagery`, `tracks` |
| `mode DAY|NIGHT|NVG [display ...]` | the displays' lighting mode (all six, or `radar pfd mfd eicas tsd sms`) |
| `test list` / `test SUITE ...` | the port's tests for upstream's nine suites (by name or number 1-9) and the rest, in a child process |
| `scenario load FILE`, `events`, `start [speed]`, `stop`, `status` | a scenario run from the prompt |
| `tables`, `table NAME [N]` | the recorder's tables |
| `help`, `quit` | |

A command's acknowledgement (`OK, queued at frame ... (cmd_seq 101)`) means the controller queued it; whether the
terminal acted on it is in its status (`last_cmd_seq`, `cmd_rejected`, and the command status fields).

## 12.3 Scenarios

The frozen training and failure scenarios (`FMOFP/Interfaces/scenarios/*.xml`) run against a flying aircraft as bus
commands, timed by the bus frame:

```bash
py -m fmofp_scenario FMOFP/Interfaces/scenarios/trainingScenario.xml
py -m fmofp_scenario FMOFP/Interfaces/scenarios/failureScenario.xml --speed 10
```

Waypoints and phases become `MSN_CMD`, threats `DEF_CMD INJECT_THREAT`, failures `AVN_CMD FORCE_FAULT`; radar contacts
and weather cells are injected into the plant's traffic and sky, where the radars find them. One line is printed per
event with its acknowledgement. From the prompt: `scenario load trainingScenario.xml`, `scenario start 10`,
`scenario status`.

## 12.4 Recording

```bash
py -m fmofp_recorder
```

writes, beside a flying aircraft, the database tables the original services wrote (`comms_data`, `defensive_events`,
`fuel_tanks`, `engines`, `fuel_lines`, `ecu_data`, `fcs_data`, `surface_data`, `mission_data`, `pms_data`), in their
files and columns, under `logs/recorder/`, from the values the bus carries. `py -m fmofp_demo --record` runs it with
the demo. Read them back from the prompt:

```
fmofp> tables
fmofp> table fcs_data 5
```

## 12.5 A typical exercise

1. `py -m fmofp_demo --no-events` (a quiet aircraft).
2. In a second terminal, `py -m fmofp_cli`.
3. `do flight-mode COMBAT`, then `msg FMS_STATUS`: the weapons state is ARMED; the SMS's master arm follows.
4. `send MSN_CMD command=SET_PHASE phase=INGRESS`: the five radars come on (`status radar`).
5. `do tgt-lock 1` after `do tracks` shows a track: the targeting radar locks.
6. `send DEF_CMD command=DISPENSE_CHAFF count=2`: the EICAS's chaff count drops.
7. `do surface ELEVATOR 10`, then `do surface ELEVATOR 0`: the PFD shows the climb.
8. `mode night`: every display to night mode.
