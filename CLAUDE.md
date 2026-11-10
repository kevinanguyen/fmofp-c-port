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
  `git log -1`. Last milestone: `a63556e` unit 16 power management, ICD v1.19 (2026-11-08;
  CI run 42507980864 all ten jobs green). Before it: `c4057ed` (unit
  15 sensor management, ICD v1.18; CI run 42439181347 all ten jobs green), `d718e09` (unit 18
  defensive systems, ICD v1.17; CI run 42435137866: eight green, `linux-gcc` red on one
  unanswered poll in the display e2e on the slow runner, the same code green on the next run,
  the Linux 3.13 Python leg red on the flaky `test_weather_radar_live`), `782078f` (the rename
  and Alee), `8d67afd` (this file and `B20SS/verify.sh`), `d82173f` (merge of upstream/main
  `4c25f52`), `051e57d` (mission computer + comms, ICD v1.16).
- **ICD** v1.19 (`B20SS/icd/fmofp_icd.xml`): 26 terminals, 121 message definitions
  (167 after per-terminal expansion), 42 message relays (15 broadcast), 24 block streams
  (12 layouts, 12 relayed copies), 9 mode codes, 89/89 legacy types mapped.
- **C++ partitions (processes)**: FCS (RT 5), nav (RT 7), FMS (RT 12), radar computer
  (RT 9: weather, terrain-following, targeting + track fusion, AEWC, synthetic aperture),
  engine management (RT 3), mission computer (RT 6), communications (RT 2), defensive
  systems (RT 22), sensor management (RT 10), power management (RT 8); the bus controller
  `fmofp_bc`; tools `fmofp_nav_tool`, `fmofp_radar_tool`, `fmofp_engine_tool`,
  `fmofp_mission_tool`, `fmofp_defensive_tool`, `fmofp_sensor_tool`, `fmofp_power_tool`
  (stdin oracles for the Python tests).
- **Python test equipment on the bus**: the plant `py -m fmofp_plant` (RT 27: the aircraft's
  random-walk flight state, GPS pseudoranges, weather, terrain, two engines, air traffic, the
  ground scene, the RF environment, the ESM intercepts, the sensor scans, the electrical
  readings); six display terminals `py -m fmofp_display radar|pfd|mfd|eicas|tsd|sms`
  (RT 15, 11, 13, 14, 16, 17), each an unchanged FMOFP display class fed from the bus through
  `fmofp_display/*_feed.py`; the one-command demo `py -m fmofp_demo`; the bus library
  `fmofp_bus` with generated `fmofp_bus/icd/`.
- **Load**: 17 terminals, 90 scheduled messages, worst minor frame 8128 us of the 10000 us
  budget. Thirty seconds of headless demo: 1500 frames, 0 overruns, 17/17 terminals
  answering.
- **Tests**: Python 217 OK (`fmofp_bus/tests`, about 42 s on Windows); C++ ctest 2/2
  (hand-written gtests + generated ICD round-trip tests), cppcheck clean; CI (`.github/
  workflows/ci.yml` job `cpp`, linux-gcc + linux-asan, and Alee's eight Python legs).
- **Meter**: 23 of 29.5 units = **78 %** (section 2). Pace measured over the log: about
  5 units per full working day, so about a day and a half more to 100 % (6.5 units open); the
  intern-ticket authoring phase comes after and is not in the number.
- **Upstream**: merged through `4c25f52` (2026-11-02). Port baseline for the ported logic
  stays `0ab9236` (Alee's freeze, 2026-10-10); later upstream commits have been plumbing and
  lint only.
- **Open work / claims**: unit 17 avionics is `IN PROGRESS (Alee, 2026-11-09)`, on branch
  `wip/unit17-avionics` (`95f6fca`, Alee, 2026-11-09, on top of `d5aa844`; its commit message is
  its record, condensed in section 7 under 2026-11-10; it merges onto `port/cpp` without conflict
  as of 2026-11-10). Green there: ICD v1.20, the bus controller's bus-health message, the C++
  partition and tool, the oracle and e2e tests. Not done: the display tests, the full Python
  suite and the headless demo since the wiring, the ICD and ofp READMEs, this file. Next step for
  whoever continues it: rebase on `port/cpp`, finish those, `verify.sh` green, one commit on
  `port/cpp`, delete the branch. Last session: Kevin's, 2026-11-10 (this record). Kevin's next
  unit: 19 flight surfaces or 20 utilities (not 17), then 28, 29 last, 30; a unit landing on
  `port/cpp` while unit 17 is open takes ICD v1.21 (v1.20 is unit 17's; section 8).
- **Known red in CI that is not ours**: Alee's `test_weather_radar_live` is flaky on the
  Windows and 3.12 Python legs (again on the Windows 3.13 leg of run 41932029106, the Linux 3.13
  leg of 42435137866 and the Windows 3.13 leg of 42729856922); the two `cpp` jobs are the ones
  that judge the port.
- **Known flaky in our own `cpp` job**: the display e2e runs the bus under `--strict` with
  seven Python terminals; the slow Linux runner answered one poll late in run 42435137866
  (worst frame 48 ms, exit 1, the next run of the same code green). Its poll timeout is 40 ms
  since unit 15; if it reds again, rerun the job before suspecting the code. The demo test
  (`test_demo.DemoRunTest`) was red once the same way (run 42728027159: 17 overruns in 400 frames
  on the runner, the 7 s radio event not yet on the last dashboard line of an 8 s run); it runs
  ten seconds since 2026-11-09. Every terminal added makes the runner's real-time demo harder:
  unit 30 should give CI a lighter whole-aircraft check or a longer window.

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
| 17 | Avionics: LRU health + BIT + fitness + SW configuration (RT 1) | 1 | IN PROGRESS (Alee, 2026-11-09) |
| 18 | Defensive systems (RT 22) | 0.5 | DONE 2026-11-07 |
| 19 | Flight surfaces (RT 21) | 0.5 | IN PROGRESS (Kevin, 2026-11-10) |
| 20 | Small utilities: ECS (RT 4), hydraulics (RT 19), airframe (RT 20), flight data monitoring (RT 23) | 1 | open |
| 21 | Radar display + PFD on the bus | 1.5 | DONE 2026-10-25 |
| 22 | MFD on the bus | 1 | DONE 2026-10-25 |
| 23 | Broadcast relays | 0.5 | DONE 2026-10-25 |
| 24 | EICAS on the bus | 0.5 | DONE 2026-11-01 |
| 25 | TSD on the bus | 0.5 | DONE 2026-11-01 |
| 26 | SMS on the bus | 0.5 | DONE 2026-11-02 |
| 27 | HUD on the bus | 0.5 | STRUCK 2026-11-02 (the Python HUD is an empty placeholder; removed from the total) |
| 28 | Scenario engine + debug CLI on the bus | 1.5 | open |
| 29 | Retire the old Python messaging stack and the radar bridge | 1 | open |
| 30 | Hardening: release build, timing checks, coverage targets, MISRA-subset lint, intern docs | 1.5 | open |

**Done: 23 / 29.5 = 78 %.** Open: 6.5 units.

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

- **Python to read in full**: `Systems/avionics/hardwareHealth/LRUstatus.py` (449;
  `LRUStatusMonitor` at 1 Hz: `_build_catalogue()` maps each LRU to a live subsystem's getter
  (`_acc(import_path, func)`), `_derive_health(status, lru)` turns a status dict into a
  `HealthState`, forced faults for the scenario engine (`force_fault`, `clear_forced_fault`,
  `get_forced_faults`), `get_faults`, `overall_health`, `update_bit_result`),
  `builtInTesting.py` (297; `PowerOnSelfTest`, `PeriodicBIT` whose intervals are minutes
  from the config, `InitiatedBIT`; `_probe_system` pokes a live subsystem),
  `Systems/builtInTestSystems/bitControl.py` (153; `BuiltInTestController` parses
  `bitsConfig.xml` (72 lines: self tests, periodic tests with intervals, interface tests) and
  runs them), `Systems/fmFitness/fmStatus.py` (155; `FlightManagementFitness` at 1 Hz:
  `check_thresholds(component, metrics)` from `fmfConfig.xml` (33 lines),
  `handle_redundancy`), `Systems/configurationManagement/swConfigure.py` (121;
  `SoftwareConfigManager` reads `swcmConfig.xml` (52 lines: components, versions, data
  loads); `run()` applies one hard-coded data load "20191015"; it has no thread).
- **Consumers today**: the EICAS lists `BuiltInTestController().self_tests` as "id: PASS"
  strings (`eicas.py` around 343; `SystemsFeed.bit.self_tests = []` for now); the scenario
  engine's failure injection calls `LRUStatusMonitor.force_fault` (unit 28 will send it as a
  command). The scenario engine's forced fault is the only path that makes an LRU unhealthy.
- **Shape of the port**: on the bus the LRU monitor cannot call other subsystems' getters.
  Its inputs are what the bus controller already knows: every terminal's TERM_STATUS reply
  (state, BIT word) and its poll statistics. The clean design is a bus-health message from
  the bus controller (per RT: state, BIT word, answered/no-response counts) that RT 1
  receives at 1 Hz; RT 1 derives the LRU table from it, applies forced faults, runs the BIT
  schedule (power-on, periodic, initiated), the fitness thresholds and the software
  configuration table, and publishes `AVN_STATUS` (overall health, fault count, BIT
  summary) and an `AVN_LRU` block (per LRU: health, last BIT result, forced) for the EICAS,
  with `AVN_CMD` (initiated BIT; force/clear a fault; apply a data load). This touches the
  bus controller (`B20SS/ofp/bc/`): keep that change small, with its own test in
  `bus_controller_test.cpp`.
- **Tests**: oracle = `_derive_health`, `check_thresholds` and `PeriodicBIT.run_due` with a
  patched clock; the EICAS BIT list in the feed and render tests; a scripted forced fault
  end to end.
- **Traps**: `_probe_system` and `_build_catalogue` import every live subsystem (do not port
  the probe, port the catalogue and the rules; construct the monitor in the oracle without
  starting it); periodic intervals are 90 minutes (nothing happens in a test without a clock
  you control); `swConfigure.run()` is a one-shot hard-coded load; `avConfig.xml` is a
  placeholder.

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

- **Python to read in full**: `Systems/flightSurfaces/flightSurfaceService.py` (292; a
  50 Hz loop; `Surface.step(dt)` moves each surface toward its command at a rate limit;
  `_sync_from_fcc()` takes the commanded positions from the flight control computer (on the
  bus that is `FCS_SURFACE_STATUS`); `set_flaps(detent)`, `set_speedbrake(pct)`,
  `set_rudder(deg)`, `set_trim(axis, deg)`; `_persist` to SQLite; `get_data()` the positions;
  `health_report`). `fsConfig.xml` is three lines.
- **Consumers today**: none draws it. The natural consumer is the FCS itself: today
  `FCS_SURFACE_STATUS` reports commands, never measured positions.
- **Shape of the port**: RT 21 receives `FCS_SURFACE_STATUS` by relay, moves the surfaces at
  the Python's rates (50 Hz = every minor frame), publishes `FSF_POSITIONS` (measured
  positions with SSMs) relayed to the FCS, which reports them beside its commands (one new
  field group, or a second message; keep `FCS_SURFACE_STATUS` compatible), and takes
  `FSF_CMD` for flaps, speedbrake, rudder and trim. Smallest unit after the HUD: keep it so.
- **Tests**: oracle = `Surface.step`; a C++ test for the rate limit; e2e: command a surface
  through `FCS_SURFACE_CMD` and watch the position arrive over a few frames.

### 2.20 Small utilities, 1 (ECS RT 4, hydraulics RT 19, airframe RT 20, flight data monitoring RT 23)

Four thin terminals, one unit. Each is a small class with `init/step/status`, a status
message, and a plant source wherever the Python invented its readings. The EICAS gets its
remaining UNKNOWN rows from them (hydraulics C, ECS; electrical is unit 16) through
`set_system_readings` in `EicasWindow.tick()`.

- **ECS** `Systems/enviornmentalControlSystem/ecsControl.py` (199; 2 Hz; readings are
  hard-coded unless `set_sensor_readings` is called; `adjust_temperature/pressure/
  air_quality` nudge toward the targets of `ecsConfig.xml` (27 lines); `climate/
  climateControl.py` 41 and `oxygenGenerationsys/oxygenControl.py` 42 are stubs). Cabin
  environment to the plant (`PLANT_CABIN`), the regulation to RT 4, `ECS_STATUS` to the EICAS.
- **Hydraulics** `Systems/hydraulics/hydrControl.py` (187; 1 Hz; `monitor_pressure` over
  systems A/B/C against `hydrConfig.xml` (35 lines: nominal and minimum pressures),
  `activate_backup`, `health_report`). Pressures to the plant (`PLANT_HYDRAULICS`), the
  low-pressure and backup logic to RT 19, `HYD_STATUS` to the EICAS (whose A/B rows come
  from a g-load model today, C is unknown: the terminal's values replace the model).
- **Airframe** `Systems/airframeSystemManagement/airframeControl.py` (176; 1 Hz;
  `monitor_airframe` compares sensor readings with `asmConfig.xml` (38 lines) limits;
  `control_landing_gear(command)`, which the Python calls with "deploy" on every tick: a
  known defect; the port follows the FMS gear command in `FMS_CONTROL_STATUS` instead and
  says so in the ICD README section 2). Loads and temperatures to the plant, the limit
  checks and the gear state to RT 20, `AFR_STATUS`.
- **Flight data monitoring** `Systems/flightDataMonitoring/fdmControl.py` (148; a 2 Hz
  `_record_loop`: `collect_data()` snapshots other subsystems into the recorder,
  `eject_storage(slot)`; `fdmsConfig.xml` 53 lines lists the recorded parameters). On the bus
  RT 23 listens to the broadcasts it records (FMS flight data, engine status, GCAS alerts)
  into a fixed ring buffer and publishes `FDM_STATUS` (record count, slot state); a dump
  through the monitor or a command for the CLI (unit 28). No display reads it.

### 2.28 Scenario engine + debug CLI on the bus, 1.5

- **Python to read in full**: `Interfaces/scenarios/scenarioEngine.py` (395; loads
  `trainingScenario.xml` (126) or `failureScenario.xml` (106), sorts events by `time_s`, a
  daemon thread dispatches them; injectors `_inject_radar_contact` (writes a radar's
  `current_targets`), `_inject_failure` (an LRU forced fault), `_inject_weather` (a cell into
  the weather state manager), `_inject_threat` (RWR), `_inject_waypoint`, `_inject_phase`,
  `message` (log only)) and `Utils/debug/userCLI.py` (1031; a click REPL on four threads:
  `status`, `send`, `msg`, `test`, `test_1553b`, `scenario`, `help`).
- **Shape of the port**: both stay Python and become bus clients, like the plant and the
  displays. The scenario engine reads the same XML and sends bus commands at the right frame:
  waypoints and phases as `MSN_CMD`, radar contacts, weather cells and threats as
  injections into the plant (new plant *receive* messages, `PLANT_INJECT_*`, since the world
  lives there), failures as the avionics command of unit 17. The CLI becomes a REPL over the
  monitor port (status = decode the latest TERM_STATUS and status messages) and a command
  path. Both need one new thing in the bus controller: a command socket through which a
  Python client queues an aperiodic transaction (`fmofp_bc --script FILE` already queues
  commands by frame; generalise it to a port and add a `fmofp_bus` client). Design it first,
  write it in the ICD README section 7, then build. Both scenario files must run end to end
  over the bus in a test. The demo's scripted events (`fmofp_demo/demo.py`) are the model for
  the engine's output.

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
bash B20SS/verify.sh            # icd, cpp (configure + build + ctest + cppcheck), py (217 tests), load
bash B20SS/verify.sh icd py     # any subset, in order
```

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
`fmofp_bc --report` the per-terminal statistics.

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
