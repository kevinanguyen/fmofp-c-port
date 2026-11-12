# FMOFP OFP — the C++ flight software

The C++ port of FMOFP's flight logic. It talks to the Python displays and tools only
through the simulated MIL-STD-1553B bus defined in [`../icd/`](../icd/README.md).
Rules for the code are in [`CLAUDE.md`](CLAUDE.md).

## Layout

| Directory | Contents | Target |
|---|---|---|
| `bus/` | Bus word primitives (bit fields, two's complement, scaling), command and status words, the datagram framing, `RemoteTerminal`: what every terminal owes the bus, and the block transfer (descriptor and segments) for payloads over 32 words, with `BlockPublisher` and `BlockCollector` to put a block on a terminal's subaddresses | `ofp::bus` |
| `osal/` | The only code that talks to the OS: monotonic clock with absolute-deadline sleep, UDP on 127.0.0.1. One implementation each for Windows and POSIX | `ofp::osal` |
| `icd/` | Builds the generated headers (`fmofp/icd/enums.hpp`, `messages.hpp`, `blocks.hpp`, `version.hpp`) from `../icd/fmofp_icd.xml`. Nothing here is checked in | `ofp::icd` |
| `bc/` | The bus controller: the 20 ms schedule, the frame loop with sync and timing, the transaction engine, and the `fmofp_bc` process, which can also send commands to terminals at given frames from a script or from a client of its command port (the scenario engine, the debug CLI, the tests: ICD README section 7) | `ofp::bc`, `fmofp_bc` |
| `partitions/` | `common/`: the socket loop every partition runs around its terminal. `rt_stub/`: a stand-in terminal that answers `TERM_STATUS`. `fcs/`: flight control, the first ported partition (GCAS alerts, envelope monitoring, mode and surface commands). `nav/`: navigation (the GPS position solver, the GPS / dead-reckoning fusion), plus `fmofp_nav_tool`, which puts its arithmetic on stdin/stdout for the Python oracle tests. `fms/`: flight management (flight modes and their envelopes, attitude commands and maneuvers, autopilot targets, thrust and gear, the flight data the displays read, energy maneuverability). `radar/`: the radar computer with the weather radar, the terrain-following radar, the targeting radar and the AEWC radar ported, and the cross-radar track fusion: the sensor model that renders the plant's weather, the signal processing (VIL, rain rate, storm cells, precipitation areas, wind shear, turbulence), the 1.2 s scan and the products block; the clearance assessment, path optimiser and terrain warnings over the plant's terrain profile, the guidance and the elevation block; the track table over the plant's traffic with the signature analyser, the stealth detector, the lock and the track filter; the AEWC's own track table over the same traffic out to 400 km, with its radar equation, its sectors and their priorities and its electronic protection; and the fusion's epochs over both radars' tracks; plus `fmofp_radar_tool` for the oracle tests. `engine/`: engine management (the commanded thrust of each engine, the autothrottle and the asymmetry check; the tanks, fuel lines, transfer policy and fuel monitor; the assessment of the engines' measurements; the engine model itself runs in the plant), plus `fmofp_engine_tool`. `mission/`: the mission computer (the route and its progress, the designated targets, the order of battle, the phase), plus `fmofp_mission_tool`. `comms/`: communications (the radio, satcom and data-link state and controls over the plant's RF environment). `defensive/`: defensive systems (the radar warning receiver's contact table over the fused air tracks and the plant's ESM intercepts, the chaff and flare dispensers with the automatic salvo and its cooldown, the ECM mode), plus `fmofp_defensive_tool`. `sensor/`: sensor management (the six sensors' states and the health rule, the sensor data fusion's contact table over the plant's radar, LIDAR, infrared and ESM detections), plus `fmofp_sensor_tool`. `power/`: power management (the main, APU and emergency batteries charged or discharged by the plant's electrical balance, the avionics coolant loop with its fan controller, the cabin's HVAC, the generator hold and the component controls), plus `fmofp_power_tool`. `surfaces/`: the flight surfaces (the ten control surfaces moved toward their commands at their slew rates: the ailerons and elevators from the sensed roll and pitch, the slats from the angle of attack, the flaps, speedbrake, rudder and trim from `FSF_CMD`), plus `fmofp_surfaces_tool`. `ecs/`, `hydraulics/`, `airframe/`, `fdm/`: the four small utilities (the cabin's three checks, climate copy and oxygen generator; the hydraulic pressure monitor and backup switch; the airframe readings and the landing gear state the FMS commands; the flight data recorder over the FMS flight data heard by broadcast, with its storage cards), plus `utilities_tool/` (`fmofp_utilities_tool`, the four on stdin for the oracle tests). Each is a pure library plus a process | `ofp::rt_process`, `fmofp_rt_stub`, `ofp::fcs`, `fmofp_fcs`, `ofp::nav`, `fmofp_nav`, `fmofp_nav_tool`, `ofp::fms`, `fmofp_fms`, `ofp::radar`, `fmofp_radar`, `fmofp_radar_tool`, `ofp::engine`, `fmofp_engine`, `fmofp_engine_tool`, `ofp::mission`, `fmofp_mission`, `fmofp_mission_tool`, `ofp::comms`, `fmofp_comms`, `ofp::defensive`, `fmofp_defensive`, `fmofp_defensive_tool`, `ofp::sensor`, `fmofp_sensor`, `fmofp_sensor_tool`, `ofp::power`, `fmofp_power`, `fmofp_power_tool`, `ofp::surfaces`, `fmofp_surfaces`, `fmofp_surfaces_tool`, `ofp::ecs`, `fmofp_ecs`, `ofp::hydraulics`, `fmofp_hydraulics`, `ofp::airframe`, `fmofp_airframe`, `ofp::fdm`, `fmofp_fdm`, `fmofp_utilities_tool`, `ofp::avionics`, `fmofp_avionics`, `fmofp_avionics_tool` (`avionics/`: the LRU health monitor, the built-in tests, the fitness rule and the software configuration, RT 1) |
| `tests/` | GoogleTest unit tests for the hand-written code, including the Phase 1 gate run in-process | `ofp_tests` |
| `cmake/` | The compiler flags every target gets | `ofp::warnings`, `ofp::flight` |

## Running the bus

The Phase 1 gate: a bus controller and two terminals in separate processes,
exchanging `TERM_STATUS` in lockstep for 150 frames (3 s) with no overruns.
From `build/<preset>/`, in three shells (or background the first two):

```bash
partitions/fmofp_rt_stub --rt 1 --port-base 53000
partitions/fmofp_rt_stub --rt 2 --port-base 53000
bc/fmofp_bc --rt 1 --rt 2 --port-base 53000 --frames 150 --strict
```

`--strict` makes `fmofp_bc` exit 1 if any terminal failed to answer or any frame
overran. Leave out `--frames` to run until killed; add `--report` for a line per
major frame and `--free-run` to go as fast as the terminals answer. Default ports
follow the ICD (base 51000: terminal *n* at 51000+*n*, the controller at 51032,
the monitor at 51033, the command port at 51034); a different `--port-base` lets two
buses share a machine. The command port is how the scenario engine, the debug CLI and
the tests queue commands (ICD README section 7); `--no-command-port` leaves it closed.

With `--report`, `fmofp_bc` also prints where the frames' time went when it stops (unit 30), after its
statistics: `bc: timing: overruns_late_start=N worst_wake_late_us=N` (the overrun frames
whose own work fitted the 20 ms period, so they overran because they started late, and the
latest any frame started after its deadline), then one line per terminal,
`rt N timing: mean_response_us=N worst_response_us=N overruns_slowest=N`: how long its
answers took, and of how many overrun frames it gave the slowest answer. A terminal with a
large `overruns_slowest` is the first place to look; a large `overruns_late_start` with
every terminal quick is the machine, not the bus.

## Seeing the whole aircraft run

One command starts everything on the bus and shows what crosses it. From `B20SS/`:

```bash
py -m fmofp_demo
```

It starts the plant (the simulated aircraft with its weather, terrain and
engines, its air traffic), the five ported partitions, the five display windows and the bus
controller, runs a short scripted flight (radars on, the thrust lever, the
autothrottle, a flight mode change, one engine throttled back, a fuel
transfer; each event is announced as it happens) and prints one line a second:
altitude, airspeed and heading from the FMS, the GCAS state, the engines' N1
and the fuel, the radars' modes and the terrain clearance, the navigation fix,
and which terminals are answering. The radar display window's buttons keep
working: it is the radars' control panel. Each program's log is under
`logs/demo/`. Stop with Ctrl-C.

`--seconds 30` runs for a fixed time, `--headless` runs the displays without
windows (what `test_demo.py` does on CI), `--no-events` leaves the flight to
the display's buttons, `--hold altitude=5000,speed=450` pins the aircraft,
`--build DIR` points at another build. On Windows the binaries need the MSYS2
runtime; the launcher puts `C:\msys64\ucrt64\bin` on the children's PATH
itself, so nothing has to be on yours. If the C++ or the ICD changed since the
binaries were built, it says so; rebuild as described under *Building*.

Each display program is a PyQt6 window plus a bus terminal in a helper
process of its own (`fmofp_display/terminal_process.py`): the window's
painting (the weather picture animates thousands of particles) holds the
Python interpreter for longer than a bus reply may take, and with the terminal
in a thread of the window the radar display missed every poll once the first
scan arrived. The helper answers the bus and forwards what it hears; the
window reads a mirror.

## Running the partitions

Flight control, navigation, flight management, the five radars (weather,
terrain-following, synthetic aperture, targeting and AEWC) with the track fusion,
engine management, the mission computer, communications, the defensive systems, sensor management,
power management, the flight surfaces, environmental control, hydraulics, the airframe systems, flight
data monitoring and the avionics health computer on the bus, fed by
the Python plant model (the simulated aircraft, its weather, its terrain, its two
engines, the air traffic around it, the ground beneath it, the RF environment it
flies through and its electrical system, RT 27). From `B20SS/`:

```bash
py -m fmofp_plant --port-base 53000                 # the aircraft; add --hold altitude=150 to test ALT LOW
ofp/build/<preset>/partitions/fmofp_fcs --port-base 53000
ofp/build/<preset>/partitions/fmofp_nav --port-base 53000
ofp/build/<preset>/partitions/fmofp_fms --port-base 53000
ofp/build/<preset>/partitions/fmofp_radar --port-base 53000
ofp/build/<preset>/partitions/fmofp_engine --port-base 53000
ofp/build/<preset>/partitions/fmofp_mission --port-base 53000
ofp/build/<preset>/partitions/fmofp_comms --port-base 53000
ofp/build/<preset>/partitions/fmofp_defensive --port-base 53000
ofp/build/<preset>/partitions/fmofp_sensor --port-base 53000
ofp/build/<preset>/partitions/fmofp_power --port-base 53000
ofp/build/<preset>/partitions/fmofp_surfaces --port-base 53000
ofp/build/<preset>/partitions/fmofp_ecs --port-base 53000
ofp/build/<preset>/partitions/fmofp_hydraulics --port-base 53000
ofp/build/<preset>/partitions/fmofp_airframe --port-base 53000
ofp/build/<preset>/partitions/fmofp_fdm --port-base 53000
ofp/build/<preset>/partitions/fmofp_avionics --port-base 53000
ofp/build/<preset>/bc/fmofp_bc --rt 27 --rt 5 --rt 7 --rt 12 --rt 9 --rt 3 --rt 6 --rt 2 --rt 22 --rt 10 --rt 8 --rt 21 --rt 4 --rt 19 --rt 20 --rt 23 --rt 1 --port-base 53000 --report
```

The controller polls the plant's `PLANT_SENSORS` 50 times a second and relays it
to every consumer that is present (`FCS_SENSORS`, `FMS_SENSORS`,
`NAV_SENSORS`, `RDR_TFR_SENSORS`, `FSF_SENSORS`), polls the plant's GPS pseudoranges and its
weather once a second and relays them (`NAV_GPS`, `RDR_WX_WEATHER`), polls the
plant's terrain block every frame and relays its descriptor and segments to the
radar (`RDR_TFR_TERRAIN`, the first block relay), relays `FCS_ATTITUDE` and
`NAV_SOLUTION` to the FMS and the radar's `RDR_TFR_GUIDANCE` to the FCS
(`FCS_TERRAIN`, where the ground collision avoidance TERRAIN alert now gets its
clearance), and collects everything the partitions publish, including the
radar's `RDR_WX_PRODUCTS` and `RDR_TFR_ELEVATION` blocks a segment every other
frame (25 Hz: a second display's copies had pushed the 50 Hz schedule past the
controller's bus-load budget).
Anything listening on the monitor port sees every transaction
(`fmofp_bus.monitor` reads it from Python; `fmofp_bus.block.blocks_from_records`
reassembles the blocks). The radars do nothing until they are told a mode: a
`RDR_WX_MODE_CMD` (RT 9, SA 1) for NORMAL and SURVEILLANCE starts the weather
radar scanning, and `RDR_WX_SCAN` then reports what each 1.2 s sweep found; a
`RDR_TFR_MODE_CMD` (RT 9, SA 2) for NORMAL and TERRAIN_FOLLOWING with a set
clearance starts the terrain-following radar assessing each profile the plant
publishes, and `RDR_TFR_GUIDANCE` reports the clearance and the first altitude
command ten times a second; a `RDR_SAR_MODE_CMD` (RT 9, SA 3) for NORMAL and
STRIPMAP at a resolution starts the synthetic aperture radar picturing the
strip 2 km to the right of the track from the plant's ground scene, an image
every 3 s (`RDR_SAR_IMAGE`), once the FMS flight data broadcast has given it a
position. The engine computer needs no command: the FMS
thrust lever (50 % until an `FMS_CONTROL_CMD` moves it) reaches it as
`ENG_FMS_CONTROL`, it commands the plant's engines (`ENG_THRUST_CMD`, relayed
as `PLANT_THRUST_CMD`), their measurements come back as `ENG_ENGINE_IN`, and
its engine and fuel status go out by broadcast (31/18, 31/19), where the flight
computer picks up the fuel flow for its fuel efficiency and the MFD its engine
rows. An `ENG_CMD` (RT 3, SA 13) sets one engine's thrust, engages the
autothrottle at a target airspeed or moves fuel between tanks. The mission
computer (RT 6) hears the FMS flight data broadcast for the route's progress and
takes `MSN_CMD` (RT 6, SA 11): waypoints, the phase, designated targets and their
engagement, units of the order of battle, a route optimisation around the enemy
ones; its `MSN_STATUS` and `MSN_PLAN` block go to the MFD and the TSD by
broadcast. The communications terminal (RT 2) measures the plant's RF
environment (`PLANT_RF`, relayed as `COM_RF`: the field strength, a satellite
that comes into view by chance, the link's traffic) and takes `COM_CMD` (RT 2,
SA 12): the radio's frequency and mode, a satellite acquisition, transmissions on
the radio, the satcom and the data link; its `COM_LINK_STATUS` reaches the MFD's
communications page by relay. The defensive systems terminal (RT 22) hears the
fused air tracks broadcast (31/22-23) and the plant's ESM intercepts (`PLANT_ESM`,
relayed as `DEF_ESM`): its radar warning receiver keeps a contact per hostile track
and per intercept for ten seconds, its flare dispenser fires a salvo of two by itself
on a priority-1 hostile contact (three seconds between salvos), and it takes `DEF_CMD`
(RT 22, SA 12): chaff and flares by hand, the ECM mode, a scenario threat injected on
the receiver. Its `DEF_STATUS` reaches the EICAS by relay and its `DEF_RWR_CONTACTS`
block the EICAS and the TSD by broadcast. The sensor management terminal (RT 10)
receives the plant's sensor scans block (`PLANT_SENSOR_SCAN`, relayed as `SNS_SCAN`) and
its ESM intercepts (`SNS_ESM`), fuses them into its contact table five times a second,
takes `SNS_CMD` (RT 10, SA 12) to switch one of its six sensors on or off, and sends
`SNS_STATUS` to the EICAS by relay. The power management terminal (RT 8) receives the
plant's electrical reading once a second (`PLANT_ELECTRICAL`, relayed as `PWR_ELECTRICAL`)
and runs its bookkeeping on each: the main battery takes the surplus or supplies the
deficit, the APU battery charges at a quarter, the emergency battery carries its load
while the emergency mode is on, the coolant loop and the cabin move on; it takes `PWR_CMD`
(RT 8, SA 13) for the generator hold (which reaches the plant as `PLANT_GEN_CMD`) and the
component controls, and sends `PWR_STATUS` to the EICAS by relay, where it fills the
electrical rows. The flight surfaces terminal (RT 21) receives the plant's sensed flight
state every frame (`PLANT_SENSORS`, relayed as `FSF_SENSORS`) and moves its ten surfaces
toward their commands at their slew rates: the ailerons from the roll, the elevators from
the pitch, the slats from the angle of attack, and the flaps, speedbrake, rudder and trim
from `FSF_CMD` (RT 21, SA 12); `FSF_POSITIONS` says where they are, `FSF_STATUS` the flap
detent and the trim. Nothing consumes them yet (the monitor and the demo's dashboard read
them from the controller's table). The four small utility terminals (v1.22) receive the
plant's cabin readings (`PLANT_CABIN`, relayed as `ECS_CABIN`, twice a second), hydraulic
pressures (`PLANT_HYDRAULICS` → `HYD_PRESSURES`) and airframe sensors (`PLANT_AIRFRAME` →
`AFR_SENSORS`), once a second; the environmental control terminal (RT 4) runs its three
checks, its oxygen generator and its climate copy on each reading and takes `ECS_CMD` (RT 4,
SA 12); the hydraulics terminal (RT 19) judges the active system's pressure and switches to
the backup on CRITICAL or on `HYD_CMD` (RT 19, SA 12); the airframe terminal (RT 20) reports
its readings and moves its gear state when the FMS's gear command changes
(`FMS_CONTROL_STATUS`, relayed as `AFR_FMS_CONTROL`) or on `AFR_CMD` (RT 20, SA 13); the flight
data monitoring terminal (RT 23) records the FMS flight data it hears by broadcast twice a
second and ejects a card on `FDM_CMD` (RT 23, SA 11). `HYD_STATUS` and `ECS_STATUS` reach the
EICAS by relay, where they fill the hydraulic and cabin rows. The avionics terminal (RT 1) is the one
terminal the controller itself feeds: once a second, from the second major frame on, `fmofp_bc` writes
`AVN_BUS_HEALTH` into RT 1 SA 11 (which terminals are listed, have answered, are answering, and what each
one's `TERM_STATUS` says; `bc/bus_health.hpp`). On each report the terminal derives the health of its
eleven line replaceable units, runs the power-on self test the first time and the periodic tests that are
due, and checks the fitness thresholds; it takes `AVN_CMD` (RT 1, SA 13) for the scenario engine's forced
faults (by name, as `force_fault(key)` took one), the initiated built-in test, a data load and the
fitness redundancy, and sends `AVN_STATUS` to the EICAS by relay, where it fills the BITS rows.

To command a partition, give the controller a script: one command per line,
`frame rt sa word word ...` with the data words in hex, sent in that minor
frame. For example, a `FMS_MANEUVER_CMD` (RT 12, SA 18) for BREAK_RIGHT with
`cmd_seq` 1 in frame 10, and a `FMS_FLIGHT_MODE_CMD` (SA 20) for COMBAT in
frame 40:

```text
# frame rt sa words
10 12 18 0001 0001 0000
40 12 20 1001
```

```bash
ofp/build/<preset>/bc/fmofp_bc --rt 27 --rt 5 --rt 7 --rt 12 --port-base 53000 --script commands.txt
```

**The scenario engine and the debug CLI.** Both are Python clients of the controller's command port (ICD README section 7) and need nothing but a running bus. From `B20SS/`, with the aircraft up (`py -m fmofp_demo`, or the processes by hand at the same port base):

```bash
py -m fmofp_scenario FMOFP/Interfaces/scenarios/trainingScenario.xml --speed 10
py -m fmofp_cli
```

The engine reads the frozen scenario file, times its events by the bus frame (`--speed 10` runs the 510 s scenario in 51 s) and sends each as the bus command its Python injector amounted to: waypoints and phases to the mission computer, threats to the defensive terminal, failures to the avionics terminal, radar contacts and weather cells into the plant's world, where the radars find them; it prints a line per event with the controller's acknowledgement and exits 0 when every command was queued. The CLI is a prompt: `terminals` and `status RT` decode what the monitor has shown of each terminal, `msg ID` the latest message of a kind field by field, `send ID field=value ...` builds any ICD command message and queues it (`send MSN_CMD command=SET_PHASE phase=EGRESS`), `scenario load|events|start|stop|status` drives the engine from the prompt, and `-c COMMAND` runs commands without it. `--port-base` on both selects the bus.

**The displays.** Six of the PyQt6 displays run as their own bus terminals
(`B20SS/fmofp_display`): the radar display, RT 15, which shows the weather and
terrain-following radars' pictures and commands the weather, terrain-following,
targeting, AEWC and synthetic aperture radars; the primary
flight display, RT 11, which reads the FMS's flight data; the multi-function
display, RT 13, whose radar page mirrors the radars' pictures from the same
broadcasts, draws the targeting and AEWC radars' tracks and the SAR's picture of
the ground, whose systems page shows the flight computer's GCAS alerts and
envelope exceedances and the engine computer's readings, and whose mission
page shows the mission computer's route, targets and order of battle with
the FMS position, and whose communications page the radio, satcom and data
link; and the EICAS, RT 14, which shows the engine computer's
readings and tanks, the flight computer's alerts, the weather radar's wind
shear and turbulence severities and the crew alert list (its hydraulic,
electrical and ECS rows wait for those terminals); and the TSD, RT 16, which
shows the fused air tracks around the aircraft, the mission computer's route
and its enemy units as hostile contacts, the FMS's energy metrics and the
tactical systems strip (its radar warning contacts wait for the defensive
terminal); and the SMS, RT 17,
which shows the weapon stations and the signature strip, its master arm
following the FMS's weapons state (its stations are the display's own table
until a stores management computer exists). List them for the
controller and give it a reply timeout a Python process beside a Qt paint loop
can meet, without `--strict`:

```bash
py -m fmofp_display radar --port-base 53000
py -m fmofp_display pfd --port-base 53000
py -m fmofp_display mfd --port-base 53000
py -m fmofp_display eicas --port-base 53000
py -m fmofp_display tsd --port-base 53000
py -m fmofp_display sms --port-base 53000
ofp/build/<preset>/bc/fmofp_bc --rt 27 --rt 5 --rt 7 --rt 12 --rt 9 --rt 3 --rt 11 --rt 13 --rt 14 --rt 15 --rt 16 --rt 17 --rt 6 --rt 2 --port-base 53000 --timeout-ms 20 --report
```

The controller broadcasts the radars' status, scan summary and guidance, their
product blocks segment by segment, the flight computer's alerts and
exceedances and the FMS's flight data once each, to address 31; every display
accepts the subaddresses it draws and ignores the rest (ICD README section 8),
so another display costs the bus nothing for data it already broadcasts. The
radar display's mode buttons load `DSP_RDR_WX_CMD` / `DSP_RDR_TFR_CMD` /
`DSP_RDR_TGT_CMD` / `DSP_RDR_AEWC_CMD` / `DSP_RDR_SAR_CMD` on its own subaddresses, which the
controller relays into the radar every 100 ms. The
display classes under `FMOFP/Interfaces/userInterface/displays` are unchanged:
a feed turns the bus words into the dictionaries they always drew. The MFD's
pages import the engine, GCAS, performance, comms and mission services'
getters when they paint; the MFD process registers stand-ins under those
module names, so the feed answers the getters and no flight-system code runs
in a display.

The Python message classes encode the words (`FmsManeuverCmd(...).encode()`),
which is how the tests write their scripts. `test_fcs_e2e.py`, `test_nav_e2e.py`,
`test_fms_e2e.py`, `test_radar_e2e.py` and `test_tfr_e2e.py` run exactly these
processes: the first checks the FCS's alerts against the original Python GCAS
on the same numbers, with the real radar measuring the clearance over flat
terrain, the second that navigation lands on the plant and moves with it, the
third that the FMS answers a scripted sequence of commands as the original
`fmsControl` does, the fourth that the weather radar scans, answers mode
commands and publishes its block on cadence, the fifth that the plant's terrain
reaches the radar through the block relay, that the guidance and the elevation
block are the assessment of that terrain, and that the FCS's TERRAIN alert
follows the radar. `test_engine_e2e.py` runs the plant, the FCS, the FMS and
the engine computer with a scripted lever movement, a single-engine thrust
command, an autothrottle engagement and a fuel transfer, and checks the plant's
engines, the engine status, the flight computer's fuel efficiency and the
tanks against them. `test_nav_oracle.py`, `test_weather_oracle.py` and
`test_tfr_oracle.py` check the arithmetic against the original Python through
`fmofp_nav_tool` and `fmofp_radar_tool`: the rendered volume, the VIL and
rain-rate fields, the point selection, the storm cell detection, the
precipitation areas, the wind shear events and the turbulence cells; the
clearance levels and their latch, the path commands and the terrain warnings.
`test_engine_oracle.py` drives `thrustManagement.py`'s thrust manager and
`fmofp_engine_tool` through the same lever inputs and autothrottle steps, and
`test_plant_engine.py` checks the plant's engine model against
`engineControlUnit.py`'s formulas. `test_targeting_e2e.py` runs the plant with its
traffic, the radar and the controller through search, a lock and standby, and
checks the tracks block against the plant's aircraft and the fused block against
the tracks; `test_targeting_oracle.py` checks the signature analyser, the stealth
detector, the threat rule and a fusion epoch against the original Python through
`fmofp_radar_tool`, and `test_plant_traffic.py` the plant's traffic against the
radars' generators; `test_aewc_oracle.py` checks the AEWC's radar equation, sectors,
priorities and electronic protection the same way, and `test_targeting_e2e.py`
runs both radars and checks the fused tracks carry both. `test_sar_e2e.py` runs
the plant over a scene of its own with the flight control, navigation, flight
management and radar partitions and checks the strip picture (the road in it),
two spotlight pictures of one patch with the ship three pixels further on, and
standby's empty block; `test_sar_oracle.py` checks the change detector against
`sar_processor.py` event for event and the picture's geometry and levels through
`fmofp_radar_tool`, and `test_plant_ground.py` the plant's training range.
`test_mission_oracle.py` runs the frozen `handleRoute.py`, `targeting.py` and
`orderOfBattle.py` beside `fmofp_mission_tool` (the route's progress and ETEs,
target insertion and threat deviation, the target status machine and its decay,
the order of battle's threats), `test_mission_e2e.py` flies a route under the
real controller with a script of mission commands, `test_comms_e2e.py` tunes,
acquires and transmits with a scripted satellite, and `test_plant_rf.py` checks
the plant's RF environment.
`test_defensive_oracle.py` runs the frozen `defensiveService.py` beside
`fmofp_defensive_tool` (the contact table from fused tracks and intercepts, its
expiry, the automatic salvo and its cooldown, the manual dispensers, the ECM
modes) and records the Python's dead fusion branch; `test_defensive_e2e.py` runs
the plant, the radar and the defensive partition under the real controller with
a scripted threat and commands and reads the results at the EICAS's and the TSD's
bus halves; `test_plant_esm.py` checks the plant's intercepts against the Python's
sensor draw for draw.
`test_sensor_oracle.py` runs the frozen `sensorService.py` and `sensorDataFusion.py`
beside `fmofp_sensor_tool` (the health rule, the contact table's merges,
corroboration and expiry, the id counter); `test_sensor_e2e.py` runs the plant and
the sensor partition under the real controller with sensors switched off and on and
reads the result at the EICAS's bus half; `test_plant_sensors.py` checks the plant's
scans against the Python's sensors draw for draw.
`test_power_oracle.py` runs the frozen `powerManagementSystem.py` with its batteries and
thermal units beside `fmofp_power_tool` second for second (the balance through the
batteries, the coolant loop, the cabin, the manual controls) and records the Python's
`set_generator_output`; `test_power_e2e.py` runs the plant and the power partition under
the real controller with the generator held at zero and released, the emergency power on
and a setpoint moved, and reads the result at the EICAS's bus half; `test_plant_electrical.py`
checks the plant's readings against the Python's draws draw for draw.
`test_surfaces_oracle.py` runs the frozen `flightSurfaceService.py` beside `fmofp_surfaces_tool`
pass for pass (the sync from the sensed attitude, the slew-rate steps with a varying dt, the
detents and clamps of the manual controls) and records the Python's quirks; `test_surfaces_e2e.py`
runs the plant with its attitude held and the surfaces partition under the real controller with
the flaps, speedbrake, rudder and trim commanded, and reads the positions from the monitor.
`test_utilities_oracle.py` runs the frozen `ecsControl.py`, `hydrControl.py`, `airframeControl.py` and
`fdmControl.py` beside `fmofp_utilities_tool` (the ECS's checks, oxygen and climate pass for pass with its
logger captured, the hydraulics config and backup switch, the gear state machine and sensor table, the
recorder's tables and card ejection) and records their quirks; `test_utilities_e2e.py` runs the plant, the
four partitions, the FCS and the FMS under the real controller with the hydraulic pressure and the cabin
held, the gear commanded through the FMS and by hand, the backup system switched in and a card ejected,
and reads the result at the EICAS's bus half; `test_plant_utilities.py` checks the plant's three new
worlds.
`test_avionics_oracle.py` runs the frozen `LRUstatus.py`, `builtInTesting.py`, `bitControl.py`,
`fmStatus.py` and `swConfigure.py` beside `fmofp_avionics_tool`, every subsystem they reached into replaced
by a stand-in that answers what the bus view says of its terminal (`_derive_health` over every status, the
polls, the key resolution, the forced faults through polls and clears, the three test families by a
patched clock, the fitness equality, the data loads) and records their quirks; `test_avionics_e2e.py` runs
the plant, the FCS and the avionics partition under the real controller with a script of forced faults,
an initiated test and a data load, reads the controller's own reports from the monitor and the BITS rows
at the EICAS's bus half, and in a second run without the plant watches the flight control computer's
DEGRADED reach its three LRUs; `bus_controller_test.cpp` checks the report itself.
`test_display_e2e.py` runs the six display terminals headless beside the
whole set of partitions and checks that the radars' products and the FMS's
flight data arrive at the displays by broadcast, that the flight computer's
alerts and exceedances and the engine computer's engine and fuel status reach
the MFD and the EICAS, that the targeting radar's tracks reach the MFD and
the fused tracks the EICAS and the TSD, the radar warning contacts and the
defensive status the displays, and that the radar display's commands
reach the radars; `test_display_feeds.py` checks the feeds
and `test_display_render.py` paints the six windows offscreen from sample
bus data, the MFD through every page and radar picture, the EICAS with its
alert list and countermeasures panel, the TSD with its radar warning contacts
and the SMS with its master arm following the FMS status (skipped without PyQt6).

## Building on Windows

Install MSYS2 (`winget install MSYS2.MSYS2`), open the **UCRT64** shell
(`C:\msys64\ucrt64.exe`), and install the toolchain once:

```bash
pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-cmake \
    mingw-w64-ucrt-x86_64-ninja mingw-w64-ucrt-x86_64-gtest \
    mingw-w64-ucrt-x86_64-cppcheck mingw-w64-ucrt-x86_64-gcovr
```

Then, in this directory:

```bash
cmake --preset windows-ucrt64
cmake --build --preset windows-ucrt64
ctest --preset windows-ucrt64
```

The ICD tool runs under the MSYS2 Python that comes with those packages; it needs
nothing outside the standard library.

## Building on Linux

```bash
sudo apt-get install g++ cmake ninja-build libgtest-dev cppcheck gcovr python3
cmake --preset linux-gcc
cmake --build --preset linux-gcc
ctest --preset linux-gcc
```

`linux-asan` is the same build with AddressSanitizer and UndefinedBehaviorSanitizer;
CI runs both. MinGW GCC has no sanitizers, so on Windows use `linux-asan` under WSL
if you need it locally.

## The optimised build

The presets above build Debug (`-O0`): the build to step through in gdb, and the one the
gate (`B20SS/verify.sh`) tests. `windows-ucrt64-release` and `linux-gcc-release` build the
same code with `-O2 -g` (CMake's RelWithDebInfo) into `build/<preset>-release/`:

```bash
cmake --preset windows-ucrt64-release     # or linux-gcc-release
cmake --build --preset windows-ucrt64-release
ctest --preset windows-ucrt64-release
```

`py -m fmofp_demo` flies this build when it exists and the debug one otherwise (`--build
DIR` chooses by hand). The radar computer is why: its worst answer to the bus was 6 to 28 ms
at `-O0` and 4 to 6 ms at `-O2` in the thirty-second demo. The whole gate runs against it
with `PRESET=windows-ucrt64-release bash B20SS/verify.sh cpp py load`: the oracle tests
compare the C++ with the frozen Python to many places, so they are also the check that
optimisation changed no computed word. CI builds and unit-tests it (`linux-gcc-release`).

## Other targets

```bash
cmake --build build/<preset> --target cppcheck     # static analysis, fails on any finding
cmake --build build/<preset> --target lint         # clang-tidy, the MISRA-style subset, fails on any finding
cmake --preset coverage && cmake --build --preset coverage   # tests + gcovr report + the floor per module
```

The coverage build runs the unit tests in an instrumented build and then holds each
module of flight code (`bus`, `osal`, `bc`, every `partitions/<name>`) to a floor of
covered lines: 80 %, `cmake/coverage_check.py`. It prints one line per module and fails
when one is under, so a partition cannot land with its logic untested behind a good
overall number. The process mains, the stdin tools and the generated ICD code are not
counted: the Python end-to-end and oracle tests run the first two (gcov does not see
those runs), and the generated code has generated tests. A module with a reason to sit
lower gets its own floor: `-DOFP_COVERAGE_FLOORS="partitions/x=70"`, with the reason in
`CMakeLists.txt`. CI runs it (`coverage`).

The lint is clang-tidy with `.clang-tidy` in this directory: the rules of `CLAUDE.md` that a
tool can hold (no recursion, no heap, no unions or reinterpreting casts, no unchecked
narrowing, every value initialised, every result that can fail looked at, and the
`bugprone` checks), each check listed there beside the rule it stands for. It runs over
the flight code only (`cmake/lint.py` picks `bus`, `osal`, `bc` and every partition's
`src/` from the compile database, less the mains and the stdin tools) and needs
clang-tidy installed (`pacman -S mingw-w64-ucrt-x86_64-clang-tools-extra` in UCRT64,
`apt-get install clang-tidy` on Linux); without it the target does not exist. To keep a
line as it is, say why on it: `// NOLINT(check-name): reason`. CI runs it on the
`linux-gcc` leg.

The intern's reading list is `docs/`: `docs/ARCHITECTURE.md` first, then
`docs/DEBUGGING.md` (one partition under gdb: a unit test, the stdin tool, on the bus).
`docs/TICKETS.md` is a draft of the intern ticket format, under review.

## Generated code

`cmake --build` regenerates the ICD headers whenever `fmofp_icd.xml` or
`icd_tool.py` changes. To read them, look in `build/<preset>/icd/generated/include/`,
or produce them anywhere with:

```bash
py ../icd/tools/icd_tool.py gen-cpp --out some/dir
```
