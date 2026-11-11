# FMOFP Python-to-C++ port: the shared working file

**Read this whole file before doing anything else in this repository.** Two people take
turns on this fork, Kevin (the owner, GitHub `kevinanguyen`) and Alee (GitHub `TubAleeLo`,
who also owns the upstream repository this fork came from), each driving Claude (Fable 5.1)
in their own sessions, on their own machines, at different times. This file is how one
session hands the work to the next. It is checked in on branch `port/cpp`, Claude Code
loads it automatically, and **the copy on disk is only as current as the last `git pull`**,
so the first thing every session does is pull (section 0). The last thing every session
does is update this file and push it with the work (section 0.4). A session that does not
push is invisible to the other person; a session that does not pull may redo or undo their
work.

Section numbers are anchors both agents rely on: add to sections, do not renumber them.
Sections 7 and 8 are append-only.

Contents: 0 session protocol · 1 current state · 2 the units (progress meter, with the open
units' details) · 3 how a unit is ported · 4 rules · 5 machines, tools, commands · 6 gotchas
· 7 unit log · 8 decisions.

---

## 0. Session protocol (mandatory for both agents)

### 0.1 Start of every session, before reading code or answering anything about the project

1. `git status --short` must print nothing. If it does not, report it to your human and do
   not stash, reset or commit it blindly: it may be the other person's unfinished work on a
   shared machine, or your own from a session that died.
2. `git fetch origin && git fetch upstream`, then `git checkout port/cpp`, then
   `git pull --ff-only origin port/cpp`. If the pull is not a fast-forward, someone committed
   locally without pushing: stop and ask.
3. If the pull changed this file (`git diff --stat ORIG_HEAD HEAD -- CLAUDE.md` prints a
   line), **read this file again in full**: the copy Claude Code loaded at session start is
   stale.
4. Read section 1 (current state) and the last entries of section 7 (unit log). Look for any
   unit marked `IN PROGRESS` or any `wip/` branch named in section 1: that is the other
   person's open work.
5. `git log --oneline HEAD..upstream/main`: if it prints anything, Alee's upstream has
   moved; apply the merge rule (section 4.4) before starting a unit.
6. On a machine's first session: do the setup of section 5 and run `bash B20SS/verify.sh`
   until it is green before changing anything. Then say so in section 7.

### 0.2 Claim a unit before building it

Set the unit's status in the section 2 table to `IN PROGRESS (<name>, <date>)`, commit that
one-line change ("Claim unit N: <name>") and push. It costs a minute and keeps the two of you
from porting the same subsystem. If a unit is already claimed by the other person and the
claim is less than two days old, take another unit or ask your human. A claim older than that
with no `wip/` branch and no log entry is stale: say so in section 7 and take the unit.

### 0.3 While working

One unit at a time, done to the standard of section 3: code, tests, ICD, docs and this file
together. Do not start a second unit in the same commit. Record decisions as they are made
(section 8), not at the end.

### 0.4 End of every turn that changed anything (that is, after every prompt)

1. **Update this file**: section 1 (current state block), the unit's row in section 2, a
   section 7 entry (what was done, how, warnings and lessons, files, tests, numbers), new
   gotchas in section 6, any decision in section 8, and the details of an open unit if you
   learned something about it.
2. **Verify**: `bash B20SS/verify.sh` (section 5.5) must be green. For a change that touches
   only documents, the `icd` step is enough. Never push red to `port/cpp`.
3. **Commit and push**: `git add` the files you changed (never `git add -A` without reading
   `git status`), commit with a message in the style of section 4.6, then
   `git push origin port/cpp`. If the push is rejected, `git pull --rebase origin port/cpp`,
   re-run `verify.sh` if any code conflicted, push again. Never force-push `port/cpp`.
4. **Tell your human** in plain words: what was done, the commit id, the conversion
   percentage with the time left (section 4.7), what is next, and the one decision they must
   make, if any.

A turn that changed nothing in the repository (a question answered) needs no commit: say so.
A decision made in conversation **is** a change: write it in section 8 and push.

Unfinished work never stays on `port/cpp`. If a unit cannot be brought to green before the
session ends, commit it on a branch `wip/<unit>` (tests may be red there), push that branch,
and record in section 1 and section 7 what works, what does not, and the next step. Either
person may continue it in their next session; when it is green it is rebased onto
`port/cpp` (one commit) and the `wip/` branch deleted.

### 0.5 Never

- Never push to `upstream` (TubAleeLo/fmofp, Alee's repository). Keep its push URL disabled:
  `git remote set-url --push upstream DISABLED`.
- Never force-push or rewrite history on `port/cpp`.
- Never edit the frozen Python under `B20SS/FMOFP/` except by merging upstream (section
  4.4). The C++ is measured against that Python.
- Never commit build directories, logs, databases or anything under `B20SS/logs/`.
- Never put the other person's or your own secrets, tokens or passwords anywhere in the
  repository, including this file.
- Never delete or rewrite entries of sections 7 and 8; append corrections.

---

## 1. Current state (rewrite this block; keep it short and exact)

- **Branch** `port/cpp` on `origin` = github.com/kevinanguyen/fmofp-c-port (renamed from
  `fmofp` on 2026-11-04; the old URL redirects, new clones use the new name). HEAD: see
  `git log -1`. Last milestone: `c78d4af` unit 28 scenario engine + debug CLI, ICD v1.23 (2026-11-10, section 7; CI run
  42941262908 all ten jobs green). Before it: `6497634` unit 17 avionics, ICD v1.20
  (2026-11-10, section 7; landed after v1.22; CI run 42925246480 all ten jobs green), `888eafe` unit 20 small
  utilities, ICD v1.22 (2026-11-10, section 7; CI run 42900090742 green), `337820b` unit 19 flight surfaces, ICD
  v1.21 (2026-11-10, CI run 42885140093, section 7), `a63556e` unit 16 power management, ICD v1.19 (2026-11-08; CI
  run 42507980864 all ten jobs green), `c4057ed` (unit 15 sensor management, ICD v1.18; CI run 42439181347 all ten
  jobs green), `d718e09` (unit 18 defensive systems, ICD v1.17; CI run 42435137866: eight green, `linux-gcc` red on
  one unanswered poll in the display e2e on the slow runner, the same code green on the next run, the Linux 3.13
  Python leg red on the flaky `test_weather_radar_live`), `782078f` (the rename and Alee), `8d67afd` (this file and
  `B20SS/verify.sh`), `d82173f` (merge of upstream/main `4c25f52`), `051e57d` (mission computer + comms, ICD v1.16).
- **ICD** v1.23 (`B20SS/icd/fmofp_icd.xml`; the next unit takes v1.24): 26 terminals, 154 message definitions
  (200 after per-terminal expansion), 50 message relays (15 broadcast), 24 block streams (12 layouts, 12 relayed
  copies), 9 mode codes, 89/89 legacy types mapped. The bus controller has a **command port** at `port_base + 34`
  since v1.23 (ICD README section 7): a client queues a receive transaction and is acknowledged with the
  controller's frame count; `fmofp_bus/command_port.py` is the Python client, `fmofp_bus/bus_view.py` the monitor
  reader both clients use.
- **C++ partitions (processes)**: FCS (RT 5), nav (RT 7), FMS (RT 12), radar computer
  (RT 9: weather, terrain-following, targeting + track fusion, AEWC, synthetic aperture),
  engine management (RT 3), mission computer (RT 6), communications (RT 2), defensive
  systems (RT 22), sensor management (RT 10), power management (RT 8), flight surfaces
  (RT 21), environmental control (RT 4), hydraulics (RT 19), airframe systems (RT 20), flight
  data monitoring (RT 23), avionics (RT 1: LRU health, built-in tests, fitness, software
  configuration); the bus controller `fmofp_bc`, which also writes `AVN_BUS_HEALTH` for RT 1 once
  a second and takes the clients' commands on its command port (`--no-command-port` closes it); tools
  `fmofp_nav_tool`, `fmofp_radar_tool`, `fmofp_engine_tool`, `fmofp_mission_tool`, `fmofp_defensive_tool`,
  `fmofp_sensor_tool`, `fmofp_power_tool`, `fmofp_surfaces_tool`, `fmofp_utilities_tool`,
  `fmofp_avionics_tool` (stdin oracles for the Python tests).
- **Python test equipment on the bus**: the plant `py -m fmofp_plant` (RT 27: the aircraft's
  random-walk flight state, GPS pseudoranges, weather, terrain, two engines, air traffic, the
  ground scene, the RF environment, the ESM intercepts, the sensor scans, the electrical
  readings, the cabin, the hydraulic pressures, the airframe gauges; since v1.23 it takes the scenario engine's
  injections, an aircraft into its traffic and a storm cell into its sky); six display terminals
  `py -m fmofp_display radar|pfd|mfd|eicas|tsd|sms` (RT 15, 11, 13, 14, 16, 17), each an unchanged FMOFP display
  class fed from the bus through `fmofp_display/*_feed.py`; the one-command demo `py -m fmofp_demo`; **the scenario
  engine** `py -m fmofp_scenario FILE [--speed S]` (`fmofp_scenario/`: the frozen `Interfaces/scenarios/*.xml` fired
  as bus commands through the command port, timed by the bus frame) and **the debug CLI** `py -m fmofp_cli [-c CMD]`
  (`fmofp_cli/`: `terminals`, `status`, `msg` from the monitor, `send ID field=value` of any ICD command, the
  `scenario` commands); the bus library `fmofp_bus` with generated `fmofp_bus/icd/`.
- **Load**: 23 terminals, 107 scheduled messages, worst minor frame 8612 us of the 10000 us budget (the
  schedule's estimate). The real-time demo, thirty seconds headless with the scripted events, 1500 frames, 23/23
  answering: on Alee's machine 26-42 overruns before unit 30's first part and, after it (2026-11-11), 0-9 on the
  debug build (seven runs: 7, 1, 7, 0, 6, 4, 9) and 0-6 on the optimised build (1, 5, 6, 1, 0, 0, and one run of 91
  in which 69 frames started late and every terminal was slow at once: the machine, section 7). Kevin's machine,
  before that part: 2-3 overruns with 23 terminals (13 right after the gate), 0 with 22; after it, with the
  optimised build (2026-11-11, section 7): three runs, 1500 frames each, 0 overruns in all three, worst frame 11.5, 9.5 and 9.7 ms (24-26 ms on the debug build the day before), 23/23 answering, 19 scripted commands sent. `fmofp_bc --report` now says which terminal held each overrun frame up (section
  5.5).
- **Tests**: Python 298 OK (`fmofp_bus/tests`, about 65 s on Kevin's machine, 80 s on Alee's); C++
  ctest 2/2 (320 hand-written gtests + generated ICD round-trip tests) on the debug build and on the optimised
  one, cppcheck clean; the whole Python suite also passes against the optimised build (`PRESET=<preset>-release
  bash B20SS/verify.sh cpp py load`); CI (`.github/workflows/ci.yml` job `cpp`: linux-gcc, linux-asan and, since
  unit 30, linux-gcc-release; and Alee's eight Python legs).
- **Meter**: 27 of 29.5 units = **92 %** (section 2). Pace measured over the log: about
  5 units per full working day, so about half a day more to 100 % (2 units open: 29, 30); the
  intern-ticket authoring phase comes after and is not in the number.
- **Upstream**: merged through `4c25f52` (2026-11-02). Port baseline for the ported logic
  stays `0ab9236` (Alee's freeze, 2026-10-10); later upstream commits have been plumbing and
  lint only.
- **Open work / claims**: unit 30 hardening is `IN PROGRESS (Alee, 2026-11-11)`, on `port/cpp` in parts, each
  green (no `wip/` branch). Part 1 landed 2026-11-11 (section 7): the demo's overruns traced and cut (the block
  CRC in C, the optimised build preset the demo prefers, the controller's timing report, test port bases that
  step off Windows' reserved ranges). Left in unit 30 (section 2.30): the timing test, gcovr thresholds in CI, the
  MISRA-subset lint, the display processes' loggers at WARNING, the intern documents. Then unit 29, last (it cuts
  the upstream line, section 2.29; both humans decide what `py FMOFP/Main.py` becomes). Last session: Kevin's,
  2026-11-11 (the check after part 1 landed: the gate green here on both builds, the optimised build's demo
  measured); before it Alee's part 1 the same day.
- **Known red in CI that is not ours**: Alee's `test_weather_radar_live` is flaky on the
  Windows and 3.12 Python legs (again on the Windows 3.13 leg of run 41932029106, the Linux 3.13
  leg of 42435137866, the Windows 3.13 leg of 42729856922 and the Linux 3.14 leg of 42931963850); the two
  `cpp` jobs are the ones that judge the port.
- **Known flaky in our own `cpp` job**: the display e2e runs the bus under `--strict` with
  seven Python terminals; the slow Linux runner answered one poll late in run 42435137866
  (worst frame 48 ms, exit 1, the next run of the same code green). Its poll timeout is 40 ms
  since unit 15; if it reds again, rerun the job before suspecting the code. The demo test
  (`test_demo.DemoRunTest`) was red once the same way (run 42728027159: 17 overruns in 400 frames
  on the runner, the 7 s radio event not yet on the last dashboard line of an 8 s run); it runs
  ten seconds since 2026-11-09. Every terminal added makes the runner's real-time demo harder
  (23 terminals since unit 17; unit 28 added none): unit 30 should give CI a lighter whole-aircraft check or a
  longer window. Unit 28's scenario e2e runs the controller free-running with four Python terminals under
  `--strict`, like the other e2e tests; its two scenarios take about 10 s together.

---

## 2. The units (progress meter)

Percentage = done weight / 29.5. Weights are rough equal-effort units; change one only with
a reason written in section 8. Status values: `open`, `IN PROGRESS (<name>, <date>)`,
`DONE <date>` (with the section 7 entry), `STRUCK <date>` (with the decision in section 8).

| # | Unit | Weight | Status |
|---|---|---|---|
| 1 | Bus core: words, RemoteTerminal, bus controller, transport, OSAL | 2 | DONE 2026-10-10 |
| 2 | ICD + C++/Python generators + checks | 1 | DONE 2026-10-10 |
| 3 | Python bus library + plant framework + monitor | 1 | DONE 2026-10-10 |
| 4 | FCS partition (RT 5) | 1 | DONE 2026-10-10 |
| 5 | Nav partition (RT 7) | 1 | DONE 2026-10-11 |
| 6 | FMS partition (RT 12) | 1.5 | DONE 2026-10-11 |
| 7 | Weather radar (RT 9) | 2 | DONE 2026-10-11 |
| 8 | Terrain-following radar | 1 | DONE 2026-10-25 |
| 9 | Engine management (RT 3) | 1 | DONE 2026-10-25 |
| 10 | Targeting radar + track fusion | 1.5 | DONE 2026-11-01 |
| 11 | AEWC radar | 1 | DONE 2026-11-01 |
| 12 | SAR radar | 1 | DONE 2026-11-01 |
| 13 | Mission computer (RT 6) | 1 | DONE 2026-11-02 |
| 14 | Communications (RT 2) | 0.5 | DONE 2026-11-02 |
| 15 | Sensor management (RT 10) | 0.75 | DONE 2026-11-08 |
| 16 | Power management (RT 8) | 0.75 | DONE 2026-11-08 |
| 17 | Avionics: LRU health + BIT + fitness + SW configuration (RT 1) | 1 | DONE 2026-11-10 |
| 18 | Defensive systems (RT 22) | 0.5 | DONE 2026-11-07 |
| 19 | Flight surfaces (RT 21) | 0.5 | DONE 2026-11-10 |
| 20 | Small utilities: ECS (RT 4), hydraulics (RT 19), airframe (RT 20), flight data monitoring (RT 23) | 1 | DONE 2026-11-10 |
| 21 | Radar display + PFD on the bus | 1.5 | DONE 2026-10-25 |
| 22 | MFD on the bus | 1 | DONE 2026-10-25 |
| 23 | Broadcast relays | 0.5 | DONE 2026-10-25 |
| 24 | EICAS on the bus | 0.5 | DONE 2026-11-01 |
| 25 | TSD on the bus | 0.5 | DONE 2026-11-01 |
| 26 | SMS on the bus | 0.5 | DONE 2026-11-02 |
| 27 | HUD on the bus | 0.5 | STRUCK 2026-11-02 (the Python HUD is an empty placeholder; removed from the total) |
| 28 | Scenario engine + debug CLI on the bus | 1.5 | DONE 2026-11-10 |
| 29 | Retire the old Python messaging stack and the radar bridge | 1 | open |
| 30 | Hardening: release build, timing checks, coverage targets, MISRA-subset lint, intern docs | 1.5 | IN PROGRESS (Alee, 2026-11-11) |

**Done: 27 / 29.5 = 92 %.** Open: 2 units (29, 30).

The terminal addresses are fixed in the ICD's terminal table (`fmofp_icd.xml`, `<terminals>`):
RT 1 avionics, 2 comms, 3 engine, 4 ECS, 5 FCS, 6 mission, 7 nav, 8 power, 9 radar, 10 sensor
management, 11 PFD, 12 FMS, 13 MFD, 14 EICAS, 15 radar display, 16 TSD, 17 SMS, 18 HUD
(unused), 19 hydraulics, 20 airframe, 21 flight surfaces, 22 defensive, 23 flight data
monitoring, 27 plant, 31 broadcast. Free: 24-26, 28-30.

### 2.15 Sensor management (RT 10), 0.75

DONE 2026-11-08 (section 7, ICD v1.18). The plan that stood here became the ICD README's
v1.18 paragraph and its section 2 rows. As planned: the detections are the plant's
(`PLANT_SENSOR_SCAN`, and `PLANT_ESM` relayed a second time as `SNS_ESM`), the EICAS counts the
fused tracks from the block it already hears, `SNS_STATUS` is the EICAS's own relay (RT 14
SA 3), and there is no contacts block (nothing draws the contacts; `fmofp_sensor_tool` reads the
table for the oracle). One choice beyond the plan: a sensor switched off by `SNS_CMD` leaves
the fusion too (the Python's fusion had its own always-on managers, a path nothing exercised).

### 2.16 Power management (RT 8), 0.75

DONE 2026-11-08 (section 7, ICD v1.19). The plan that stood here became the ICD README's
v1.19 paragraph and its section 2 rows. As planned: the six random draws are the plant's
(`PLANT_ELECTRICAL` at 1 Hz in the Python's order), the bookkeeping is RT 8, `PWR_STATUS`
carries `monitor()`'s snapshot and is the EICAS's own relay (RT 14 SA 4). Beyond the plan:
`set_generator_output`, dead in the Python (the next draw overwrote it), holds the plant's
generator (`PWR_GEN_CMD` → `PLANT_GEN_CMD`) until released; `PWR_CMD` also carries the
component classes' manual controls nothing called (emergency power, APU, engine start, HVAC,
dissipation unit); the EICAS's two generator rows show the one generator and its essential bus
row the 28 V auxiliary bus; the mission equipment batteries stay off the bus.

### 2.17 Avionics: LRU health, built-in test, FM fitness, software configuration (RT 1), 1

DONE 2026-11-10 (section 7, ICD v1.20, landed after v1.22). The plan that stood here became the ICD
README's v1.20 paragraph and its section 2 rows. As planned: the bus controller writes a bus-health
message for RT 1 once a second (`AVN_BUS_HEALTH`, from its poll statistics and each terminal's
`TERM_STATUS`), and RT 1 derives the LRU table from it, applies the forced faults, runs the three
built-in test families, the fitness rule and the software configuration, and publishes `AVN_STATUS`
(the EICAS's own relay, RT 14 SA 8). Changed from the plan: the report is nine masks of one bit per
terminal, not a word per terminal (the ICD tool has no repeated groups); there is no `AVN_LRU` block
(nothing draws the LRUs: three slot masks in `AVN_STATUS` instead); `AVN_CMD` names an LRU by a
key of up to 24 characters, resolved in C++ as `resolve_lru_id` did, so unit 28's scenario engine
sends `failureScenario.xml`'s `<system>` values as written (`fmofp_bus/avionics.py` `key_fields`);
a key that names no LRU declares an entry (four slots). Almost all of this was dead in the Python
(the monitor never started, the tests never run, the EICAS wrote PASS without reading a result):
the quirks kept and the two departures (no random probe fault; the monitor and the power-on test
do run) are Alee's choices of 2026-11-09 (section 8).

### 2.18 Defensive systems (RT 22), 0.5

DONE 2026-11-07 (section 7, ICD v1.17). The plan that stood here became the ICD README's
v1.17 paragraph and its section 2 rows. Two things changed from the plan: `DEF_STATUS` has one
consumer (the TSD draws only the contacts), so it is the EICAS's own relay `EICAS_DEF_STATUS`
(RT 14 SA 1) and only the contacts block is broadcast (`BCAST_DEF_RWR_CONTACTS`, 31/16-17, up
to 64 contacts); and the Python's fused-track branch turned out to be dead (it called
properties as methods), so the port computes the contacts the Python meant to make and the
oracle records the Python's behaviour. The scenario engine's threat injection is `DEF_CMD`
`INJECT_THREAT`, ready for unit 28.

### 2.19 Flight surfaces (RT 21), 0.5

DONE 2026-11-10 (section 7, ICD v1.21). The plan that stood here assumed the Python service followed
the flight control computer's commanded deflections; it follows the sensed roll, pitch and angle of
attack (the FCC's data dictionary, which is `PLANT_SENSORS` on the bus) and nothing read its positions,
so the port takes `PLANT_SENSORS` by relay (`FSF_SENSORS`, the producer's fifth: the relay limit went to
six), publishes `FSF_POSITIONS` with no consumer (the monitor, the dashboard, the recorder to come) and
leaves `FCS_SURFACE_STATUS` alone; closing the loop is backlog (ICD README section 12). `FSF_CMD` carries
`set_flaps`, `set_speedbrake`, `set_rudder` and `set_trim`.

### 2.20 Small utilities, 1 (ECS RT 4, hydraulics RT 19, airframe RT 20, flight data monitoring RT 23)

DONE 2026-11-10 (section 7, ICD v1.22). The plan that stood here overstated the Python: none of the four
classes had a sensor source (the plant invents the cabin, the two hydraulic systems' pressures and the three
airframe gauges, `fmofp_plant/utilities.py`), the hydraulics had one system and a backup (not A/B/C) and compared
a constant 2800 psi for equality with its thresholds (judged at-or-under here), asmConfig.xml has no limits (the
readings are reported, not judged), the gear's "deploy every tick" was already gone from the frozen tree (the
FMS's gear command drives it now, when it changes), and the recorder logged 123 for every parameter (it records
the FDR's three config parameters from the FMS flight data). The EICAS's SYS A/B and CAB TEMP / CAB ALT rows
fill; SYS C and OXY PSI have no system behind them and stay unknown (ICD README section 2).

### 2.28 Scenario engine + debug CLI on the bus, 1.5

DONE 2026-11-10 (section 7, ICD v1.23). The plan that stood here became the ICD README's v1.23 paragraph, its
section 2 rows and its section 7 command-port paragraph. As planned: both stay Python and are clients of the bus; the
bus controller got a command port (`port_base + 34`, frame types 4 and 5) through which a client queues an aperiodic
receive transaction and is acknowledged with the controller's frame count; the engine reads the frozen XML as
`scenarioEngine._parse` did and fires waypoints and phases as `MSN_CMD`, threats as `DEF_CMD INJECT_THREAT`, failures
as `AVN_CMD` with `key_fields`, and radar contacts and weather cells as injections into the plant
(`PLANT_INJECT_CONTACT` into the traffic, `PLANT_INJECT_WEATHER` into the sky, where the radars find them); both
scenario files run end to end over the bus in `test_scenario_e2e.py`. The CLI is a prompt over the monitor port and
the command port (`terminals`, `status`, `msgs`, `msg`, `send ID field=value`, `scenario`). Changed from the plan:
the engine's clock is the bus frame, not wall time (a `--speed` factor runs a scenario fast for a test); `--script`
stayed and the command port was added beside it rather than replacing it; the demo did not change (it keeps its
scripted events; `py -m fmofp_scenario` runs beside it). Backlog (ICD README section 12): the recorder's dump to the
CLI, the plant's all-zero TERM_STATUS.

### 2.29 Retire the old Python messaging stack and the radar bridge, 1

Delete what the bus replaced: `B20SS/FMOFP/local_messaging/` (about 38,700 lines),
the Python bus `B20SS/FMOFP/MIL_STD_1553B/` (19,300), `radar_to_display_bridge.py` (695),
the display-side mirror `Interfaces/userInterface/messaging/`, the per-subsystem message
handlers and messengers, their tests under `FMOFP/Tests/`, and the wiring in
`core/system_manager.py` / `Main.py` that starts the Python subsystems now running in C++.
Decide with the humans what `py FMOFP/Main.py` becomes (the demo launcher already is the
aircraft). Both CI files change (Alee's Python jobs test the deleted stack). **Do this unit
last among the port units**: Alee's upstream still edits these files every week, so after
this unit upstream merges will conflict and the merge rule (section 4.4) stops the pulling;
tell both humans that the upstream line is cut from then on.

### 2.30 Hardening, 1.5

A release preset (every preset builds Debug `-O0` today, demo binaries included); a timing
test that asserts each partition's step time and the schedule's worst frame against the
budget; gcovr thresholds per partition in CI; a MISRA-subset lint (cppcheck's misra addon,
or clang-tidy on the Linux job); the FMOFP loggers at WARNING in the display processes (the
MFD log grows 2 MB per three minutes); the intern documents: how to build, run and debug one
partition under gdb, the architecture page, the ticket format. Cheap backlog items from the
ICD README section 12 can ride along (a plant whose airspeed answers the thrust, engine
spool-up).

First job (added 2026-11-10 after unit 17 landed): the real-time demo's overruns with 23 terminals (section 1:
2 in 1500 frames on Kevin's machine with the events on, 21-36 on Alee's). Candidates, cheapest first:
`AVN_STATUS` at 1 Hz instead of 5 (its content changes once a second); `PLANT_SENSORS` as one broadcast
instead of five 50 Hz relays (about 1 ms of every minor frame, ICD README section 12); the display terminals'
poll answering (Python processes on a loaded machine); the controller's response timeout and what it does
with a late answer. The timing test of this unit then pins what was gained.

First job done 2026-11-11 (section 7). What it found, in the order tried: `AVN_STATUS` at 1 Hz did not help
(46-55 overruns against 26-42: reverted, the status stays at 5 Hz). The controller's new timing report
(`--report`: per terminal the mean and worst answer and the overrun frames it was slowest in; the overrun
frames that merely started late) then named the MFD's Python terminal: each completed SAR image cost its one
loop 10.7 ms of bit-by-bit CRC, 6 ms of decoding and 2.4 ms of pickling between two answers. The CRC is
`binascii.crc_hqx` now (0.2 ms), which also serves the plant's block publishers. Next the radar computer, 6-28 ms
to answer at worst at `-O0`: the optimised presets (`windows-ucrt64-release`, `linux-gcc-release`, `-O2 -g`) bring
it to 4-6 ms and the demo flies them when built. Not done, in case the reference machine still overruns: the
SAR image's 6 ms decode and 2.4 ms pickle moved out of the display terminal's helper process into the window's
(forward the raw words, decode on read); `PLANT_SENSORS` as one broadcast; the plant's own worst answers (4-21
ms, a Python process). The timing test of this unit should pin: the release build's per-terminal worst answer
in a free-running whole-aircraft run, and the schedule's estimate.

---

## 3. How a unit is ported (the pattern every done unit followed)

1. **Scope the Python in full.** Read the module(s), the config XML beside them, and every
   consumer (grep the displays and the other Systems for the getter). Write down, before
   designing: which parts are *world* (random walks, invented readings, generated detections,
   wall-clock sines) and which are *flight logic* (rules, thresholds, state machines, filters,
   bookkeeping); every quirk and defect you find; what each display actually reads (keys and
   units, not what the docstring says).
2. **World goes to the plant, logic goes to C++.** The plant (`B20SS/fmofp_plant/`) owns
   everything the real aircraft would measure; the partition owns everything the real
   computer would decide. The ported logic is translated step for step from the Python,
   including its quirks, unless the quirk makes the function unusable (then depart, and
   record the departure in `B20SS/icd/README.md` section 2 with the evidence). Improvements
   go to the README's section 12 backlog, not into the port.
3. **Design the bus interface in the ICD first** (`B20SS/icd/fmofp_icd.xml`): the
   terminal's status message and mode command (SA 10 by convention), its inputs (relays of
   plant or other terminals' messages, or broadcast listeners), its commands (aperiodic, with
   `cmd_seq`), blocks for anything over 32 words (`<block>` with a `<header>` and
   `<section>`s using `id=`). Apply the rules of section 4.2. Run
   `py icd/tools/icd_tool.py check`, bump the minor version, regenerate (`gen-py`,
   `render`), update the README: a section 1 paragraph for the version, section 2 rows for
   every departure from the Python, the "Added in vX" table, section 12, the revision row.
4. **Plant side** if any world moved: `fmofp_plant/<thing>.py` with its own seeded
   generator (`seed ^ a constant`, so earlier seeded flights do not change), `plant.py`
   publishing it at its rate and reading any command the partition sends back, CLI flags,
   `fmofp_bus/tests/test_plant_<thing>.py`.
5. **C++ partition**: `B20SS/ofp/partitions/<name>/{include/fmofp/<name>/<name>.hpp,
   src/<name>.cpp, src/main.cpp, tools/<name>_tool.cpp}` modelled on `partitions/comms`
   (the smallest) or `partitions/mission` (with a block and a tool); `partitions/
   CMakeLists.txt`; `tests/<name>_test.cpp` and `tests/CMakeLists.txt`; the counts in
   `tests/icd_messages_test.cpp` (`kIcdMinor`, messages, relays). Rules: `B20SS/ofp/
   CLAUDE.md`. The stdin tool exists so the Python oracle test can drive the C++ logic with
   the frozen Python's own inputs and compare outputs.
6. **Python side**: `fmofp_display/systems_feed.py` (stand-ins returning the dictionaries
   the display reads; omit a field until it is valid rather than inventing one),
   `fmofp_display/app.py` (which terminal receives which messages and blocks, with
   `accept_broadcast` for RT 31), `fmofp_demo/demo.py` (`PARTITIONS`, `NAMES`, a dashboard
   line, an event in time order with `cmd_seq` 201 or above, the banner), tests:
   `test_messages.py` counts and listeners, `test_display_feeds.py`, `test_display_render.py`
   (offscreen Qt), `test_display_e2e.py` (the whole aircraft, every terminal),
   `test_demo.py`, `test_<name>_oracle.py`, `test_<name>_e2e.py` (its own `PORT_BASE`, at
   most 65000, distinct from every other test's), the env var in `fmofp_bus/tests/
   _support.py` and in **both** CI files (`.github/workflows/ci.yml`, `bitbucket-pipelines.yml`),
   and `B20SS/verify.sh` `export_binaries` if a new binary or tool exists.
7. **Docs**: `B20SS/ofp/README.md` (the partition list, the command lines, the tests
   paragraph), the ICD README, this file (sections 1, 2, 7, 6, 8).
8. **Verify**: `bash B20SS/verify.sh` green; a headless demo run
   (`py -m fmofp_demo --headless --seconds 30`, from `B20SS/`) with 0 overruns; the load line
   under budget with margin.
9. **Commit, push, record** (section 0.4). One commit per unit, in the style of the
   existing ones (`git log` on `port/cpp` shows twenty).

---

## 4. Rules

### 4.1 Architecture

- The bus is the only link between programs: 16-bit words on a simulated MIL-STD-1553B over
  UDP on 127.0.0.1 (`port_base` + RT for terminals, +32 the controller, +33 the monitor).
  No shared memory, files or sockets of any other kind between partitions.
- One process per subsystem (a *partition*), one per display, the bus controller its own
  process and the master clock: a 20 ms minor frame, 50 per major frame; terminals step on
  the controller's synchronise mode code (MC17), never on their own clocks.
- The displays stay Python (PyQt6, unchanged FMOFP classes, fed from the bus). The scenario
  engine, the CLI, the plant and the tests stay Python. Everything that decides something
  about the aircraft is C++17 under `B20SS/ofp/`.
- The Python under `B20SS/FMOFP/` is frozen at Alee's `0ab9236` for the logic being ported;
  the C++ is measured against it by oracle tests that import the frozen modules. Upstream
  merges (section 4.4) are allowed only when they do not change that logic.
- The ICD is ours to evolve (Kevin's decision, 2026-10-10: no approval loop; since 2026-11-04
  Alee is the second contributor, so "ours" means the two of them). Whoever is working
  decides, implements, records it in the ICD README section 2, and tells both humans.

### 4.2 Bus and ICD rules (the tool enforces most; know them anyway)

- Rates: 50, 25, 10, 5, 1 Hz or aperiodic. The controller refuses a schedule whose worst
  minor frame exceeds 10000 us; the load model charges a relay as one RT-to-RT transfer per
  consumer. Check the load line (`verify.sh load`) after every ICD change.
- **One consumer, its own relay** (v1.15): a stream with exactly one listener is relayed
  into that listener's own receive subaddress; RT 31 (broadcast) only for two or more
  listeners. A listener's own receive subaddresses must be broadcast numbers it never
  listens to (one receive buffer per SA); `check_broadcasts` refuses the collision. Free
  broadcast SAs after v1.17: 12 (not for the MFD), 20, 21, 30.
- Terminals store a broadcast only on subaddresses they `accept_broadcast`; everything else
  on RT 31 is ignored and counted.
- Blocks: 31 payload words per 32-word segment, descriptor + segments, CRC-16/CCITT-FALSE,
  version 1-255 (never 0). A block of n segments polled at rate r must be republished no more
  often than every 2n frames at 25 Hz and 5n frames at 10 Hz (the collector needs every
  segment once per version). `bus::BlockPublisher` must be `init(storage, capacity)`-ed
  before its first `publish`, or the descriptor reads zeros.
- Validity: every measured value carries a 2-bit SSM (0 = FAILURE_WARNING is the fail-safe
  zero; NO_COMPUTED_DATA for unknown or stale); staleness is counted in frames by the
  receiver. Commands carry an 8-bit `cmd_seq`; 0 means "no command"; the terminal reports
  the last accepted sequence and a rejected bit.
- Enums must define value 0 and fit in 8 bits; scaled fields give `lsb` as a fraction and a
  range; a plain unsigned field may not carry min/max without an lsb; block sections use
  `id=`. Message, relay and block counts are pinned in `icd_messages_test.cpp` and
  `test_messages.py`: update both with the ICD.
- Subaddress conventions: 29 TERM_STATUS/TERM_CMD on every terminal, 31 mode codes, 10 the
  terminal's status + mode command, radars on 1-5, displays' own status at 11-17; otherwise
  the next free number in the terminal's table.

### 4.3 C++ rules

`B20SS/ofp/CLAUDE.md` is binding (no heap after init, no exceptions, `[[nodiscard]]
Status`, `-Werror` with conversion warnings, cppcheck clean, tests for every module). Lessons
cppcheck taught: never name a local or parameter after a member accessor (`config`, `stats`,
`worst`, `mode`, `track`, `count`); prefer `std::find_if` / `count_if` / `fill` to raw search
loops; pointers to data you do not modify are `const`; a decoded record with no enum field
needs `(void)` on its decode status; `*_test.cpp` is suppressed (cppcheck cannot parse
`TEST(`). Shifts of promoted narrow integers trip `-Wsign-conversion` only under UBSan:
`static_cast<unsigned>` first. Large objects (the 4 MB radar volume) are `static` in
`main`, never stack temporaries. `layout_of` messages are composition (a `payload`
member), not inheritance.

### 4.4 Upstream (Alee's TubAleeLo/fmofp): merge when clean, otherwise report

Every session: `git fetch upstream`; `git log --oneline HEAD..upstream/main`. If there is
anything: `git diff --name-only $(git merge-base HEAD upstream/main) upstream/main`, and for
every file in the **mirrored set** (ICD sources: `rtAddressConfig.xml`, `message_schemas.py`,
`metadata_codec.py`, `radar_enums.py`, `messageRateConfig.xml`, `command_registry.xml`;
the modules the C++ was translated from; the modules the oracle tests import, listed by
`grep -h "from FMOFP" B20SS/fmofp_bus/tests/*.py B20SS/fmofp_display/*.py`; the display
classes the display processes embed) read the diff with `git diff -w`. Then
`git merge-tree --write-tree HEAD upstream/main` for conflicts. If conflict-free and the
mirrored files changed only in plumbing (imports, logging, comments, formatting): `git
merge --no-commit --no-ff upstream/main`, `bash B20SS/verify.sh icd py` (the oracle tests
arbitrate; run `cpp` too if anything under `ofp/` or `icd/` moved), commit the merge with a
message naming the upstream commit and what was checked, push. Otherwise `git merge
--abort`, and tell your human which files interfere; the baseline then stays where it is.
Never push to upstream.

### 4.5 The Python's quirks

Keep them as written and document them; they are the intern tickets of the future. Every
departure is a row in the ICD README section 2 with the reason and the evidence (an oracle
test that proves the Python's behaviour, where possible). Examples already recorded: the
storm-cell tracker that deletes every cell it creates, the SAR change detector that masks
its own detections, the AEWC radar equation mixing dBW and dBm, the mission route's ETEs
always at 450 kt, the SMS station table painted with the wrong brush.

### 4.6 Commits and CI

- One unit per commit, after `verify.sh` is green. Message: a one-line title naming the
  unit and the ICD version, then paragraphs saying what moved where, what the port settles
  about the Python, what the displays and the demo gained, and the tests, with numbers. End
  with the attribution line the harness gives you (`Co-Authored-By: Claude Fable 5.1
  <noreply@anthropic.com>` today).
- Both CI files are edited together (`.github/workflows/ci.yml` and
  `bitbucket-pipelines.yml`): the env vars for new binaries, the apt packages.
- After a push, note the CI run (`gh run list --repo kevinanguyen/fmofp-c-port --branch port/cpp
  --limit 3`; the `gh` binary on Windows is at `C:\Program Files\GitHub CLI\gh.exe` and
  needs `--repo`). Record the result in section 7 when it lands (next session is fine).
- Warnings like `LF will be replaced by CRLF` on commit are harmless (`-c
  core.safecrlf=false` silences them).

### 4.7 Reporting to the humans

Plain words, short, no jargon without a gloss (Kevin asked what a "port" and an "ICD" are:
explain such words the first time). Lead with what was done and whether it is verified;
give the commit id; **always give the conversion percentage from section 2 and the
estimated time to 100 % with the pace it rests on**; end with the one decision the human
has to make, if any. Report failures as failures with the output; never say "done" for a
step that was skipped.

### 4.8 Tooling rules for Claude on Windows (learned the hard way)

- Python is `py` (the launcher), never `python` (the Store shim). Install nothing globally
  without saying so.
- The C++ toolchain is MSYS2 UCRT64 at `C:\msys64`; it is not on the Windows PATH on
  Kevin's machine. `verify.sh` handles it; for anything else run
  `MSYSTEM=UCRT64 /c/msys64/usr/bin/bash.exe -lc 'cd <dir> && <command>'` or put
  `C:\msys64\ucrt64\bin` first on PATH (the test executables need its DLLs).
- **Never put a script in a Bash command body**: no heredocs (`<<'EOF'`), no inline Python
  with quotes, backslashes or escape sequences, no commit message inline. Write the file
  with the Write tool, then run `py file.py`, `bash file.sh` or `git commit -F file`. It has
  failed six times (length limits, apostrophes, doubled backslashes collapsed, escape
  sequences turned into newlines, variables lost in a backgrounded `&&` chain).
- PowerShell 5.1 mangles embedded quotes in native arguments: use the Bash tool for git,
  gh and the build.
- Python subprocesses want native paths in env vars on Windows (`K:/...`), not `/k/...`
  (`cygpath -m`). `taskkill /PID` gets path-converted under Git Bash (use PowerShell
  `Stop-Process -Id`); `wmic` is gone (`Get-CimInstance Win32_Process`).
- Scratch files, probes and patch scripts go in the session scratchpad, never in the
  repository.

---

## 5. Machines, tools, commands

### 5.1 Clone and remotes (once per machine)

```bash
git clone https://github.com/kevinanguyen/fmofp-c-port.git
cd fmofp-c-port
git checkout port/cpp
git remote add upstream https://github.com/TubAleeLo/fmofp.git
git remote set-url --push upstream DISABLED
git config user.name "<your name>" && git config user.email "<your email>"
```

Alee has write access to `kevinanguyen/fmofp-c-port` (collaborator invitation sent by Kevin
on 2026-11-04; it must be accepted on GitHub before the first push). The disabled `upstream`
push URL applies to Alee's clone of this fork too: port work reaches `TubAleeLo/fmofp` only
when both humans decide so (unit 29 is where that comes up). Anyone without write access
works on a fork of the fork and opens pull requests into `port/cpp`; the protocol's "push"
then means "push and open the PR".

### 5.2 Windows toolchain

Python 3.10 or newer from python.org with the `py` launcher, then
`py -m pip install -r B20SS/requirements.txt` (PyQt6 6.8.1, numpy, scipy, qasync, click).
MSYS2 (`winget install MSYS2.MSYS2`), then in the **UCRT64** shell (`C:\msys64\ucrt64.exe`):

```bash
pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja mingw-w64-ucrt-x86_64-gtest mingw-w64-ucrt-x86_64-cppcheck mingw-w64-ucrt-x86_64-gcovr
```

Versions that are known to work: g++ 16.2, cmake 4.4, ninja 1.13, gtest 1.18, cppcheck 2.21,
gcovr 8.6. No sanitizers on MinGW: CI's `linux-asan` job covers that. Optional: GitHub CLI
(`winget install GitHub.cli`, then `gh auth login`).

### 5.3 Linux (what CI installs)

```bash
sudo apt-get install -y g++ cmake ninja-build libgtest-dev cppcheck gcovr python3 python3-numpy python3-scipy python3-pyqt6 libgl1 libegl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libglib2.0-0
```

`verify.sh` picks `linux-gcc`; `PRESET=linux-asan bash B20SS/verify.sh cpp` runs the
sanitizer build. The Qt tests render offscreen (`QT_QPA_PLATFORM=offscreen`, set by the
script).

### 5.4 Build, test, verify

```bash
bash B20SS/verify.sh            # icd, cpp (configure + build + ctest + cppcheck), py (298 tests), load
bash B20SS/verify.sh icd py     # any subset, in order
```

The optimised build (unit 30): `cmake --preset windows-ucrt64-release && cmake --build --preset
windows-ucrt64-release` from `B20SS/ofp/` (`linux-gcc-release` on Linux), into `build/<preset>-release/`; the
demo uses it when it exists. `PRESET=windows-ucrt64-release bash B20SS/verify.sh cpp py load` runs the gate
against it. The plain presets stay Debug `-O0`: the gate's, and the ones to debug.

By hand, from `B20SS/ofp/` in a UCRT64 shell or on Linux: `cmake --preset <preset>`,
`cmake --build --preset <preset>`, `ctest --preset <preset>`, `cmake --build build/<preset>
--target cppcheck`, `cmake --preset coverage && cmake --build --preset coverage`. The
Python suite by hand needs the `FMOFP_*` environment variables pointing at the binaries
(`verify.sh` shows which; `fmofp_bus/tests/_support.py` documents them); one test module:
`py -m unittest fmofp_bus.tests.test_mission_e2e` from `B20SS/` with those variables set.
`py icd/tools/icd_tool.py check|render|gen-py|gen-cpp` from `B20SS/`.

### 5.5 Running the aircraft

From `B20SS/`: `py -m fmofp_demo` starts the plant, every C++ partition, the six display
windows and the bus controller, prints one dashboard line per second and drives the scripted
events; Ctrl-C stops everything. Options: `--seconds S`, `--headless`, `--no-displays`,
`--no-events`, `--hold heading=0,speed=450`, `--seed N`, `--port-base N`, `--build DIR`.
Logs in `B20SS/logs/demo/` (ignored by git). `B20SS/ofp/README.md` has the per-process
command lines, `fmofp_bc --schedule --rt ...` prints the schedule and its load, and
`fmofp_bc --report` the per-terminal statistics and, when it stops, where the frames' time went (unit 30: `bc: timing: overruns_late_start` and, per terminal, `mean_response_us`, `worst_response_us`, `overruns_slowest`; the demo's `logs/demo/bc.log` has them).

With the aircraft running, from `B20SS/`: `py -m fmofp_scenario FMOFP/Interfaces/scenarios/trainingScenario.xml
[--speed 10] [--port-base N]` runs a frozen scenario against it through the bus controller's command port, one
line per event; `py -m fmofp_cli [--port-base N] [-c CMD]` is the debug prompt (`help` lists its commands:
`terminals`, `status RT`, `msg ID`, `send ID field=value ...`, `scenario load|start|stop|status`).

### 5.6 Where things are

`B20SS/icd/` the ICD (XML source of truth, `README.md` conventions and decisions, generated
`ICD_TABLES.md`, `tools/icd_tool.py`). `B20SS/ofp/` the C++ (`bus/`, `bc/`, `osal/`,
`partitions/<name>/`, `tests/`, `CLAUDE.md` rules, `README.md`). `B20SS/fmofp_bus/` the
Python bus library and all port tests (`tests/`). `B20SS/fmofp_plant/` the plant.
`B20SS/fmofp_display/` the display terminals and feeds. `B20SS/fmofp_demo/` the launcher.
`B20SS/FMOFP/` the frozen Python application (`PLANNING.md` beside it describes its
architecture; its own tests are Alee's). `B20SS/verify.sh` the gate.

---

## 6. Gotchas and lessons (add yours; keep each to a line or two)

Bus and C++
- A `BlockPublisher` without `init(storage, capacity)` publishes a descriptor of zeros and
  no error (cost 25 minutes once).
- `fmofp_bc` rejects `--port-base` above 65000; every e2e test owns a distinct base
  (grep `PORT_BASE` in `fmofp_bus/tests` before choosing one).
- A bus-controller run with Python terminals needs `--timeout-ms 20` (40 for the busiest
  tests under the full suite): a Python plant answers several polls per frame.
- A 1 Hz TERM_STATUS needs a window of at least 50 frames in a test, a 5 Hz message at
  least 10; count frames from the MC17 syncs on the monitor.
- The gate tests' stub terminals must not use an RT that has messages now (RT 2 became
  comms: the stubs moved to RT 4).
  RT 1 is the avionics terminal since v1.20 and RT 4 the ECS since v1.22: the stubs are at the free
  addresses 24 and 25, in `bus_controller_test.cpp`, `schedule_test.cpp` and `test_bus_integration.py`.
- The controller's bus-health report (`AVN_BUS_HEALTH`) says nothing before the first major frame is done
  (epoch 0): a test of anything RT 1 derives from it needs frames 0-49 for the first poll of every terminal,
  up to 50 more for the report's 1 Hz slot, and 10 for `AVN_STATUS`: assert from frame 110.
- A message whose producer is the controller is a periodic `dir="R"` message with no relay: the schedule
  gives it a receive slot and the controller sends what `set_receive_data` stored (zeros until then).
- The load model: the fourteen-terminal aircraft sits at 6908 us; a 25 Hz block costs
  roughly a quarter of a frame per segment; before adding a 50 Hz message check the line.
- A custom CMake target that runs ctest must `add_dependencies` on the test executables;
- Shell scripts are committed with LF line endings (.gitattributes forces it); if bash on Windows complains about a stray carriage return in verify.sh, run git add --renormalize B20SS/verify.sh and check the file out again.
  run test executables from the UCRT64 shell or with its `bin` on PATH (DLLs).
- The radar display's particle animation in the same process as a bus terminal starved the
  terminal (overruns): display terminals run in a helper process (`TerminalProcess`) and
  `cancel_join_thread()` their queue so a killed window leaves no orphan.
- Track tables age out after 15 frames without a report: tests that step many frames must
  re-feed the traffic each frame.

Python tests and displays
- Oracle tools print `ok` for `*_clear` commands: consume every answer in the order asked.
- The fake terminal of the feed tests stores unquantised values; a 1/16-LSB field compares
  with the quantised value, not the float you stored.
- Demo events must be in time order (a test checks); event sequence numbers start at 201 so
  the radar window's own numbering (from 1) never collides.
- The TSD paints every pixel of its panels: compare pictures, not lit-pixel counts.
- Offscreen Qt renders glyphs as boxes; layout and colours are still testable. Two display
  processes sharing the FMOFP log file name print a harmless `WinError 32`.
- `assertAlmostEqual(a, b, "msg")`: the third positional is `places`; use `msg=`.
- `install_system_sources()` must run before `mfd.py` is imported; the shared test process
  needs `uninstall_system_sources()` in a `finally`.
- The plant's airspeed is a random walk that ignores thrust (test aircraft, not an engine
  model): the autothrottle winds to full power in the demo by design.
- An oracle's fake clock must start far from zero (1000.0): a Python service whose "last
  time" starts at 0.0 (the epoch) compares against it, and a clock near zero invents a
  cooldown the real program never had (cost one failing oracle run in unit 18).
- `dict.get(key, random.uniform(...))` draws every time: the default is evaluated before the
  lookup. A `random` patched for an oracle must answer those draws too (match on arguments).
- Before porting a branch, check how it calls what it reads: `DefensiveService` called
  `FusedTrack.bearing_deg()` on a property, so its fusion branch never ran in the Python.
- An oracle tool answers from the live table when the Python's getter read live state, not
  from the last published block (`refresh_contacts()` in `fmofp_defensive_tool`).
- `to_dict()` can hand out a live list (`corroborated_by`): an oracle snapshot taken from it
  changes with later merges. Deep-copy snapshots.
- A Python service reports a switched input at its next poll (`get_data()` is the last
  update's snapshot): compare after an update, not right after the switch.
- An attribute named like an existing method (`PlantModel.sensors()`) shadows it silently and
  the method's callers crash later: `self.scan_world`, not `self.sensors`.
- A Python service's `get_data()` dictionary is the last loop pass's snapshot: a manual control
  changes the components, not the dictionary, until the next pass (the power oracle compares
  `pms_data` only right after a `monitor()`).
- A plant command sent at frame f is applied at the plant's next model step, and a 1 Hz reading
  is relayed within the second: the power e2e's generator hold at frame 100 shows in
  `PWR_STATUS` between 150 and 200, and its release at 250 misses the step at 250 (three
  readings at zero, not two); window the assertions on the trough, not on a count of steps.
- An `epoch` field that starts at 0 cannot say "no reading": `PLANT_ELECTRICAL`'s cycles 1-255
  and 0 is the plant without the model, which the terminal ignores.
- The ICD tool has no 32-bit unsigned field (a double-word field must be `sint` with an `lsb`) and no
  repeated group or character type in a message: a 32-bit mask is two 16-bit words (`_hi`, `_lo`), a number
  like a data load's id a `sint` with `lsb="1"`, text two characters a word (`fmofp_bus/avionics.py`).
- A stand-in module in `sys.modules` answers `from a.b.c import f` without importing `a` or `a.b`: how the
  avionics oracle replaces the five subsystems `_probe_system` imports (`mock.patch.dict(sys.modules, ...)`).
- When two units land out of order, take the other side's ICD XML and generated files whole
  (`git checkout --ours` in a rebase) and re-apply your own additions with the script that made them: the
  conflict blocks interleave both units' enums and a union of them is not well-formed XML.
- A producer may be relayed to six consumers (`MAX_RELAYS_PER_SOURCE` in `icd_tool.py` = `kMaxRelaysPerMessage`
  in `bc/schedule.hpp`; four until v1.21): `PLANT_SENSORS` has five. Past six, make the stream a broadcast.
- An oracle tool's `status` command must print live accessors when the oracle drives a loop's halves: the status
  message is filled by the frame (`step()`), not by the halves (cost one failed run in unit 19).
- Demo events go into `default_events()` in time order (a test checks): insert after the earlier event, not
  before the later one.
- Sign conventions bite: FlightSurfaceService puts the LEFT aileron at minus the aileron command, so a right
  roll (positive) gives it the positive command.
- The bus gate tests' stub terminals must sit at addresses with no messages: RT 24 and 25 since unit 20 (RT 4
  became the ECS; RT 1 is Alee's avionics). Free: 24-26, 28-30.
- A frozen display class with its own stand-in model (the EICAS's g-load hydraulics) and a terminal feeding the
  same rows fight at their two timers: subclass the display in the window's factory and re-apply the terminal's
  readings right after its poll (`app.make_eicas`), rather than edit the frozen file.
- An oracle tool that drives a class's method directly (not the frame) needs the method to store what the frame
  would have stored first (`EcsControl::monitor` keeps the readings its `data` line prints).
- An `inspect.getsource` quirk assertion must strip comment lines: the frozen airframe loop names
  `control_landing_gear` only in a comment.
- The plant's 1 Hz readings step first at frame 50 and are relayed within the second: a terminal that reads them
  is NORMAL by frame 110, not 60 (window the first e2e checks on 110-150).
- A double-word ICD field (`word="6-7" bits="31-0"`) must be `type="sint"` with an lsb; `FDM_STATUS.last_frame`
  counts 31 bits of frames (1.4 years).
- A `threading.Thread` subclass must not name an attribute `_stop`: `Thread._stop()` is a method and `join()` calls it
  (`BusView`; one failed run in unit 28).
- A partition kept alive across two controller runs sees the frame count restart at 0: its frame-based cooldowns and
  expiries freeze (`frame < last_dispense_` in the defensive terminal reads as cooling). An e2e test that runs the
  controller twice restarts the partitions between runs (`test_scenario_e2e.py`).
- The controller polls a plant message for its relay whether or not the consumer is on the bus (`status plant` in the
  CLI shows every plant message with RT 27 alone). The plant's own TERM_STATUS is zeros: it fills none.
- The ICD's `<enums>` tail is `avionics_command` since unit 17 landed: anchor a patch script on `</enums>`, not on the
  last value of the last enum you wrote.
- The command port answers when the controller polls it, once a frame: a client's `send` returns after up to one frame
  (20 ms real time); an engine step with several due events takes one frame per event.
- `fmofp_bc`'s closing statistics are read by most e2e tests only after it exits, through a pipe Windows makes
  4 KB long: with 23 terminals they are about 2.6 KB. Twenty-three more lines hung the display e2e for forty
  minutes (the controller blocked writing, the test blocked waiting for its exit) and left 30 processes behind:
  anything new the controller prints at exit goes behind `--report`, which only the demo passes (to a file).
- A hung e2e test leaves its children: before rerunning, list them (`Get-CimInstance Win32_Process`, names
  `fmofp_*` and `python` with `spawn_main` or `unittest`) and stop them, or the next run finds its ports taken.
- "plant port in use?" with no process on the port: Windows reserves blocks of a hundred UDP ports at boot
  (`netsh int ipv4 show excludedportrange protocol=udp`), different on each machine and restart. Every test's
  `PORT_BASE` is `free_port_base(N)` since unit 30 (`_support.py`): N when a bus can be bound there, else just
  below it. New tests do the same; `fmofp_demo`'s default 51000 is not protected (`--port-base`).
- Measure the real-time demo on an idle machine, several runs, with `logs/demo/bc.log`'s timing lines: a game
  running gave 262-326 overruns for code that gives 26-42; a run where `overruns_late_start` is most of the
  overruns and every terminal's worst answer is tens of ms is the machine, not the bus.
- Python on the bus: anything the terminal's one loop does between two polls delays its answer. Time it
  (`time.perf_counter` around the suspect, in a scratch script) before changing the ICD to lighten the load.
- An optimised build can warn where `-O0` does not and can change floating-point results: `-Werror` and the
  oracle tests are the check, so run the Python suite against the release build after touching the C++.

Working on this machine (Kevin's)
- `.claude/CLAUDE.md` in Kevin's clone is a private pointer to this file; the root file is
  the shared one. Do not create a second working file.
- MSYS2's `bin` holds its own `python.exe` (3.14, no PyQt6): never put it above the
  python.org install on PATH; `py` is unaffected.

Working on Alee's machine
- `py` defaults to the free-threaded `python3.14t` there, which PyQt6 6.8.1 cannot load: the
  requirements are installed into the regular 3.14, so run the gate as
  `PY_PYTHON=3.14 bash B20SS/verify.sh` (and `py -3.14 ...` by hand).
- The clone is a worktree of a repository whose remotes were renamed: `origin` is the fork,
  `bitbucket` is Alee's private Bitbucket copy, `upstream` is push-disabled. Push only to
  `origin`.
- `verify.sh icd` reports the four `fmofp_bus/icd` files and `ICD_TABLES.md` as changed on a
  CRLF checkout: the generator writes LF and `git diff` is empty. Not a change: `git restore`
  them, do not commit them.
- `sed -i` under Git Bash rewrites a CRLF file with LF endings: git shows only the real change (and warns
  `LF will be replaced by CRLF`), but the Edit tool then wants the file read again.
- A rebase in this OneDrive worktree can end with `could not remove ... rebase-merge`: the rebase is done;
  remove the empty directory under `.git/worktrees/<name>/` by hand.

---

## 7. Unit log (append-only; newest at the bottom)

Format for new entries: `### <date> - unit N <name> - <commit> - by <name's agent>`, then
*What*, *How*, *Warnings / lessons*, *Files*, *Tests and numbers*. Entries for the units
done before this file existed are condensed from the private session notes.

### 2026-10-10 - units 1, 2, 3 bus core, ICD generators, Python bus library - f61c569..8755ed3, 8490842
- *What*: the simulated bus in C++ (`ofp/bus`: words, command and status words, framing,
  `RemoteTerminal` with per-SA buffers, status latches and mode codes 2/3/6/7/8/16/17/18/19;
  `ofp/osal`: absolute-deadline clock and UDP for win32/posix; `ofp/bc`: `Schedule` with
  phase spreading and the load estimate, `BusController` = MC17 sync, scheduled slots,
  aperiodic queue, per-RT stats, latest-data table, monitor copy; `fmofp_bc`, `fmofp_rt_stub`),
  the ICD (`icd/fmofp_icd.xml`, `icd_tool.py check|render|gen-cpp|gen-py`, generated
  enums/messages/blocks headers and modules with round-trip tests), the Python twin
  (`fmofp_bus`: status, word, transport, remote_terminal, rt_process, monitor).
- *How*: the ICD was drafted from `rtAddressConfig.xml` + `message_schemas.py` (89 legacy
  types mapped), Alee answered ten questions (UDP 51000, big-endian, UCRT64, BC own process,
  one process per subsystem and per display, freeze the Python, true heading), then Kevin
  took the ICD over. Gate: 150 frames with two stubs, 0 overruns, worst frame 285 us.
- *Warnings*: Windows UDP needs `SIO_UDP_CONNRESET` off or a dead peer's ICMP breaks
  `recvfrom`; the BC's latest-data table is 80 KB (keep the controller static); Python
  `encode_scaled` uses llround semantics, not `round()`; the old Python codec cannot encode
  radar modes (documented in the ICD README section 10; Alee: leave it).

### 2026-10-10 - unit 4 FCS - d5b8061 (ICD v1.1)
- *What*: `ofp/partitions/fcs`: GCAS (`_evaluate` decision for decision: PULL UP vs <= -4000
  and alt < 2000, SINK RATE, TERRAIN clearance < 500, ALT LOW < 200) and the performance
  monitor's envelope (g 9, AoA 25, roll 60, pitch 45, VS 6000; fuel efficiency), the mode and
  surface commands with fmsControl's clamps, state INITIALIZING/NORMAL/DEGRADED on stale
  sensors (3 frames). The Python FCC itself was a random-walk plant, so it became the plant
  (`fmofp_plant`, RT 27, `PLANT_SENSORS` 50 Hz relayed as `FCS_SENSORS`).
- *How*: oracle test `test_fcs_e2e.py` runs the frozen `GCAS()._evaluate` beside the real
  processes over the real bus (six scenarios).
- *Warnings*: the Python GCAS's terrain clearance import named a function that does not
  exist, so its TERRAIN alert never fired (the port gets clearance from the TFR, unit 8);
  outputs after init are all-zero FAILURE_WARNING, NO_COMPUTED_DATA once stepped without data.

### 2026-10-11 - unit 5 nav - (ICD v1.2 with unit 6)
- *What*: `ofp/partitions/nav`: the 12-satellite constellation, pseudoranges, WLS solver
  (max 8 iterations, tolerance 0.01 m, weights sin^2(el) + 0.01, 4x4 elimination with partial
  pivot), Bowring ECEF to WGS84, the per-axis scalar Kalman fusion, dead reckoning; `PLANT_GPS`
  (1 Hz, epoch + visible mask + 12 pseudoranges as 32-bit words), `NAV_SOLUTION` 10 Hz.
- *How*: `fmofp_nav_tool` (stdin) lets `test_nav_oracle.py` compare WLS/Bowring/fusion/
  visibility with the frozen Python; `test_nav_e2e.py` over the bus.
- *Warnings*: from the Python's INS start point (Tinker AFB) exactly four coplanar satellites
  are visible and the Python's solver is singular unless bootstrapped from the truth; the
  plant home is therefore 0 N 0 E (where the Python's fixes were really made). A Bancroft
  closed form seeds the WLS. The Python re-noised the pseudoranges every WLS iteration (the
  plant draws the noise once per epoch); the INS was noise with no consumer (not carried).
  The plant refreshes the GPS message every walk step so a fix polled late in the second is
  current.

### 2026-10-11 - unit 6 FMS - 5a42ffe (ICD v1.2)
- *What*: `ofp/partitions/fms`: flight-mode profiles (NORMAL/COMBAT/STEALTH/TRAINING/
  EMERGENCY limits), `update_attitude` envelope limiting with its warnings, thrust and gear
  (`set_thrust`: afterburner can never light through it, kept), autopilot targets, maneuvers
  (BARREL_ROLL not implemented, as in the Python), Mach, energy state, energy
  maneuverability; messages FMS_FLIGHT_DATA 10 Hz (replaces the FMS_DATA block), FMS_STATUS,
  FMS_ATTITUDE_STATUS, FMS_NAV_UPDATE_STATUS, FMS_CONTROL_CMD/STATUS, FMS_ENERGY, inputs by
  relay (FCS attitude, sensors, nav solution). `fmofp_bc --script FILE` ("frame rt sa words")
  queues aperiodic commands for tests.
- *How*: `test_fms_e2e.py`: eleven scripted commands; the oracle is the frozen `FMSControl`
  in-process with its attitude dict reset to the measured zeros before each command.
- *Warnings*: the Python's dead-reckoning rates were always zero (a ground-speed key the FMS
  never wrote); the port uses airspeed as ground speed (no wind model yet, backlog). On Linux
  the monitor socket overflowed when a test drained it only after the run: `Monitor.
  read_until()` reads while the BC runs.

### 2026-10-11 - unit 7 weather radar - 13cbcb9, 87ee524 (ICD v1.3)
- *What*: `ofp/partitions/radar` (weather_model, weather_products, weather_radar): the
  360 x el x 200 reflectivity volume, cells and stratiform areas, clutter, VIL and
  precipitation products with `round_to_sigfigs(3)`, storm-cell analysis, wind shear and
  turbulence processors; scans of 60 frames; products as the first block transfer
  (`RDR_WX_PRODUCTS`, 548 words, header + six sections). The weather world moved to the plant
  (`fmofp_plant/weather.py`, `PLANT_WEATHER`). Block transport in both libraries
  (`ofp/bus/block.*`, `fmofp_bus/block.py`).
- *How*: `fmofp_radar_tool` + `test_weather_oracle.py` compare every stage with the frozen
  generators and processors; texture noise is a hash (seed, az, el, r) so the oracle can
  turn it off.
- *Warnings*: the Python's storm-cell tracker deletes every new cell in the call that created
  it (no cell ever reached a display); the precipitation generator does not round azimuths
  before radians but VIL does (both mirrored); scipy's `uniform_filter1d` running sum has a
  specific order (`tmp += line[i+2] - line[i-1]` with reflect padding); numpy's label order
  is raster order of the first pixel; the 4 MB volume must be static. Shifts of promoted
  narrow integers trip `-Wsign-conversion` only under UBSan (cast first).

### 2026-10-25 - unit 8 terrain-following radar - af838a4, 019c8f8 (ICD v1.4)
- *What*: TFR in the same radar process: clearance levels CLEAR/LOW/CAUTION/PULL_UP (600/300/
  150 m) with a latching master, the path optimiser with the set clearance (30-5000 ft),
  terrain warnings; the terrain moved to the plant (`fmofp_plant/terrain.py`: hills =
  1000 + 500 sin(n/1000) cos(e/2500) + 200 sin(n/300 + e/700) plus two ripples; `PLANT_TERRAIN`
  block 100 samples over 10 km ahead, 10 Hz); block relays and receive blocks in the ICD;
  `FCS_TERRAIN` gives GCAS its clearance (the Python never could).
- *Warnings*: the Python assessed every profile at a fixed 1000 m altitude and never called
  `update_speed`; `PLANT_TERRAIN` later went to 25 Hz with a 5 Hz profile when the load
  needed it (rule: n segments need 2n frames at 25 Hz). BC runs with Python terminals need
  `--timeout-ms 20`.

### 2026-10-25 - unit 21 radar display + PFD on the bus - 5abb03a, f7c9b41, 1838cc4 (ICD v1.5)
- *What*: `fmofp_display` (`terminal.py` DisplayTerminal, `radar_feed.py`, `flight_feed.py`,
  `app.py`): the unchanged `WeatherRadarDisplay`, `TFRRadarDisplay` and
  `PrimaryFlightDisplay` fed from the bus; the radar display is the radars' control panel
  (its commands on SA 20-24; the MFD commands nothing); `cmd_seq` 0 = no command; the BC
  retries a silent transaction once.
- *Warnings*: positions are true nm at the radar's range (the Python drew a fixed 40 nm
  frame); the TFR display raises on a None clearance (feed passes 0.0/UNKNOWN); Qt tests on
  CI need the apt packages of section 5.3.

### 2026-10-25 - unit 22 MFD on the bus - 3848ef6 (ICD v1.6)
- *What*: `systems_feed.py` stand-in modules (PEP 562 `__getattr__`) for every getter
  `mfd.py` imports inside its pages; the embedded radar displays through the plain factory;
  the radar product blocks moved to 25 Hz with least-loaded phase assignment (the 50 Hz copies
  had hit 10352 us).
- *Warnings*: `install_system_sources()` before importing `mfd.py`; the MFD's ENGINE page is
  unreachable in the Python; new schedule phases exposed timing assumptions in two tests
  (fixed properly: the plant's GPS refresh, the radar e2e's first scan with weather).

### 2026-10-25 - unit 23 broadcast relays - 181b39e (ICD v1.7)
- *What*: RT 31 broadcasts with `listeners`, `accept_broadcast` in both terminal libraries
  (before it, any terminal stored any broadcast on any SA), `check_broadcasts` collision
  rule, the BC schedules a broadcast relay when any listener is present; the per-display
  copies removed. Load 8136 -> 7056 us with eight terminals.

### 2026-10-25 - unit 9 engine management - fe8cdc9 (ICD v1.8)
- *What*: `ofp/partitions/engine`: `ThrustManager` (PI autothrottle kp .5 ki .05, asymmetry),
  `FuelSystem` (tanks ML/MR/C, burn from measured flow, the Center top-up policy, transfers,
  low/critical/leak), `EngineManagement` (FMS lever drives both engines, ENG_CMD); the ECU's
  engine model (N1/N2/EGT/flow/oil/vibration formulas with its noise order) moved to the
  plant (`fmofp_plant/engine.py`, `PLANT_ENGINE`, reads `PLANT_THRUST_CMD`). First subsystems
  that listen to broadcasts (engine hears FMS flight data, FCS hears engine status).
- *Warnings*: the Python had three unconnected thrust numbers and tanks that never moved;
  `replaces=` in the ICD must name a legacy type that exists; a FuelSystem test that drains a
  main must keep the Center at or below 5000 kg or the policy refills it.

### 2026-11-01 - demo launcher and display helper processes - e9336ec, 54b4656
- *What*: `py -m fmofp_demo` (Kevin's "see it work" command): starts everything, dashboard
  line per second, scripted events, logs in `logs/demo/`; `TerminalProcess` runs each display
  terminal in a helper process (the weather widget's particle animation had starved the bus
  thread: 416 overruns), `cancel_join_thread()` so a killed window leaves no orphan helper.
- *Numbers*: 180 s run for Kevin: 9000 frames, 0 overruns, worst 6.9 ms, 9/9 answering.

### 2026-11-01 - unit 24 EICAS on the bus - fc50fdd (ICD v1.9)
- *What*: RT 14 listens to seven broadcasts; `SystemsFeed` answers the ten getters
  `eicas.py` polls; `RDR_WX_SCAN.max_shear` added; engine readings through
  `set_engine_readings`.
- *Warnings*: `_compute_alerts(None)` raises (the profile power is always given); the alert
  list grades the thrust model's EGT, not the measured one (kept, asserted). Hydraulics C,
  electrical and ECS rows stay UNKNOWN until units 16 and 20.

### 2026-11-01 - unit 10 targeting radar + track fusion - 226f3c3 (ICD v1.10)
- *What*: `target_processing` (signature analysis, stealth Bayes, threat rule),
  `targeting_radar` (12-track table, gate 1000 m, drop after 15 frames, lock), `track_fusion`
  (epochs every 25 frames, greedy clusters within 500 m, confidence 1 - prod(1 - w)); the air
  traffic moved to the plant (`fmofp_plant/traffic.py`, `PLANT_TRAFFIC`). `PLANT_TERRAIN` to
  25 Hz for the load.
- *Warnings*: a 4-segment block polled at 25 Hz needs a source at 5 Hz or slower; libm-fragile
  tie cases between two reference RCS values are not testable.

### 2026-11-01 - unit 25 TSD on the bus - 26a14f6, bb08383 (ICD v1.11)
- *What*: RT 16 with the fused tracks block, FMS data and energy; the MFD targeting page and
  the radar window's targeting controls. The feed maps the radar's class names into the
  display's symbol vocabulary (the Python's never matched: every target was a '?').

### 2026-11-01 - unit 11 AEWC radar - a3a9521, 680f358, 2a59729 (ICD v1.12)
- *What*: AEWC radar in the radar process (radar equation kept as written: dBW/dBm mix,
  SNR 0 beyond about 40 km; sectors from EAST counter-clockwise; ECM assessment; priorities);
  reports join the fusion (weight 0.7). One display-class fix (`aewc_radar_display.py`
  `_draw_target` arity: every conventional target raised). Load model: a relay costs one
  RT-to-RT transfer per consumer (11 terminals 9712 -> 6368 us).

### 2026-11-01 - unit 12 SAR radar - 499272a (ICD v1.13)
- *What*: strip imaging 2 km right of track at 64 x 64 on the bus (2075-word block every
  150 frames), the change detector step for step (log floor, 11 x 11 box filter with scipy's
  order, mean + 3 sigma, erode/dilate, 4-connected labels, regions); the ground scene moved
  to the plant (`fmofp_plant/ground.py`, `PLANT_GROUND`); the MFD SAR page decodes a PGM.
- *Warnings*: the Python's CFAR has no guard cells, so any compact change masks itself (the
  moving ship is never reported) and scipy's running-sum residue reports unchanged ground as
  CHANGE: both reproduced exactly and documented (a future intern ticket). Images every 3 s
  exceed the display's staleness window: the feed keeps the last image.

### 2026-11-02 - unit 26 SMS on the bus - 8e1eb62 (ICD v1.14)
- *What*: RT 17 listens to `BCAST_FMS_STATUS` only; the stations, release modes and signature
  are the display's own (no armament system exists in the Python: a stores computer is
  backlog). Quirk kept: the station table paints with the last icon's brush.
- *Decision*: the HUD (unit 27) is an empty placeholder in the Python; Kevin struck it.

### 2026-11-02 - one consumer, its own relay - ec755a9 (ICD v1.15)
- *What*: the broadcast map was full; single-consumer streams (targeting, AEWC and SAR
  pictures to the MFD; energy to the TSD) became the consumers' own relays, freeing seven SAs.

### 2026-11-02 - units 13 + 14 mission computer + communications - 051e57d (ICD v1.16)
- *What*: `ofp/partitions/mission` (`RouteManager`, `Targeting`, `OrderOfBattle`,
  `MissionComputer`: route progress, ETEs, target insertion, threat deviation, the target
  status machine with quadratic decay, the plan block every 75-150 frames) and
  `ofp/partitions/comms` (`CommsComputer`: radio active above 20 % field, satcom connected
  when the plant's satellite is in view, data link active iff connected, COM_CMD clamps); the
  RF environment moved to the plant (`fmofp_plant/rf.py`, `PLANT_RF`). MFD comms and mission
  pages, TSD route and contacts, demo events (14 terminals).
- *Warnings*: the Python's second route (`MissionPlanningSystem`) was write-only; its
  position guard against (0, 0) and a misspelled ground-speed key made every ETE 450 kt;
  `insert_target` on an empty route deadlocked the service (the port appends). Test slips
  worth remembering: ids keep counting across `clear()`; a LOST target keeps decaying; unit
  ids count across affiliations.
- *CI*: run 41569356013 all ten jobs green.

### 2026-11-04 - upstream merge d82173f; this file and verify.sh - by Kevin's agent
- *What*: merged upstream/main `4c25f52` (six commits of 2026-11-02: lint sweep, logging,
  dead-code removal; 253 files, conflict-free; every mirrored module changed only by removed
  unused imports and plain strings; full suite 186 OK on the merged tree). Created this
  shared working file for the two-person workflow, `B20SS/verify.sh` as the one gate, and
  retired the private `.claude/CLAUDE.md` to a pointer (its notes are archived on Kevin's
  machine).
- *Numbers*: meter unchanged, 21 / 29.5 = 71 %.

### 2026-11-04 - repository renamed, Alee joins, CI of the two file commits - by Kevin's agent
- *What*: Kevin renamed the fork `kevinanguyen/fmofp` to `kevinanguyen/fmofp-c-port` and
  invited Alee (GitHub `TubAleeLo`, the upstream owner) as a collaborator with write access
  (invitation pending acceptance when this was written). The local `origin` URL, this file
  (preamble, sections 1, 4.1, 4.6, 5.1) and Kevin's private pointer file carry the new name;
  GitHub redirects the old one. No code changed.
- *CI*: `8d67afd` run 41931935765 all ten jobs green; `e325d00` run 41932029106 nine green,
  the Windows 3.13 Python leg red on `FMOFP.Tests.test_weather_radar_live` only (Alee's
  flaky live test, section 1), both `cpp` jobs green.
- *Numbers*: meter unchanged, 21 / 29.5 = 71 %.

### 2026-11-07 - unit 18 defensive systems (RT 22) - ICD v1.17 - by Kevin's agent
- *What*: `ofp/partitions/defensive` (`DefensiveSystems`: the radar warning receiver's
  64-contact table from the hostile fused tracks heard by broadcast and the plant's ESM
  intercepts, THREAT_DB by class, 10 s expiry, the automatic two-flare salvo on a hostile
  priority-1 contact with its 3 s cooldown, manual chaff and flares, the ECM mode, the
  scenario threat injection; `fmofp_defensive_tool`). The ESM detections moved to the plant
  (`fmofp_plant/esm.py`, `PLANT_ESM`: a set of 0-5 signals every 25 frames in the Python's
  draw order, then a range per signal). ICD v1.17: `DEF_STATUS` → `EICAS_DEF_STATUS` (one
  consumer), `DEF_MODE_CMD`, `DEF_CMD`, `DEF_ESM`, the `DEF_RWR_CONTACTS` block (9 segments
  at 25 Hz, republished every 25 frames) → `BCAST_DEF_RWR_CONTACTS` 31/16-17 (EICAS, TSD);
  RT 22 a listener of `BCAST_RDR_FUSED_TRACKS`. EICAS countermeasures panel and alerts, TSD
  threat ring, demo `DEF` line and three events (a SAM on the receiver at 18 s with the
  salvos that follow, ECM ACTIVE at 19 s, chaff at 45 s).
- *How*: oracle `test_defensive_oracle.py` runs the frozen `DefensiveService` (database and
  sensors blocked, `time` and `random.uniform` patched, fake tracks answering the calls it
  makes) beside the tool over a 12 s scenario; `test_defensive_e2e.py` (port base 53000)
  runs plant + radar + defensive + the EICAS's and TSD's bus halves under the real
  controller; `test_plant_esm.py` checks the plant's draws against `ESMSensor.detect`; the
  feed, render, display e2e, demo and message-count tests extended; 10 gtests.
- *Warnings / lessons*: the Python's fusion branch was dead (`track.bearing_deg()` on a
  property: TypeError swallowed), so the Python's RWR only ever showed ESM intercepts and
  scenario injections; THREAT_DB's SAM entries match no radar class, so no fused track
  reaches priority 1 and only an injected threat fires the auto-dispenser (kept; ICD README
  section 2). A manual flare request with an empty dispenser restarts the cooldown (kept).
  The Python's table was unbounded (about 50 live intercepts): the block holds 64 and counts
  refusals. The oracle's clock must start far from 0 and its patched `random.uniform` must
  answer the `dict.get` default draw (section 6). A 1 Hz TERM_STATUS needs a 50-frame window
  (again). The demo's worst measured frame is 19-22 ms at start-up (the Python terminals
  starting); the schedule estimate is 7332 us.
- *Files*: `ofp/partitions/defensive/{include/fmofp/defensive/defensive_systems.hpp,
  src/defensive_systems.cpp, src/main.cpp, tools/defensive_tool.cpp}`,
  `ofp/tests/defensive_systems_test.cpp`, `fmofp_plant/esm.py`, `fmofp_display/
  systems_feed.py` (`rwr_contact_dict`, `defensive_data`, `rwr_contacts`, the `DEF` status
  text), `fmofp_display/app.py`, `fmofp_demo/demo.py`, `icd/fmofp_icd.xml` + README +
  generated files, `verify.sh`, both CI files, `_support.py`, the tests.
- *Tests and numbers*: Python 196 OK (was 186), ctest 2/2 (249 gtests), cppcheck clean; load
  82 messages for 15 terminals, worst minor frame 7332 us (was 6908 for 14); headless demo
  30 s: 1500 frames, 0 overruns (a first run: 2), 15/15 answering; meter 21.5 / 29.5 = 73 %.

### 2026-11-08 - unit 15 sensor management (RT 10) - ICD v1.18 - by Kevin's agent
- *What*: `ofp/partitions/sensor` (`SensorManagement`: the six sensors' on/off states and
  SensorService's health rule; SensorDataFusion's contact table, 192 entries in insertion
  order, every radar, LIDAR, infrared and ESM detection merged into the first contact within
  5 degrees of bearing or appended, corroboration and FUSED, the missing kinematics filled,
  8 s expiry, the id counter; `fmofp_sensor_tool`). The sensors' scans moved to the plant
  (`fmofp_plant/sensors.py`, the `PLANT_SENSOR_SCAN` block: the two radars, the LIDAR and the
  two infrared sensors, a set every 10 frames in the managers' draw order) and `PLANT_ESM`
  steps every 10 frames (the fusion's 5 Hz; the defensive terminal takes the latest set per
  update). ICD v1.18: `SNS_STATUS` → `EICAS_SNS_STATUS` (RT 14 SA 3), `SNS_MODE_CMD`, `SNS_CMD`,
  `SNS_ESM` (a second relay of `PLANT_ESM`), `SNS_SCAN` (a block relay). The EICAS SENSORS rows
  (health; the fused tracks counted from the block it already hears), demo `SNS` line and two
  events (LIDAR off at 48 s, on at 58 s). Unit 18's CI result recorded in section 1.
- *How*: `test_sensor_oracle.py` runs the frozen `SensorService` and `SensorDataFusion` on fake
  managers beside the tool (`time` patched, `SensorContact` subclassed so new contacts take
  the fake clock, snapshots deep-copied); `test_sensor_e2e.py` (port base 53500) runs plant +
  sensor + the EICAS's bus half with sensors switched off and on under the real controller;
  `test_plant_sensors.py` checks the plant's scans against the managers' sensors draw for
  draw; feed, render, display e2e, demo and message-count tests extended; 9 gtests.
- *Warnings / lessons*: the Python's fusion owned its own always-on sensor managers beside the
  service's (deactivating a sensor, which nothing called, would not have stopped the fusion):
  one set of states in the port (ICD README section 2). LIDAR points carry `azimuth` and the
  fusion reads `angle`: no bearing, never merge, about a hundred live LIDAR contacts (kept).
  `to_dict()` hands out the live `corroborated_by` list (deep-copy oracle snapshots); a service
  reports a switched sensor at its next poll (compare after an update); an attribute named
  like a method (`PlantModel.sensors`) shadows it (section 6). The display e2e's poll timeout
  went from 20 to 40 ms after unit 18's CI red (one unanswered poll on the slow runner).
- *Files*: `ofp/partitions/sensor/{include/fmofp/sensor/sensor_management.hpp,
  src/sensor_management.cpp, src/main.cpp, tools/sensor_tool.cpp}`,
  `ofp/tests/sensor_management_test.cpp`, `fmofp_plant/sensors.py`, `fmofp_plant/plant.py`,
  `fmofp_display/systems_feed.py` (`sensor_data`, the `SNS` status text), `fmofp_display/app.py`,
  `fmofp_demo/demo.py`, `icd/fmofp_icd.xml` + README + generated files, `verify.sh`, both CI
  files, `_support.py`, the tests.
- *Tests and numbers*: Python 205 OK (was 196), ctest 2/2 (258 gtests), cppcheck clean;
  load 86 messages for 16 terminals, worst minor frame 7884 us (was 7332 for 15);
  headless demo 30 s: 1500 frames, 0 overruns, 16/16 answering; meter
  22.25 / 29.5 = 75 %.

### 2026-11-08 - protocol check; CI of unit 15 recorded - by Kevin's agent
- *What*: section 0.1 run on Kevin's machine: tree clean, `origin/port/cpp` = local `c4057ed`,
  no `wip/` branches, no pull requests, upstream/main still `4c25f52` (nothing to merge). Alee
  is in the collaborator list with write access (no pending invitation) and has not pushed.
  No code changed.
- *CI*: `c4057ed` run 42439181347 all ten jobs green (the claim `98bb051`, run 42436742888,
  green too), consistent with unit 18's `linux-gcc` red being the display e2e's timing on the
  slow runner; the 40 ms poll timeout stays.
- *Numbers*: meter unchanged, 22.25 / 29.5 = 75 %.

### 2026-11-08 - unit 16 power management (RT 8) - ICD v1.19 - by Kevin's agent
- *What*: `ofp/partitions/power` (`PowerManagement`: PowerManagementSystem's 1 Hz bookkeeping
  over the plant's reading: the balance as current on the 24 V main battery (charged by a
  surplus, discharged by a deficit), the APU battery charged at a quarter, the emergency
  battery's 8 A critical load while the emergency mode is on, 6 W per kW of consumption into
  the coolant loop with its fan controller, the cabin's HVAC; `Battery` and its four kinds,
  `ActiveDissipationUnit`, `CoolingSystem`, `HvacSystem`; `fmofp_power_tool`). The six random
  draws moved to the plant (`fmofp_plant/electrical.py`, `PLANT_ELECTRICAL` at 1 Hz, epoch
  1-255, the generator held where `PLANT_GEN_CMD` says). ICD v1.19: `PWR_STATUS` →
  `EICAS_PWR_STATUS` (RT 14 SA 4), `PWR_MODE_CMD`, `PWR_CMD` (fourteen commands),
  `PWR_GEN_CMD` → `PLANT_GEN_CMD`, `PLANT_ELECTRICAL` → `PWR_ELECTRICAL`; enums
  `thermal_status`, `power_command`. The EICAS's ELECTRICAL rows fill in (`system_readings()`
  through `set_system_readings`), a `PWR` status text and demo line, three demo events (the
  generator off at 52 s, back at 61 s, the emergency power on at 80 s).
- *How*: `test_power_oracle.py` runs the frozen `PowerManagementSystem` (its `random` answering
  the staged reading by range, its `DatabaseManager` a mock) beside the tool second for second
  to nine places (the same arithmetic in the same order), plus the manual controls and a quirk
  test; `test_power_e2e.py` (port base 54500) runs plant + power + the EICAS's bus half under
  the real controller with the generator held at zero and released, the emergency power on, a
  setpoint moved and an empty command rejected; `test_plant_electrical.py` checks the plant's
  draws against the Python's; feed, render, display e2e, demo and message tests extended;
  14 gtests.
- *Warnings / lessons*: `set_generator_output` was dead (the next second's draw overwrote it):
  departed, it holds the plant's generator (README section 2). The bus voltages are draws
  independent of the generator, so a generator at zero shows GEN FAIL but never MAIN BUS LO
  (backlog). The coolant settles near 40 C under the Python's 6 W/kW: WARNING and CRITICAL need
  the dissipation unit off. The oracle's `pms_data` cross-check must follow a `monitor()`
  (section 6); the e2e's hold lasts three readings, not two (section 6). The XML's `<revision>`
  elements stop at 1.8: versions since are in the README's table only.
- *Files*: `ofp/partitions/power/{include/fmofp/power/power_management.hpp,
  src/power_management.cpp, src/main.cpp, tools/power_tool.cpp}`,
  `ofp/tests/power_management_test.cpp`, `fmofp_plant/electrical.py`, `fmofp_plant/plant.py`,
  `fmofp_display/systems_feed.py` (`power_data`, `system_readings`, the `PWR` text),
  `fmofp_display/app.py`, `fmofp_demo/demo.py`, `icd/fmofp_icd.xml` + README + generated
  files, `ofp/README.md`, `verify.sh`, both CI files, `_support.py`, the tests.
- *Tests and numbers*: Python 217 OK (was 205), ctest 2/2 (272 gtests), cppcheck clean;
  load 90 messages for 17 terminals, worst minor frame 8128 us (was 7884 for 16); headless
  demo 30 s: 1500 frames, 0 overruns, 17/17 answering; meter 23 / 29.5 = 78 %.

### 2026-11-09 - first session on Alee's machine; CI of unit 16 recorded - by Alee's agent
- *What*: section 0.1 step 6 on Alee's Windows 10 machine. Setup of section 5: the
  requirements into python.org 3.14 (PyQt6 6.8.1, numpy 2.5, scipy 1.18, qasync, click),
  MSYS2 by winget with g++ 16.2, cmake 4.4.5, ninja 1.13.2, cppcheck 2.21, gtest and gcovr in
  UCRT64; remotes as section 5.1 (`upstream` push-disabled). No code changed.
- *How*: `PY_PYTHON=3.14 bash B20SS/verify.sh` from a clean `port/cpp` at `a63556e`.
- *Warnings / lessons*: the default `py` there is free-threaded 3.14t (PyQt6 cannot load);
  the first MSYS2 login shell exits after the core update (run pacman again); the regenerated
  ICD files differ only in line endings on a CRLF checkout (section 6). `gh` is not installed:
  CI read from the public Actions API.
- *CI*: `a63556e` (unit 16) run 42507980864 all ten jobs green; the claim `2dc221c` run
  42503903851 green; the working-file commit `76df0c3` run 42501800996 nine green, `linux-gcc`
  red (a documents-only commit, so the known display e2e timing on the slow runner; the next
  two runs green).
- *Tests and numbers*: verify OK (icd cpp py load): ctest 2/2, cppcheck clean, Python 217 OK
  in 51 s, load 90 messages for 17 terminals, worst minor frame 8128 us, the same numbers as
  Kevin's machine. Meter unchanged, 23 / 29.5 = 78 %.

### 2026-11-09 - protocol check; Alee's first runs recorded; the demo test runs ten seconds - by Kevin's agent
- *What*: section 0.1 on Kevin's machine: tree clean, the pull brought Alee's two commits (`3e2dc89` his
  machine's setup entry, `d5aa844` the claim of unit 17), this file re-read, upstream/main still `4c25f52`.
  Unit 17 is Alee's (claimed 2026-11-09): Kevin's next unit is 19 or 20. One test changed: the demo test runs
  ten seconds instead of eight.
- *Why*: Alee's claim run 42728027159 (a documents-only commit) was red on `linux-gcc` in `test_demo`: the
  dashboard's `COM 243.000` (the radio event at 7 s) appears from the t=8 s line, which the slow runner (17
  overruns in 400 frames, worst frame 28 ms) did not print before the 8 s run ended; ten seconds leave the
  line two chances. The Python 3.10 leg of the same run was red on Alee's flaky `test_weather_radar_live`.
- *CI*: Alee's `3e2dc89` run 42727864521 all ten jobs green; `d5aa844` run 42728027159 eight green, the two
  reds above. Unit 16's `a63556e` run 42507980864 all ten green (recorded by Alee).
- *Numbers*: meter unchanged, 23 / 29.5 = 78 %.

### 2026-11-10 - protocol check; CI of 65eacdc recorded; Alee's wip branch for unit 17 - by Kevin's agent
- *What*: section 0.1 on Kevin's machine: tree clean, `port/cpp` unchanged at `65eacdc` (local = origin),
  upstream/main still `4c25f52`, no pull requests. New on origin: `wip/unit17-avionics` (`95f6fca`, Alee,
  2026-11-09, on top of `d5aa844`, 34 files, +4192 lines) with no change to this file, so the branch's state
  is in its commit message; recorded here and in section 1. No code changed.
- *Alee's branch, in his words*: done and passing on his machine: ICD v1.20 (`AVN_STATUS` →
  `EICAS_AVN_STATUS` 14/6, `AVN_MODE_CMD`, `AVN_CMD`, `AVN_BUS_HEALTH` written by the bus controller once a
  second; five enums; 126 messages, 43 relays); the bus controller's `BusHealthReporter` and
  `set_receive_data`; `ofp/partitions/avionics` (LRU monitor with forced faults, built-in tests, FM fitness,
  software configuration) with `fmofp_avionics_tool`; C++ build clean, ctest 2/2, cppcheck clean; load 93
  messages for 18 terminals, worst frame 7944 us; `test_avionics_oracle.py` (15 tests) and
  `test_avionics_e2e.py` (2 tests; port base 55500, free) pass; feed, app, demo, `verify.sh`, both CI files
  and `_support.py` wired. Not done: `test_display_feeds/render/e2e` not extended for the avionics terminal
  (the display e2e still lists 17 terminals), the full Python suite and the headless demo not run since the
  wiring, the ICD README, `ofp/README.md` and this file's sections 1, 2, 6, 7, 8 not written.
- *Checked here*: `git merge-tree --write-tree port/cpp origin/wip/unit17-avionics` reports no conflict (his
  `test_demo.py` hunks and the ten-second change of `65eacdc` do not overlap). CI does not run on `wip/**`
  (the workflow triggers on `main` and `port/**`), so the branch has no run; its first run comes when it
  lands on `port/cpp`.
- *CI*: `65eacdc` run 42729856922 nine green, the Windows 3.13 Python leg red on Alee's flaky
  `test_weather_radar_live` only; both `cpp` jobs green, so the ten-second demo test held on the runner.
- *Numbers*: meter unchanged, 23 / 29.5 = 78 %.

### 2026-11-10 - unit 19 flight surfaces (RT 21) - ICD v1.21 - by Kevin's agent
- *What*: `ofp/partitions/surfaces` (`FlightSurfaces`: FlightSurfaceService's ten surfaces, each a `Surface`
  moved toward its command by at most its slew rate x 0.02 s a frame within its limits; the loop's sync from
  the sensed roll, pitch and angle of attack (aileron = clamp(-0.5 roll, +-25) with the left aileron at minus
  it, elevator = clamp(-0.8 pitch, +-30), the slats out above 8 degrees of AoA) and the manual controls
  set_flaps (the 0/5/15/30 detents, ties to the lower), set_speedbrake (0.6 deg per %, 0-60), set_rudder (+-30),
  set_trim (+-10, bookkeeping); `fmofp_surfaces_tool`). Nothing moved to the plant: the service invented
  nothing, it read the flight control computer's data dictionary, which is PLANT_SENSORS on the bus. ICD v1.21
  (v1.20 is Alee's unit 17 on its branch): `FSF_STATUS` (5 Hz), `FSF_MODE_CMD`, `FSF_SENSORS` (PLANT_SENSORS'
  fifth relay), `FSF_CMD`, `FSF_POSITIONS` (10 Hz, no consumer: the monitor and the dashboard read it); enums
  `surface_command`, `trim_axis`; the per-producer relay limit 4 -> 6 (`icd_tool.py MAX_RELAYS_PER_SOURCE`,
  `bc/schedule.hpp kMaxRelaysPerMessage`). Demo `FSF` line and four events (flaps 15 at 42 s, speedbrake 50 %
  at 47 s, flaps up at 68 s, speedbrake in at 69 s). No display reads the surfaces: no feed change.
- *How*: `test_surfaces_oracle.py` runs the frozen `FlightSurfaceService` (its flight control computer a stand-in
  answering the staged roll, pitch and AoA, its database a mock) beside the tool pass for pass to 12 places (the
  same arithmetic in the same order), with the controls and their clamps, plus a quirk test; `test_surfaces_e2e.py`
  (port base 52500) runs the plant with roll 20 / pitch 5 / AoA 10 held and the partition under the real
  controller with flaps, speedbrake, rudder and trim commanded; display e2e, demo and message tests extended;
  12 gtests.
- *Warnings / lessons*: the section 2.19 plan assumed the service followed the FCS's commanded deflections
  (`FCS_SURFACE_STATUS`); it follows the sensed attitude, and the FCC's surface commands move nothing, in the
  Python as on the bus (ICD README section 2; closing the loop is backlog). The sign convention cost one failed
  oracle run: a right roll (positive) gives the LEFT aileron the positive command. An oracle tool's `status` line
  must read live state when the oracle drives the loop's halves (`fill_outputs` runs in the frame, not in the
  halves). Demo events must be inserted in time order (a test checks; one failed run). PLANT_SENSORS had four
  relays, the limit: FSF_SENSORS is the fifth, so the limit is six now; a broadcast would save about 1 ms a frame
  (README section 12). Alee's `wip/unit17-avionics` touches the same wiring anchors (the counts, the RT lists,
  `verify.sh`, both CI files, the demo tables, the ICD tails): his rebase will conflict there; keep both
  additions and regenerate (131 messages, 44 relays, 19 terminals).
- *Files*: `ofp/partitions/surfaces/{include/fmofp/surfaces/flight_surfaces.hpp, src/flight_surfaces.cpp,
  src/main.cpp, tools/surfaces_tool.cpp}`, `ofp/tests/flight_surfaces_test.cpp`,
  `ofp/bc/include/fmofp/bc/schedule.hpp`, `icd/tools/icd_tool.py`, `icd/fmofp_icd.xml` + README + generated
  files, `fmofp_demo/demo.py`, `ofp/README.md`, `verify.sh`, both CI files, `_support.py`, the tests.
- *Tests and numbers*: Python 221 OK (was 217), ctest 2/2 (284 gtests, was 272), cppcheck clean; load 93
  messages for 18 terminals, worst minor frame 8348 us (was 8128 for 17); headless demo 30 s: 1500 frames,
  0 overruns, 18/18 answering; meter 23.5 / 29.5 = 80 %.

### 2026-11-10 - unit 20 small utilities (RT 4, 19, 20, 23) - ICD v1.22 - by Kevin's agent
- *What*: four partitions: `ofp/partitions/ecs` (`EcsControl`: ECSControl's 2 Hz monitor_ecs over a cabin
  reading: the three threshold checks that only logged, as flags; the oxygen generator's +0.1 % a pass to 23; the
  climate's copy of the temperature; the sub-components' manual controls), `ofp/partitions/hydraulics`
  (`HydraulicController`: monitor_pressure over hydrConfig.xml's thresholds, at-or-under where the Python
  compared a constant 2800 for equality; the backup switch on CRITICAL, for good, and by hand),
  `ofp/partitions/airframe` (`AirframeManager`: asmConfig.xml's three sensors reported unjudged, there being no
  limits in the config; the gear state from the FMS's gear command when it changes and from AFR_CMD),
  `ofp/partitions/fdm` (`FlightDataRecorder`: the FDR's three parameters (frame, altitude, airspeed) from
  BCAST_FMS_FLIGHT_DATA into a ring of 512 every 25 frames; the two cards and eject_storage); one shared stdin
  tool `fmofp_utilities_tool`. The readings moved to the plant (`fmofp_plant/utilities.py`: `PLANT_CABIN` 2 Hz,
  `PLANT_HYDRAULICS` and `PLANT_AIRFRAME` 1 Hz; slow walks, gauges following g and altitude, all holdable). ICD
  v1.22: 21 messages, 6 relays, 7 enums; `HYD_STATUS` -> `EICAS_HYD_STATUS` (14/6), `ECS_STATUS` ->
  `EICAS_ECS_STATUS` (14/7); RT 23 a listener of 31/25; `FMS_CONTROL_STATUS`'s second relay (`AFR_FMS_CONTROL`).
  The EICAS's SYS A/B rows (the primary and backup pressures; C stays unknown) and CAB TEMP / CAB ALT rows (the
  pressure altitude of the cabin pressure; OXY PSI stays unknown) fill through `set_system_readings`; the
  display's own g-load model of A/B is overridden right after each poll (`app.make_eicas` subclasses the
  display). Demo: a systems line (HYD / ECS / gear / FDR) and five events (backup hydraulics at 56 s, oxygen rate
  at 62 s, gear down at 72 s and up at 78 s through the FMS, the CVR card ejected at 83 s). The gate tests' stub
  terminals moved to RT 24 and 25.
- *How*: `test_utilities_oracle.py` runs the four frozen classes beside the tool (the ECS pass for pass with its
  logger captured for the three checks; the hydraulics config and backup; the gear state machine and sensor
  table; the recorder's tables and ejection) and four quirk tests; `test_utilities_e2e.py` (port base 56500)
  runs the plant (hydraulic pressure and cabin held), the four partitions, the FCS and the FMS under the real
  controller with the gear commanded through the FMS and by hand, the backup switched in, a card ejected twice,
  and reads the EICAS's bus half; `test_plant_utilities.py`; feed, render, display e2e, demo and message tests
  extended; 20 gtests.
- *Warnings / lessons*: the section 2.20 plan overstated the Python: no A/B/C hydraulics (one system and a
  backup), no limits in asmConfig.xml, the gear "deploy every tick" already gone from the frozen tree (a comment
  remains), the FDM's "other parameters" a comment. The EICAS's own g-load hydraulics model would have fought the
  terminal's readings at two timers: the window's factory subclasses the display and re-applies the readings
  after each poll (section 6). cppcheck's shadow rule hit twice (`command` and `backup_psi` as parameters). A
  double-word ICD field must be signed. The 1 Hz readings reach a terminal by frame 110 at the earliest
  (section 6). The real-time demo with 22 terminals: 0 overruns here; CI's runner is the open question
  (section 1).
- *Files*: `ofp/partitions/{ecs,hydraulics,airframe,fdm}/{include,src}`, `ofp/partitions/utilities_tool/`,
  `ofp/tests/{ecs_control,hydraulic_controller,airframe_manager,flight_data_recorder}_test.cpp`,
  `ofp/tests/{bus_controller,schedule}_test.cpp` (stub addresses), `fmofp_plant/utilities.py`,
  `fmofp_plant/plant.py`, `fmofp_display/systems_feed.py`, `fmofp_display/app.py`, `fmofp_demo/demo.py`,
  `icd/fmofp_icd.xml` + README + generated files, `ofp/README.md`, `verify.sh`, both CI files, `_support.py`,
  the tests.
- *CI*: unit 19's `337820b` run 42885140093 all ten jobs green; the claim `6b5e5d6` run 42887030618 green.
- *Tests and numbers*: Python 239 OK (was 221), ctest 2/2 (304 gtests, was 284), cppcheck clean; load 104
  messages for 22 terminals, worst minor frame 8492 us (was 8348 for 18); headless demo 30 s: 1500 frames,
  0 overruns, 22/22 answering; meter 24.5 / 29.5 = 83 %.

### 2026-11-10 - unit 17 avionics (RT 1) - ICD v1.20 - by Alee's agent
- *What*: `ofp/partitions/avionics` (`Avionics` around four ported classes: `LruMonitor`, LRUStatusMonitor's
  table of the catalogue's eleven LRUs, `_derive_health`, `resolve_lru_id`, the forced faults with their
  scenario-declared entries (four slots), `overall_health`, `get_faults`; `BuiltInTest`, the power-on self
  test, `PeriodicBIT.run_due` by its intervals and `InitiatedBIT.run_all` over bitsConfig.xml's tables;
  `FmFitness.check_thresholds` and `handle_redundancy`; `SoftwareConfig`, swcmConfig.xml's versions and data
  loads; `fmofp_avionics_tool`). The bus controller writes `AVN_BUS_HEALTH` for RT 1 once a second
  (`ofp/bc`: `BusHealthReporter` in `bus_health.{hpp,cpp}`, `BusController::set_receive_data`, three lines in
  `main.cpp`): nine masks of one bit per terminal from its poll statistics and each terminal's last
  `TERM_STATUS`. ICD v1.20 (inside v1.22's file): `AVN_STATUS` (18 words, 5 Hz) -> `EICAS_AVN_STATUS` (RT 14
  SA 8), `AVN_MODE_CMD`, `AVN_BUS_HEALTH` (19 words, 1 Hz, a receive message with no relay), `AVN_CMD` (16
  words, the key as characters); enums `lru_health`, `bit_status`, `fitness_status`, `fitness_component`,
  `avionics_command`. The EICAS's BITS rows are the power-on results (`SystemsFeed.bit_results()`, set by
  `EicasWindow.tick()`), an `AVN` status text and demo line, three demo events (a failure forced on the flight
  control computer at 24 s, cleared at 42 s, an initiated test at 57 s). `fmofp_bus/avionics.py`
  (`key_fields`, `key_text`).
- *How*: scoped 2026-11-09 (the five modules, four config files, every caller), designed with Alee, built on
  `wip/unit17-avionics` when the session ran out, rebased over units 19 and 20 on 2026-11-10 and finished.
  `test_avionics_oracle.py` (15 tests) runs the frozen `LRUstatus.py`, `builtInTesting.py`, `bitControl.py`,
  `fmStatus.py` and `swConfigure.py` beside the tool: every subsystem they reached into is a stand-in that
  answers what the bus view says of its terminal (accessors replaced on the unstarted monitor, the probe's five
  modules replaced in `sys.modules`, `time` and `random` patched in `builtInTesting`, the fitness logger
  captured). `test_avionics_e2e.py` (port base 55500) runs plant + FCS + avionics + the EICAS's bus half under
  the real controller with seven scripted commands, and a second run without the plant in which the FCS's
  DEGRADED reaches FCC-1, GCAS-1 and PERF-1. Feed, render, display e2e, demo and message tests extended; 14
  gtests for the partition and one for the controller's report.
- *What the Python was*: nearly all dead. `LRUStatusMonitor` was never started (only the scenario engine's
  `force_fault` touched it); nothing ran the built-in tests outside the file's `__main__`; the EICAS wrote
  "<id>: PASS" for each self test without reading a result; `check_thresholds` compares with `==` on fixed
  metrics and only logs; `PeriodicBIT` stores the earlier tests' results under the later test; the data load
  parser keeps the first component of each load; `update_bit_result` has no caller. All kept and in the oracle
  except two departures (ICD README section 2): the probe's random 1 % fault is gone, and the monitor and the
  power-on test do run.
- *Warnings / lessons*: the first bus-health report must wait for the first major frame, or the power-on test
  judges a bus nobody has answered on yet (found while planning the e2e, before any test showed it). The plant
  leaves `TERM_STATUS.healthy` at 0. RT 1 can no longer be a blank stub (three tests moved to RT 24). The
  rebase: Kevin's `EICAS_HYD_STATUS` had taken RT 14 SA 6, so `EICAS_AVN_STATUS` moved to SA 8; the ICD XML's
  conflict blocks interleaved both units' enums, so his file was taken whole and the additions re-applied by
  script (section 6). cppcheck: three locals named after accessors (`lru`, `view`, `bit`), two raw search
  loops, one struct without initializers. An inline heredoc in a Bash command hung on stdin once (section
  4.8 stands).
- *The demo on this machine*: `py -m fmofp_demo --headless --seconds 30`, 23/23 answering on every line, `AVN
  NOMINAL 0/11 faults` and `AVN FAULT 1/11 faults (1 forced)` after the 24 s event; **not** 0 overruns: 21,
  31, 32 and 36 in four runs of 1500 frames (worst frame 39-62 ms), spread about one a second. Measured against
  it: the same demo without the avionics partition and its events (Kevin's 22 terminals, his events) overran
  9, 24 and 18 times on this machine (worst 28-36 ms); with `--no-events` both are 0 (worst 14 and 16 ms). So
  this machine does not hold the real-time demo once the radars are on, with or without unit 17, and unit 17's
  share (one more process, three scheduled messages, five more transactions a second into the EICAS's Python
  terminal) adds to it. The demo test does not assert overruns. Not resolved here: Kevin's machine, where 22
  terminals ran with 0, is the reference; if 23 overrun there too, `AVN_STATUS` at 1 Hz instead of 5 is the
  first thing to try (its content changes once a second).
- *Files*: `ofp/partitions/avionics/{include/fmofp/avionics/avionics.hpp, src/avionics.cpp, src/main.cpp,
  tools/avionics_tool.cpp}`, `ofp/bc/{include/fmofp/bc/bus_health.hpp, include/fmofp/bc/bus_controller.hpp,
  src/bus_health.cpp, src/bus_controller.cpp, src/main.cpp, CMakeLists.txt}`, `ofp/partitions/CMakeLists.txt`,
  `ofp/tests/{avionics_test.cpp, bus_controller_test.cpp, schedule_test.cpp, icd_messages_test.cpp,
  CMakeLists.txt}`, `fmofp_bus/avionics.py`, `fmofp_display/systems_feed.py` (`avionics_data`, `bit_results`,
  the `AVN` text), `fmofp_display/app.py`, `fmofp_demo/demo.py`, `icd/fmofp_icd.xml` + README + generated
  files, `ofp/README.md`, `verify.sh`, both CI files, `_support.py`, the tests (`test_avionics_oracle.py`,
  `test_avionics_e2e.py`, `test_bus_integration.py`, `test_display_feeds.py`, `test_display_render.py`,
  `test_display_e2e.py`, `test_demo.py`, `test_messages.py`).
- *CI*: `888eafe` (unit 20) run 42900090742 green, read from the public Actions API.
- *Tests and numbers*: `verify.sh` OK (icd cpp py load): Python 261 OK (was 239), ctest 2/2 (319 gtests),
  cppcheck clean; load 107 messages for 23 terminals, worst minor frame 8612 us (was 8492 for 22); meter
  25.5 / 29.5 = 86 %.

### 2026-11-10 - check after unit 17 landed; the 23-terminal demo measured on Kevin's machine - by Kevin's agent
- *What*: section 0.1 on Kevin's machine after Alee's push: the pull brought `6497634` (unit 17, rebased onto
  `888eafe`, one commit, as the protocol asks; the `wip/unit17-avionics` branch is gone on GitHub, the stale
  remote-tracking ref here pruned with `git fetch --prune`), this file re-read, upstream/main still `4c25f52`.
  No code changed.
- *Checked here*: `bash B20SS/verify.sh` on `6497634`: OK (icd cpp py load), Python 261 OK in 50 s, ctest 2/2
  (319 gtests), cppcheck clean, load 107 messages for 23 terminals, worst minor frame 8612 us, the same numbers
  as Alee's. The headless demo, 30 s, 23 terminals: with the scripted events 1500 frames, 2 overruns, worst
  frame 24.5 ms, 23/23 answering; with `--no-events` 0 overruns, worst 13.6 ms. The reference machine held 22
  terminals at 0 overruns the same day: the margin is gone, as Alee suspected, though far from his 21-36.
  Unit 28 adds no terminal (the scenario engine and the CLI are clients of the controller); the timing work
  goes to unit 30 (section 2.30).
- *CI*: `6497634` run 42925246480 all ten jobs green; `888eafe` (unit 20) run 42900090742 green (recorded by
  Alee).
- *Numbers*: meter unchanged, 25.5 / 29.5 = 86 %.

### 2026-11-10 - unit 28 scenario engine + debug CLI on the bus - ICD v1.23 - by Kevin's agent
- *What*: the bus controller's **command port** (`ofp/bc/command_port.{hpp,cpp}`: a UDP port at `port_base + 34`
  drained once a frame, at most 16 datagrams, the aperiodic queue's depth; a frame of type 4 carries the command
  word the client wants sent, a receive to RT 1-30 SA 1-30 with the data count, and the data words; the controller
  queues the transaction (`queue_receive`) and answers a type-5 frame with the command word, a status code and its
  frame count; `--no-command-port` leaves it closed; frame types 4 and 5 in both transports). `fmofp_bus/
  command_port.py` (`CommandClient`: `send(message, rt=None)` numbers `cmd_seq` from 201 per destination,
  `send_words`, `send_command_word`; `Acknowledgement`) and `fmofp_bus/bus_view.py` (`BusView`: a monitor thread with
  the frame count from the syncs, the latest decoded message of every kind, each terminal's TERM_STATUS and last
  answer; the terminal names). **The scenario engine** `fmofp_scenario/` (`scenario.py`: the XML parsed as
  `scenarioEngine._parse` did and sorted by time; `engine.py`: `Translator` turns each event into the ICD command its
  injector amounted to, `ScenarioEngine` fires by bus frame at a speed factor, `run(view)` until complete or the bus
  stalls; `__main__.py`: `py -m fmofp_scenario FILE --speed S`, one line per event with the acknowledgement). **The
  debug CLI** `fmofp_cli/` (`cli.py`: `DebugCli` with `frame`, `terminals`, `status`, `msgs`, `msg`, `send ID
  field=value` (fields typed from the dataclass defaults, enums by name or number, `rt=N` for TERM_CMD), `scenario
  load|events|start|stop|status`; `__main__.py`: the prompt and `-c`). ICD v1.23: the plant's `PLANT_INJECT_CONTACT`
  (27/21: an aircraft into the traffic, `TrafficWorld.inject`: the same id moves it, a thirteenth replaces the
  farthest generated) and `PLANT_INJECT_WEATHER` (27/22: a storm cell into the sky at the bearing and range of the
  offset, placed in its lifecycle at the reflectivity asked, `WeatherWorld.inject` with a generator of its own so a
  seeded sky is not moved); enum `weather_category`; the plant's `take_injections()` and `injections` counter.
- *How*: `test_scenario_oracle.py` holds the parser beside the frozen `ScenarioEngine` (both files, and a quirk XML
  through both `_parse`s), checks every translation of both scenarios and the injectors' defaults, and the engine's
  frame clock with a fake client and views; `test_scenario_e2e.py` (port base 58500) runs plant + mission + defensive
  + avionics + the EICAS's and TSD's bus halves under the real controller, the training scenario at speed 100 (its
  510 s in 255 frames) and the failure scenario at speed 50, fresh partitions per scenario, and reads MSN_STATUS (3
  waypoints, COMPLETE), DEF_STATUS (the contact, the salvo), AVN_STATUS (4 forced faults, 14 LRUs) and the plant's
  injections; `test_command_port.py` (57500: a Python RT 24 under the real controller: queued, acknowledged,
  refused, malformed, `--no-command-port`; the client alone); `test_cli.py` (the parsing and output on a fake bus;
  59500: the CLI against the controller and the plant with a three-event scenario); `test_plant_injections.py`; one
  gtest (`TheCommandPortQueuesWhatAClientSendsAndAnswers`). ICD README: the v1.23 paragraph, five section 2 rows,
  the section 7 command-port paragraph, the v1.23 table, section 12, the revision row; `ofp/README.md`: the port and
  the two commands.
- *What the Python was*: the engine fired into live objects on a wall-clock thread polling every 100 ms: a radar's
  `current_targets` table (past the radar's detection), the display bridge (past the weather radar), the RWR's
  table, the mission service, the LRU monitor's `force_fault`. The parser's quirks are kept (`"1e3"` and `"false"`
  stay text, so `bool("false")` is stealth). The CLI's `test` suites are the port's tests; `test_1553b` is the bus.
- *Warnings / lessons*: a `Thread` subclass attribute named `_stop` breaks `join()` (section 6; one failed run). A
  partition kept alive while the controller restarts its frame count at 0 freezes its frame-based cooldown (the
  defensive terminal's `frame < last_dispense_`): the e2e restarts the partitions per scenario (section 6; one
  failed run). The controller polls a plant message for its relay even without the consumer present (the CLI shows
  every plant message with RT 27 alone). The plant's TERM_STATUS is zeros (it fills none; README section 12). The
  ICD's `<enums>` tail is Alee's `avionics_command` now (anchor patch scripts on `</enums>`; one failed patch). The
  scenario's units were never defined (its table had no reader): x/y are taken as km east/north, vx/vy/vz as m/s
  (README section 2). An injected cell drifts with the wind from the frame it lands in (a test tolerance). The
  demo did not change: run `py -m fmofp_scenario` beside `py -m fmofp_demo`.
- *Files*: `ofp/bc/{include/fmofp/bc/command_port.hpp, src/command_port.cpp, src/main.cpp, CMakeLists.txt}`,
  `ofp/bus/{include/fmofp/bus/transport.hpp, src/transport.cpp}`, `ofp/tests/{bus_controller,icd_messages}_test.cpp`,
  `fmofp_bus/{command_port.py, bus_view.py, transport.py, rt_process.py}`, `fmofp_scenario/{__init__,scenario,engine,
  __main__}.py`, `fmofp_cli/{__init__,cli,__main__}.py`, `fmofp_plant/{plant.py, traffic.py, weather.py}`,
  `icd/fmofp_icd.xml` + README + generated files, `ofp/README.md`, the tests (`test_command_port.py`,
  `test_plant_injections.py`, `test_scenario_oracle.py`, `test_scenario_e2e.py`, `test_cli.py`, `test_messages.py`).
- *Tests and numbers*: Python 291 OK (was 261), ctest 2/2 (320 gtests, was 319), cppcheck clean; load
  unchanged (107 messages for 23 terminals, worst minor frame 8612 us: the injections are aperiodic); headless demo
  30 s with the command port open: 1500 frames, 3 overruns (worst frame 26.3 ms) on the idle machine and 13 in a run started right after the gate (worst 24.7 ms), 23/23 answering in both, the command port idle (received=0); meter 27 / 29.5 = 92 %.

### 2026-11-10 - unit 28 pushed; CI of 821a857 and eb2cb92 recorded - by Kevin's agent
- *What*: unit 28 landed as `c78d4af` (the entry above) and was pushed; its CI run 42941262908 landed all ten jobs
  green (recorded at the end of the same session). `821a857` (the check after unit 17 landed) run 42931018335 all
  ten jobs green; `eb2cb92` (the claim of unit 28, a documents-only commit) run 42931963850 nine green, the Linux
  Python 3.14 leg red on Alee's flaky `test_weather_radar_live` only ("a mode set against policy is applied first"),
  both `cpp` jobs green. No code changed.
- *Numbers*: meter 27 / 29.5 = 92 %.

### 2026-11-11 - unit 30 hardening, part 1: the real-time demo's overruns - by Alee's agent
- *What*: the unit's first job (section 2.30). (1) `fmofp_bc` measures where its frames' time goes
  (`TerminalStats`: `worst_response_ns`, `total_response_ns`, `overruns_slowest`; `BcStats`:
  `overruns_late_start`, `worst_wake_late_ns`), printed with `--report` when it stops. (2) The block CRC in
  `fmofp_bus/block.py` is `binascii.crc_hqx` (the bit-by-bit loop stays in `test_block.py` as the reference).
  (3) Optimised presets `windows-ucrt64-release` and `linux-gcc-release` (RelWithDebInfo, `-O2 -g`); the demo's
  `default_build_dir()` prefers `build/<preset>-release/` once its controller exists; CI builds and unit-tests
  `linux-gcc-release` (both CI files). (4) `_support.free_port_base(N)` for every test's `PORT_BASE` (23 test
  modules; `test_support.py`).
- *How it went*: the first candidate, `AVN_STATUS` at 1 Hz, was tried alone and measured: 46, 54, 55 overruns
  against 39, 26, 42 the same hour: reverted. The timing report then showed the MFD terminal (RT 13) as the slowest
  answer in 13 of 30 overrun frames, worst answer 19 ms, with every C++ partition at 0.1 ms on average; timing the
  terminal's work on a SAR image in a scratch script gave CRC 10.7 ms, decode 6.0 ms, pickle 2.4 ms. After the CRC
  fix the MFD was blamed for none, and the radar computer (RT 9) for most of what was left (worst answer 6-28 ms
  at `-O0`); the optimised build brings that to 4-6 ms.
- *Numbers, Alee's machine, 30 s headless with events, 1500 frames, 23/23 answering*: before, 39, 26, 42 (30 with
  the report on); CRC fix, debug build: 18, 16, 7, then 7, 1, 7, 0, 6, 4, 9; CRC fix, optimised build: 1, 5, 91, 6,
  1, 0, 0. The 91 had `overruns_late_start=69`, `worst_wake_late_us=49440` and worst answers of 39-49 ms from the
  FCS, the radar and the plant alike: the machine stalled (it runs a browser and OneDrive beside the bus, 24-49 %
  CPU when "idle"). With a game running nothing can be measured: 262-326 overruns before any change, and 165-216
  on the finished code when the game was started again before the last four runs (50-69 late starts each), so the
  finished code's own numbers are the seven runs above, taken before the timing lines went behind `--report` (a
  change to what is printed at exit, not to the frame).
- *Warnings / lessons*: the timing lines first printed unconditionally and hung `test_display_e2e`: the test
  reads the controller's output after it exits, the 23 extra lines overflowed Windows' 4 KB pipe, the controller
  blocked in `printf` and the test waited for it for forty minutes, leaving 30 processes that had to be stopped by
  hand (section 6; they print with `--report` only now). The same day Windows had reserved UDP 55967-56066, on
  `test_nav_e2e`'s 56000: "plant port in use?" with nothing on the port, on both builds; hence `free_port_base`
  (the test runs at 55900 here today). The optimised build compiled under `-Werror` without a change, and the
  whole Python suite passes against it: no oracle moved.
- *Not done* (section 2.30): the SAR image's decode and pickle still run in the display terminal's helper process
  (8 ms every 3 s); the plant's worst answers are 4-21 ms; `PLANT_SENSORS` is still five relays. Kevin's machine has
  not flown the optimised build.
- *Files*: `ofp/bc/{include/fmofp/bc/bus_controller.hpp, src/bus_controller.cpp, src/main.cpp}`,
  `ofp/CMakePresets.json`, `ofp/tests/bus_controller_test.cpp`, `ofp/README.md`, `fmofp_bus/block.py`,
  `fmofp_demo/demo.py`, `fmofp_bus/tests/{_support.py, test_support.py, test_block.py, test_demo.py}` and the 23
  test modules' `PORT_BASE` lines, both CI files, this file.
- *CI*: to be recorded (the first run of `linux-gcc-release`, on the runner's GCC, which is older than 16.2: if it
  warns where this one does not, fix the code, not the flags).
- *Tests and numbers*: `verify.sh` OK (icd cpp py load) on the debug build and `cpp py load` on the optimised one:
  Python 298 OK (was 291: `test_support.py` 5, one in `test_block.py`, one in `test_demo.py`), ctest 2/2
  on both (320 gtests), cppcheck clean, load unchanged (107 messages for 23 terminals, 8612 us). Meter unchanged,
  27 / 29.5 = 92 % (unit 30 is in progress).

### 2026-11-11 - check after unit 30 part 1 landed; the optimised build flown on Kevin's machine - by Kevin's agent
- *What*: section 0.1 on Kevin's machine: tree clean, the pull brought Alee's `f4ee9e3` (the claim of unit 30) and
  `fb32655` (part 1: 37 files), this file re-read in full, upstream/main still `4c25f52`, no `wip/` branch, no pull
  request. Unit 30 is Alee's (claimed 2026-11-11, landing in parts) and unit 29 is last by design (section 2.29):
  nothing to claim on this side today. No code changed.
- *Checked here*: `bash B20SS/verify.sh` on `fb32655` (the debug build): OK (icd cpp py load): ctest 2/2 (320 gtests), cppcheck clean, Python 298 OK in 63 s, load 107 messages for 23 terminals, worst minor frame 8612 us, the same numbers as Alee's. The optimised build, which
  this machine had not flown: `cmake --preset windows-ucrt64-release && cmake --build --preset
  windows-ucrt64-release` from `B20SS/ofp/`, then `PRESET=windows-ucrt64-release bash B20SS/verify.sh cpp py load`:
  OK (cpp py load): the preset configured and built under -Werror without a change, ctest 2/2 (320 gtests), cppcheck clean, the whole Python suite 298 OK in 62 s against the optimised binaries, load unchanged. The headless demo, 30 s, 23 terminals, the scripted events on, now flying the optimised build
  (the launcher found `build/windows-ucrt64-release/`): three runs, 1500 frames each, 0 overruns in all three, worst frame 11.5, 9.5 and 9.7 ms (24-26 ms on the debug build the day before), 23/23 answering, 19 scripted commands sent. The controller's timing lines
  (`logs/demo/bc.log`): overruns_late_start=0, worst_wake_late_us 1139-1698; every terminal overruns_slowest=0; the C++ partitions answer in 54-84 us on average with worst answers of 0.3-1.4 ms (the radar computer 62 us, worst 1.4 ms), the plant in 108 us (worst 1.4 ms), the display terminals in 108-450 us (the MFD 108 us, worst 1.3 ms; the TSD and the SMS the slowest at 345-450 us): the machine that gave 2-3 overruns a day earlier gives none. Before part 1 this machine gave 2-3 overruns in 1500 frames (13 in a run
  right after the gate).
- *CI*: `fb32655` run 43106860923 all eleven jobs green, the first `linux-gcc-release` job among them (1m48s: the
  runner's older GCC warned nowhere, so nothing to fix); `f4ee9e3` (the claim, a documents-only commit) run
  43045647662 red on `linux-gcc` only, in its "Install toolchain" step after 40 min 56 s (an apt hang on the runner,
  before any step of ours ran), its Lint job green.
- *Numbers*: meter unchanged, 27 / 29.5 = 92 % (unit 30 in progress).

---

## 8. Decisions (append-only: date, who, what, why)

- 2026-10-03, Kevin: port the flight software to C++ (restricted C++17), per Alee's two
  documents; displays, scenario engine, CLI, storage, installer and tests stay Python; the
  bus is the only link. The Python-era SSTR training tickets are legacy; new tickets will be
  written against the C++.
- 2026-10-10, Alee (via Kevin): freeze the Python at `0ab9236` until the conversion is done;
  bus controller as its own process; one process per subsystem and per display; UDP on
  127.0.0.1 from port 51000; UCRT64 toolchain on the intern machines; true heading; leave the
  old Python codec's bugs.
- 2026-10-10, Kevin: no more approvals through Alee; the ICD and every design choice are ours.
  Commit and push each milestone to `origin port/cpp` without asking ("yes and yes, do your
  thing").
- 2026-10-11, Kevin: interns must debug C++, so flight logic goes to C++ and displays stay
  Python ("skip the PFD, do the FMS/nav in C++").
- 2026-10-25, Kevin: keep pulling upstream/main into `port/cpp` while it merges cleanly and
  does not interfere with the mirrored logic; otherwise do not pull and say so.
- 2026-10-25, Kevin: every summary states the conversion percentage and the time to 100 %.
- 2026-11-02, Kevin: skip the HUD (unit 27 struck; total weight 29.5); do mission and comms.
- 2026-11-04, Kevin: two people alternate on the fork, each with Claude; the shared working
  file is this `CLAUDE.md` at the repository root; every session pulls first and reads it,
  every turn that changes anything updates it and pushes; `B20SS/verify.sh` is the gate.
- 2026-11-04, Kevin: the second contributor is Alee (GitHub `TubAleeLo`), added as a
  collaborator with write access; the fork is renamed `fmofp-c-port`. Section 0.5 does not
  change: port work is never pushed to `TubAleeLo/fmofp` from this workflow and the frozen
  Python stays frozen; "ours" in section 4.1 now means the two contributors.
- 2026-11-07, Kevin ("ok go") and his agent: unit 18 as designed in section 2.18 with two
  changes: `DEF_STATUS` is the EICAS's own relay (one consumer) and only the contacts block
  is broadcast (31/16-17); the dead fused-track branch of the Python RWR is departed from
  (the contacts are computed), the rest of the Python's quirks kept (THREAT_DB as written, the
  empty-dispenser cooldown, the unbounded table capped at 64 with a refusal count). The
  scenario engine's threat injection rides in `DEF_CMD` (`INJECT_THREAT`) for unit 28. The
  plant draws the ESM ranges the service drew. Recorded in the ICD README section 2.
- 2026-11-08, Kevin ("ok go unit 15") and his agent: unit 15 as designed in section 2.15 with
  these choices: the fused track count stays the EICAS's (counted from the block it hears;
  RT 10 is no listener of it); one set of sensor states (a sensor switched off by `SNS_CMD`
  leaves the fusion too, where the Python's fusion had its own always-on managers); no
  contacts block (no display draws the contacts; the oracle tool reads the table); the table
  capped at 192 with a refusal count; `PLANT_ESM` steps every 10 frames for both consumers.
  Recorded in the ICD README section 2.
- 2026-11-08, Kevin ("ok go unit 16") and his agent: unit 16 as designed in section 2.16 with
  these choices: the dead `set_generator_output` becomes a hold on the plant's generator
  (`PWR_GEN_CMD` → `PLANT_GEN_CMD`, released by GENERATOR_AUTO); `PWR_STATUS` is the EICAS's own
  relay (RT 14 SA 4) at 5 Hz, `PLANT_ELECTRICAL` at the Python's 1 Hz; the EICAS's two generator
  rows show the one generator (online while its output is above zero) and its essential bus
  row the 28 V auxiliary bus; the component classes' manual controls nothing in the Python
  called ride in `PWR_CMD`; one heat source; the mission equipment batteries stay off the bus.
  Recorded in the ICD README section 2.
- 2026-11-10, Kevin's agent (a coordination rule under section 4.1; either human may overrule):
  while a unit is open on a `wip/` branch with its ICD version already chosen, the next unit that
  lands on `port/cpp` takes the version after it, not the same number, so neither side renumbers
  when the second lands. Unit 17 holds v1.20 on `wip/unit17-avionics`; Kevin's next unit is v1.21
  even if it lands first (the README's section 1 paragraph and revision row for v1.20 are then
  inserted in order when unit 17 lands). The message, relay and block counts are still whoever
  pushes second's to fix.
- 2026-11-10, Kevin ("ok go unit 19") and his agent: unit 19 departs from the section 2.19 sketch where the
  Python did: the service follows the sensed roll, pitch and angle of attack (PLANT_SENSORS by relay,
  `FSF_SENSORS`), not the FCS's commanded deflections, and no measured position goes back to the FCS (no
  consumer in the Python or the displays); closing that loop is backlog (ICD README section 12). A producer may
  now be relayed to six consumers (four until v1.21). The trim stays bookkeeping, the 50 Hz SQLite persist is
  dropped. Recorded in the ICD README section 2.
- 2026-11-10, Kevin ("ok go unit 20") and his agent: unit 20 as designed in section 2.20, corrected where the
  Python differed from the plan: the three readings are the plant's (the Python had none); the ECS's checks stay
  flags that regulate nothing and its config stays unread; the hydraulic thresholds are judged at-or-under (the
  Python's equality with a constant made the monitor unusable), one system and its backup are SYS A and B and
  SYS C stays unknown; the airframe judges nothing and its gear follows the FMS's command when it changes (and
  AFR_CMD by hand); the recorder records the FDR's three config parameters from the FMS flight data into a ring
  of 512, the voice recorder stays idle, a card is out once ejected (the Python kept no card state) and
  ejecting stops nothing; CAB ALT is the cabin pressure's altitude and OXY PSI stays unknown. The EICAS's own
  g-load hydraulics model is overridden by the terminal's readings in the display process, not by editing the
  frozen display. Recorded in the ICD README section 2.
- 2026-11-09, Alee ("Yes, build it") and Alee's agent: unit 17 as designed in section 2.17 with four choices put to
  Alee: the built-in test probe's random 1 % failure is left out (a probe with no terminal behind it always
  passes); the fitness rule is ported as written (`==`, not `>=`, on the placeholder metrics 75 and 80, so it
  never fires) and documented as a defect; a forced fault on a system that is no LRU declares an entry, in four
  slots, with the name on the bus as characters; the periodic test's cumulative result list and the data load
  parser's first-component-only reading are reproduced and proven by oracle tests. Decided by the agent while
  building, and told to Alee: the bus-health report is nine masks rather than a word per terminal; the
  controller's first report waits for the first major frame; there is no `AVN_LRU` block; the EICAS's BITS rows
  are one per self test with its worst component's status, set by the window from `EICAS_AVN_STATUS`. After the
  rebase over v1.21 and v1.22 (2026-11-10): `EICAS_AVN_STATUS` is RT 14 SA 8 (6 and 7 are the hydraulics' and
  the ECS's), and the ICD's version line stays 1.22. Recorded in the ICD README section 2.
- 2026-11-10, Kevin ("ok go unit 28") and his agent: unit 28 as designed in section 2.28 with these choices: the
  controller's command port is a UDP port at `port_base + 34` with two new frame types (4 command, 5
  acknowledgement) and `--script` stays beside it; the engine's clock is the bus frame with a speed factor, not
  wall time; the radar contact becomes an aircraft in the plant's traffic that the radars detect themselves (its
  classification and identity carried, not applied: the radars have no IFF), the weather cell a storm cell in the
  plant's sky placed in its lifecycle at the reflectivity asked, with a generator of its own so a seeded sky is
  not moved; the threat, waypoint, phase and failure go to the terminals' existing commands; the parser's quirks
  (`bool("false")` is stealth) are kept; an unknown phase is skipped with a note; the demo is unchanged (the
  engine runs beside it). Recorded in the ICD README sections 2 and 7.
- 2026-11-11, Alee ("Yes, claim unit 30", "can you complete what is needed for this piece") and Alee's agent: unit
  30 lands on `port/cpp` in parts, each green, the unit staying `IN PROGRESS` until the last (its items are
  independent, and a `wip/` branch would hide the timing fixes from Kevin's machine, which is the reference for
  them). Part 1's choices: `AVN_STATUS` stays at 5 Hz (1 Hz measured no better); the controller's timing lines
  print with `--report` only; the optimised build is a preset beside the debug one, not a replacement (the gate
  and gdb keep `-O0`), and the demo prefers it when built; the tests' port bases step below their usual place when
  Windows has reserved it; no ICD change, so the next ICD version is still v1.24.
