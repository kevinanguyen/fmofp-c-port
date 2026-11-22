# 10. Flight Management, Flight Control and the Aircraft

**Navigation:** [← Holographic Displays](09_Holographic_Display_System.md) | [Table of Contents](00_Title_and_TOC.md) | [The Bus →](11_Communication_Messaging.md)

---

This chapter covers the flight software outside the radars and displays, and the simulated aircraft it flies. Each
partition is a C++ program under `B20SS/ofp/partitions/<name>`, started by the demo or by hand
(`ofp/build/<preset>/partitions/fmofp_<name> --port-base 51000`). Its status message carries its state (INITIALIZING,
NORMAL, DEGRADED, ...); its commands are numbered. Every command below can be sent from the prompt with `send ID
field=value ...` (chapter 12); the named shortcuts are given where they exist.

## 10.1 The aircraft: the plant (RT 27)

The plant (`py -m fmofp_plant`, `B20SS/fmofp_plant`) is the world the flight software measures: the aircraft's flight
state, GPS pseudoranges, weather, terrain, traffic, the ground, radio fields, emitters, sensor scans, two engines, the
electrical system, the cabin, hydraulic pressures and airframe gauges. Each part has its own seeded random generator
(`--seed N` repeats a flight).

The aircraft's flight state is flown one of two ways:

- **Flight dynamics** (`--dynamics`, the demo's default since unit 36): upstream's `FlightDynamicsProcessor` driven by
  the flight control computer's commanded surface deflections (`FCS_SURFACE_STATUS`, relayed to the plant). Each
  axis' rate follows the command (roll 120, pitch 60, yaw 30 deg/s at full deflection) with a damping time constant;
  the attitude integrates the rates. The plant adds what the class left out: a banked aircraft turns (g tan(roll)/V),
  a pitched one climbs (V sin(pitch)), and the speed follows the engines' thrust (150 kt at idle plus 5 kt a percent).
  With no command it flies straight and level.
- **The random walk** (the plant's default, and every test's; `py -m fmofp_demo --walk`): the original flight control
  computer's walk of altitude, speed, heading and attitude at 10 Hz.

`--hold name=value,...` freezes quantities (`heading=0,speed=450` is the demo's, so the SAR's ground stays abeam).

```
fmofp> do surface ELEVATOR 10
fmofp> do surface ELEVATOR 0
fmofp> do surface AILERONS 10
```

The first pitches the nose up at 6 deg/s; the second stops the pitch where it is (the aircraft keeps climbing); the
third rolls right.

## 10.2 Flight control computer (FCS, RT 5)

Ground collision avoidance (GCAS: PULL UP, SINK RATE, TERRAIN under 500 ft of clearance from the terrain-following
radar, ALT LOW) and the performance monitor's envelope (g 9, AoA 25, roll 60, pitch 45, vertical speed 6000 ft/min),
published as `FCS_GCAS_ALERTS` and `FCS_PERF_STATUS`; the surface commands (`FCS_SURFACE_CMD`: AILERONS, ELEVATOR,
RUDDER, FLAPS, SPOILERS, percent of travel) held in `FCS_SURFACE_STATUS`, which the plant flies. DEGRADED when its
sensors go stale.

## 10.3 Navigation (RT 7)

The GPS solution from the plant's pseudoranges (weighted least squares from a closed-form start, WGS-84) fused with
dead reckoning, `NAV_SOLUTION` at 10 Hz. Home is 0 N 0 E, where the constellation gives a good fix.

## 10.4 Flight management system (FMS, RT 12)

The flight-mode profiles (NORMAL, COMBAT, STEALTH, TRAINING, EMERGENCY, each with its g, AoA and engine power limits),
attitude envelope limiting with its warnings, the thrust lever and gear, the autopilot targets, the maneuvers (BREAK
LEFT and RIGHT, DEFENSIVE SPLIT-S, MAXIMUM CLIMB, DIVE; BARREL_ROLL is not implemented, as in the Python), Mach, the
energy state and the energy maneuverability metrics. `FMS_FLIGHT_DATA` (broadcast) is what every display reads.

```
fmofp> do flight-mode COMBAT
fmofp> do autopilot altitude=12000 heading=90
fmofp> do maneuver DIVE 30
fmofp> send FMS_CONTROL_CMD gear_present=1 gear=DOWN
```

## 10.5 Engine management and fuel (RT 3)

The autothrottle (PI), thrust asymmetry, the three tanks with the centre tank's top-up policy, transfers, low, critical
and leak monitoring; the thrust command goes to the plant's engines. `ENG_CMD` commands include
AUTOTHROTTLE_ENGAGE (with a target airspeed), AUTOTHROTTLE_DISENGAGE, SET_THRUST (one engine or both), FUEL_TRANSFER.

## 10.6 Mission computer (RT 6)

The route (waypoints reached within 0.5 nm, the estimated times enroute), targeting (designate, acquire, engage,
assess), the order of battle, threat deviation of the route, the mission phase (PLANNING, INGRESS, OBJECTIVE, EGRESS,
COMPLETE), and since unit 37 the **briefing**: objectives, rules of engagement and intelligence (up to eight of each,
counted in `MSN_STATUS`).

```
fmofp> send MSN_CMD command=SET_PHASE phase=INGRESS
fmofp> do objective Destroy the bridge
fmofp> do roe Weapons tight
fmofp> do intel threat SAM site north
```

**The radars follow the phase** (unit 37): INGRESS, OBJECTIVE and EGRESS put the five radars en route (weather
SURVEILLANCE, terrain-following TERRAIN_FOLLOWING, targeting TARGET_SEARCH, SAR STRIPMAP, AEWC AEWC_SEARCH); COMPLETE
leaves weather and terrain-following and stands the others by; PLANNING changes nothing. The radars are reconfigured
only when the configuration changes, so an operator's command since then stands.

## 10.7 The other partitions

| RT | Partition | What it decides | Commands (examples) |
|---|---|---|---|
| 1 | Avionics | LRU health from the controller's bus-health report, power-on, periodic and initiated built-in tests, fitness, software configuration | `AVN_CMD` FORCE_FAULT, CLEAR_FAULT, RUN_INITIATED_BIT |
| 2 | Communications | radio active above 20 % field, satcom connected when a satellite is in view, the data link | `COM_CMD` SET_RADIO_FREQUENCY, ACQUIRE_SATELLITE, DATALINK_SEND |
| 4 | Environmental control | the cabin checks, the oxygen generator | `ECS_CMD` SET_OXYGEN_RATE |
| 8 | Power management | batteries, the generator, emergency power, cooling, HVAC | `PWR_CMD` SET_GENERATOR_OUTPUT, GENERATOR_AUTO, EMERGENCY_POWER_ON |
| 10 | Sensor management | six sensors' states and health, the sensor fusion's contacts | `SNS_CMD` ACTIVATE, DEACTIVATE (sensor=LIDAR, ...) |
| 19 | Hydraulics | the primary system's pressure against its thresholds, the backup | `HYD_CMD` ACTIVATE_BACKUP |
| 20 | Airframe | the gauges, the landing gear state | `AFR_CMD` |
| 21 | Flight surfaces | ten surfaces moving toward their commands at their rates; flaps, speedbrake, rudder, trim | `FSF_CMD` SET_FLAPS, SET_SPEEDBRAKE |
| 22 | Defensive systems | the radar warning receiver's contacts, flares and chaff, the automatic flare salvo, ECM | `DEF_CMD` DISPENSE_CHAFF, DISPENSE_FLARES, SET_ECM_MODE, INJECT_THREAT |
| 23 | Flight data monitoring | the flight data recorder's ring, the cards | `FDM_CMD` EJECT_STORAGE |
| 26 | Crew alerting | the EICAS's alert list (chapter 8) | `CAS_MODE_CMD` |
| 28 | Stores management | the weapon stations (chapter 8) | `SMS_CMD` |

Known: the flight surfaces terminal follows the sensed attitude with laws that push the wrong way under its message's
own sign convention, so it is not in the aircraft's loop (the FCS's commands fly the plant); closing that loop is a
ticket (ICD README sections 2 and 12).

## 10.8 Tests

Each partition has gtests (`ofp/tests/<name>_test.cpp`), an oracle test against the frozen Python
(`fmofp_bus/tests/test_<name>_oracle.py`, through its stdin tool `fmofp_<name>_tool`) and an end-to-end test on the
real bus (`test_<name>_e2e.py`). `test_plant_dynamics.py` holds the flight dynamics to the frozen class;
`test_mission_briefing.py` holds unit 37. From the prompt: `test fms`, `test fcs`, `test nav`, `test engine`,
`test mission`, `test defensive`, `test systems`.
